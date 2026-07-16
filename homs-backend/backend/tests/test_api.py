import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from bson import ObjectId
from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash

# Set test environment configurations
@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
async def test_db_setup():
    await connect_to_mongo()
    db = get_database()
    # Clear collections before test runs
    await db.users.delete_many({})
    await db.outpasses.delete_many({})
    await db.audit_logs.delete_many({})
    yield
    await close_mongo_connection()

@pytest.mark.asyncio
async def test_full_system_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Register users for all required workflow roles
        roles = {
            "student": {"name": "Alice Student", "email": "alice@student.com", "role": "student", "roll_number": "STU101", "parent_email": "parent@alice.com", "password": "password123"},
            "advisor": {"name": "Bob Advisor", "email": "bob@faculty.com", "role": "advisor", "password": "password123"},
            "warden": {"name": "Charlie Warden", "email": "charlie@hostel.com", "role": "warden", "password": "password123"},
            "hod": {"name": "Dave HOD", "email": "dave@department.com", "role": "hod", "password": "password123"},
            "security": {"name": "Sam Security", "email": "sam@gate.com", "role": "security", "password": "password123"},
            "admin": {"name": "Arthur Admin", "email": "arthur@admin.com", "role": "admin", "password": "password123"},
        }
        
        db = get_database()
        tokens = {}
        for role_name, user_data in roles.items():
            user_doc = user_data.copy()
            pwd = user_doc.pop("password")
            user_doc["password_hash"] = get_password_hash(pwd)
            user_doc["enrollment_status"] = "active"
            await db.users.insert_one(user_doc)
            
            # Log in to get token
            login_data = {
                "username": user_data["email"],
                "password": pwd
            }
            login_response = await ac.post("/api/auth/login", data=login_data)
            assert login_response.status_code == 200
            tokens[role_name] = login_response.json()["access_token"]
            
        # Headers helpers
        headers_student = {"Authorization": f"Bearer {tokens['student']}"}
        headers_advisor = {"Authorization": f"Bearer {tokens['advisor']}"}
        headers_warden = {"Authorization": f"Bearer {tokens['warden']}"}
        headers_hod = {"Authorization": f"Bearer {tokens['hod']}"}
        headers_security = {"Authorization": f"Bearer {tokens['security']}"}
        headers_admin = {"Authorization": f"Bearer {tokens['admin']}"}

        # 2. Student applies for outpass
        outpass_data = {
            "destination": "City Center mall",
            "reason": "Purchase books and check health",
            "out_date": "2026-07-20T10:00:00",
            "in_date": "2026-07-20T18:00:00"
        }
        
        apply_res = await ac.post("/api/outpass/apply", json=outpass_data, headers=headers_student)
        assert apply_res.status_code == 201
        outpass_id = apply_res.json()["id"]
        assert apply_res.json()["status"] == "Pending"

        # 3. Test non-bypassable sequence (Warden trying to approve before Advisor)
        warden_fail_res = await ac.post(f"/api/outpass/{outpass_id}/approve", json={"comments": "Looks fine"}, headers=headers_warden)
        assert warden_fail_res.status_code == 400
        assert "Warden can only approve 'Advisor Approved'" in warden_fail_res.json()["detail"]

        # 4. Advisor approves
        adv_res = await ac.post(f"/api/outpass/{outpass_id}/approve", json={"comments": "Checked marks"}, headers=headers_advisor)
        assert adv_res.status_code == 200
        assert adv_res.json()["status"] == "Advisor Approved"

        # 5. HOD trying to approve before Warden
        hod_fail_res = await ac.post(f"/api/outpass/{outpass_id}/approve", json={"comments": "Proceed"}, headers=headers_hod)
        assert hod_fail_res.status_code == 400
        assert "HOD can only approve 'Warden Approved'" in hod_fail_res.json()["detail"]

        # 6. Warden approves
        warden_res = await ac.post(f"/api/outpass/{outpass_id}/approve", json={"comments": "No violations"}, headers=headers_warden)
        assert warden_res.status_code == 200
        assert warden_res.json()["status"] == "Warden Approved"

        # 7. HOD approves (generates QR Token and sends email alerts)
        hod_res = await ac.post(f"/api/outpass/{outpass_id}/approve", json={"comments": "Enjoy your break"}, headers=headers_hod)
        assert hod_res.status_code == 200
        assert hod_res.json()["status"] == "Approved"
        qr_token = hod_res.json()["qr_token"]
        assert qr_token is not None

        # 8. Test Gate EXIT marking
        exit_res = await ac.post("/api/outpass/mark-gate", json={"outpassId": qr_token, "action": "EXIT"}, headers=headers_security)
        assert exit_res.status_code == 200
        assert exit_res.json()["status"] == "Student Left"
        assert exit_res.json()["exit_time"] is not None

        # 9. Test Gate ENTRY marking
        entry_res = await ac.post("/api/outpass/mark-gate", json={"outpassId": outpass_id, "action": "ENTRY"}, headers=headers_security)
        assert entry_res.status_code == 200
        assert entry_res.json()["status"] == "Student Returned"
        assert entry_res.json()["entry_time"] is not None

        # 10. Test Admin user modification audit trails
        alice_user_id = apply_res.json()["student_id"]
        admin_update_res = await ac.put(
            f"/api/admin/users/{alice_user_id}",
            json={"name": "Alice Modified", "email": "alice_mod@student.com"},
            headers=headers_admin
        )
        assert admin_update_res.status_code == 200
        assert admin_update_res.json()["name"] == "Alice Modified"

        # 11. Fetch Audit Logs
        audit_res = await ac.get("/api/admin/audit-logs", headers=headers_admin)
        assert audit_res.status_code == 200
        logs = audit_res.json()
        assert len(logs) > 0
        latest_log = logs[0]
        assert latest_log["action"] == "UPDATE_USER"
        assert "name" in latest_log["changes"]
        assert latest_log["changes"]["name"] == ["Alice Student", "Alice Modified"]

        # 12. Test Rollback
        rollback_res = await ac.post(f"/api/admin/rollback/{latest_log['id']}", headers=headers_admin)
        assert rollback_res.status_code == 200
        
        # Check student name reverted to Alice Student
        student_check = await ac.get("/api/auth/me", headers=headers_student)
        assert student_check.status_code == 200
        # Wait, Alice's token was generated using her old email address. It should still fetch because we authenticate on MongoDB ID (which doesn't change)!
        assert student_check.json()["name"] == "Alice Student"
        assert student_check.json()["email"] == "alice@student.com"
