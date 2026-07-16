import logging
from pydantic import BaseModel, Field
from app.core.config import settings
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from app.core.database import get_database
from app.core.security import get_password_hash
from app.models.user import UserCreate, UserResponse, UserUpdate
from app.models.outpass import OutpassResponse
from app.models.audit import AuditLogResponse
from app.routes.dependencies import RoleChecker

logger = logging.getLogger("homs_admin")
router = APIRouter(prefix="/api/admin", tags=["Admin Management"])

def serialize_value(val):
    if isinstance(val, ObjectId):
        return str(val)
    elif isinstance(val, list):
        return [serialize_value(item) for item in val]
    elif isinstance(val, dict):
        return {k: serialize_value(v) for k, v in val.items()}
    return val

def get_changed_fields(old_dict: dict, new_dict: dict) -> dict:
    """
    Compares two dicts and returns a map of changes: {field: [old_val, new_val]}
    """
    changes = {}
    for key, value in new_dict.items():
        if key in ["password", "password_hash"]: # skip sensitive logging
            continue
        old_val = old_dict.get(key)
        if old_val != value:
            changes[key] = [serialize_value(old_val), serialize_value(value)]
    return changes

async def log_admin_action(db, actor: UserResponse, action: str, model: str, affected_id: ObjectId, old_state: dict, new_state: dict):
    changes = get_changed_fields(old_state, new_state)
    if not changes:
        if "DELETE" in action:
            changes = {k: [serialize_value(v), None] for k, v in old_state.items() if k not in ["password", "password_hash"]}
        else:
            return
        
    audit_doc = {
        "timestamp": datetime.utcnow(),
        "actor_id": ObjectId(actor.id),
        "actor_name": actor.name,
        "action": action,
        "affected_model": model,
        "affected_id": affected_id,
        "changes": changes,
        "immutable": True
    }
    await db.audit_logs.insert_one(audit_doc)

@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    
    # Check if email exists
    existing_email = await db.users.find_one({"email": user_in.email})
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Check if roll number exists (only for students)
    if user_in.roll_number:
        existing_roll = await db.users.find_one({"roll_number": user_in.roll_number})
        if existing_roll:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Roll number already registered"
            )
            
    # Check roles
    valid_roles = ["student", "advisor", "warden", "hod", "security", "admin"]
    if user_in.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of {valid_roles}"
        )
        
    password_hash = get_password_hash(user_in.password)
    user_dict = user_in.dict()
    user_dict.pop("password")
    user_dict["password_hash"] = password_hash
    if not user_dict.get("roll_number"):
        user_dict.pop("roll_number", None)
    
    result = await db.users.insert_one(user_dict)
    user_dict["_id"] = result.inserted_id
    
    # Log admin audit trail
    await log_admin_action(db, current_user, "CREATE_USER", "User", result.inserted_id, {}, user_dict)
    
    return UserResponse(**user_dict)

@router.get("/users", response_model=list[UserResponse])
async def get_all_users(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    cursor = db.users.find().sort("name", 1)
    results = await cursor.to_list(length=500)
    
    # Extract student IDs to run a single optimized aggregation
    student_ids = [u["_id"] for u in results if u.get("role") == "student"]
    
    recent_outpasses = {}
    if student_ids:
        pipeline = [
            {"$match": {"student_id": {"$in": student_ids}}},
            {"$sort": {"created_at": -1}},
            {
                "$group": {
                    "_id": "$student_id",
                    "doc": {"$first": "$$ROOT"}
                }
            }
        ]
        cursor_agg = db.outpasses.aggregate(pipeline)
        agg_results = await cursor_agg.to_list(length=len(student_ids))
        for res in agg_results:
            recent_outpasses[res["_id"]] = res["doc"]
            
    user_responses = []
    for u in results:
        # Convert _id to string for mapping to id field
        u_dict = {**u, "id": str(u["_id"])}
        
        # If user is a student, compute live status and location condition
        if u.get("role") == "student":
            last_outpass = recent_outpasses.get(u["_id"])
            if last_outpass:
                status_val = last_outpass.get("status")
                u_dict["active_outpass_status"] = status_val
                if status_val == "Student Left":
                    u_dict["live_status"] = "Outside Campus"
                else:
                    u_dict["live_status"] = "Inside Campus"
            else:
                u_dict["live_status"] = "Inside Campus"
                u_dict["active_outpass_status"] = "No Outpasses"
                
        user_responses.append(UserResponse(**u_dict))
        
    return user_responses

@router.get("/users/{id}/outpasses", response_model=list[OutpassResponse])
async def get_student_outpass_history(
    id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    try:
        student_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID format")
        
    cursor = db.outpasses.find({"student_id": student_oid}).sort("created_at", -1)
    results = await cursor.to_list(length=500)
    return [OutpassResponse(**op) for op in results]

@router.put("/users/{id}", response_model=UserResponse)
async def update_user(
    id: str,
    user_update: UserUpdate,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    try:
        user_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID format")
        
    old_user = await db.users.find_one({"_id": user_oid})
    if not old_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    update_data = {k: v for k, v in user_update.dict(exclude_none=True).items()}
    
    # Process password hashing if present
    if "password" in update_data:
        from app.core.security import get_password_hash
        update_data["password_hash"] = get_password_hash(update_data.pop("password"))
        
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update parameters provided")
        
    # Generate new state prediction
    new_user_state = {**old_user, **update_data}
    
    # Update user in DB
    await db.users.update_one({"_id": user_oid}, {"$set": update_data})
    
    # Log Audit Log
    await log_admin_action(db, current_user, "UPDATE_USER", "User", user_oid, old_user, new_user_state)
    
    updated_user = await db.users.find_one({"_id": user_oid})
    return UserResponse(**updated_user)

@router.put("/outpasses/{id}", response_model=OutpassResponse)
async def update_outpass(
    id: str,
    outpass_update: dict,  # Freeform JSON update for admin
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    try:
        outpass_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid outpass ID format")
        
    old_outpass = await db.outpasses.find_one({"_id": outpass_oid})
    if not old_outpass:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outpass not found")
        
    # Parse update payload dates if provided
    for date_field in ["out_date", "in_date", "exit_time", "entry_time"]:
        if date_field in outpass_update and outpass_update[date_field]:
            try:
                outpass_update[date_field] = datetime.fromisoformat(outpass_update[date_field].replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid date format for field: {date_field}")
                
    if not outpass_update:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")
        
    new_outpass_state = {**old_outpass, **outpass_update}
    
    await db.outpasses.update_one({"_id": outpass_oid}, {"$set": outpass_update})
    
    # Log Audit Log
    await log_admin_action(db, current_user, "UPDATE_OUTPASS", "Outpass", outpass_oid, old_outpass, new_outpass_state)
    
    updated_outpass = await db.outpasses.find_one({"_id": outpass_oid})
    return OutpassResponse(**updated_outpass)

@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def get_audit_logs(
    action: Optional[str] = None,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    query = {}
    if action:
        query["action"] = action
        
    cursor = db.audit_logs.find(query).sort("timestamp", -1)
    results = await cursor.to_list(length=200)
    sanitized = [serialize_value(log) for log in results]
    return [AuditLogResponse(**log) for log in sanitized]

@router.post("/rollback/{audit_log_id}")
async def rollback_changes(
    audit_log_id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    try:
        log_oid = ObjectId(audit_log_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Audit Log ID format")
        
    audit_log = await db.audit_logs.find_one({"_id": log_oid})
    if not audit_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit Log not found")
        
    model = audit_log["affected_model"]
    affected_id = audit_log["affected_id"]
    changes = audit_log["changes"]
    
    # Prepare the rollback state (reverting fields to their 'old' values)
    rollback_data = {}
    for field, vals in changes.items():
        # vals is a list [old_value, new_value]
        # We restore the old_value (vals[0])
        rollback_data[field] = vals[0]
        
    if not rollback_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes found in audit log to rollback")
        
    if model == "User":
        old_user = await db.users.find_one({"_id": affected_id})
        if not old_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target User for rollback no longer exists")
        
        new_state = {**old_user, **rollback_data}
        await db.users.update_one({"_id": affected_id}, {"$set": rollback_data})
        
        # Log the rollback itself
        await log_admin_action(db, current_user, "ROLLBACK", "User", affected_id, old_user, new_state)
        
    elif model == "Outpass":
        old_outpass = await db.outpasses.find_one({"_id": affected_id})
        if not old_outpass:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target Outpass for rollback no longer exists")
            
        # Re-parse datetimes if rollback involves dates
        for date_field in ["out_date", "in_date", "exit_time", "entry_time"]:
            if date_field in rollback_data and isinstance(rollback_data[date_field], str):
                try:
                    rollback_data[date_field] = datetime.fromisoformat(rollback_data[date_field].replace("Z", "+00:00"))
                except ValueError:
                    pass
                    
        new_state = {**old_outpass, **rollback_data}
        await db.outpasses.update_one({"_id": affected_id}, {"$set": rollback_data})
        
        # Log the rollback itself
        await log_admin_action(db, current_user, "ROLLBACK", "Outpass", affected_id, old_outpass, new_state)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Rollback unsupported for model: {model}")
        
    return {"message": "Rollback executed successfully", "affected_model": model, "affected_id": str(affected_id)}

@router.delete("/users/{id}", status_code=status.HTTP_200_OK)
async def delete_user(
    id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    try:
        user_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID format")
        
    old_user = await db.users.find_one({"_id": user_oid})
    if not old_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Prevent self-deletion
    if str(old_user["_id"]) == str(current_user.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Administrators cannot delete their own accounts")
        
    # Delete the user
    await db.users.delete_one({"_id": user_oid})
    
    # Log admin audit trail
    await log_admin_action(db, current_user, "DELETE_USER", "User", user_oid, old_user, {})
    
    return {"message": "User deleted successfully", "id": id}

@router.get("/outpasses", response_model=list[OutpassResponse])
async def get_all_outpasses(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    cursor = db.outpasses.find().sort("created_at", -1)
    results = await cursor.to_list(length=1000)
    return [OutpassResponse(**op) for op in results]

@router.delete("/outpasses/{id}", status_code=status.HTTP_200_OK)
async def delete_outpass(
    id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    try:
        outpass_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid outpass ID format")
        
    old_outpass = await db.outpasses.find_one({"_id": outpass_oid})
    if not old_outpass:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outpass not found")
        
    # Delete outpass
    await db.outpasses.delete_one({"_id": outpass_oid})
    
    # Log admin audit trail
    await log_admin_action(db, current_user, "DELETE_OUTPASS", "Outpass", outpass_oid, old_outpass, {})
    
    return {"message": "Outpass record deleted successfully", "id": id}


class SMTPSettingsUpdate(BaseModel):
    smtp_host: str = Field(..., example="smtp.gmail.com")
    smtp_port: int = Field(..., example=587)
    smtp_user: str = Field(..., example="user@gmail.com")
    smtp_password: Optional[str] = Field(None, example="mypassword")
    email_from: str = Field(..., example="user@gmail.com")
    is_enabled: bool = True
    redirect_to_sender: bool = False


@router.get("/settings/smtp")
async def get_smtp_settings(current_user: UserResponse = Depends(RoleChecker(["admin"]))):
    db = get_database()
    config = await db.system_settings.find_one({"_id": "smtp"})
    if not config:
        return {
            "smtp_host": settings.SMTP_HOST or "",
            "smtp_port": settings.SMTP_PORT or 587,
            "smtp_user": settings.SMTP_USER or "",
            "has_password": bool(settings.SMTP_PASSWORD),
            "email_from": settings.EMAIL_FROM or "",
            "is_enabled": True,
            "redirect_to_sender": False
        }
    
    return {
        "smtp_host": config.get("smtp_host", ""),
        "smtp_port": config.get("smtp_port", 587),
        "smtp_user": config.get("smtp_user", ""),
        "has_password": bool(config.get("smtp_password")),
        "email_from": config.get("email_from", ""),
        "is_enabled": config.get("is_enabled", True),
        "redirect_to_sender": config.get("redirect_to_sender", False)
    }


@router.put("/settings/smtp")
async def update_smtp_settings(
    payload: SMTPSettingsUpdate,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
):
    db = get_database()
    existing = await db.system_settings.find_one({"_id": "smtp"})
    
    update_dict = {
        "smtp_host": payload.smtp_host,
        "smtp_port": payload.smtp_port,
        "smtp_user": payload.smtp_user,
        "email_from": payload.email_from,
        "is_enabled": payload.is_enabled,
        "redirect_to_sender": payload.redirect_to_sender
    }
    
    if payload.smtp_password is not None:
        if payload.smtp_password.strip() != "" and payload.smtp_password != "********":
            update_dict["smtp_password"] = payload.smtp_password
    elif existing and "smtp_password" in existing:
        update_dict["smtp_password"] = existing["smtp_password"]
        
    await db.system_settings.update_one(
        {"_id": "smtp"},
        {"$set": update_dict},
        upsert=True
    )
    
    # Log this configuration action in audit logs
    old_state = existing or {}
    new_state = {**old_state, **update_dict}
    # Avoid recording cleartext password in database audit log
    if "smtp_password" in old_state:
        old_state = {**old_state, "smtp_password": "********"}
    if "smtp_password" in new_state:
        new_state = {**new_state, "smtp_password": "********"}
    await log_admin_action(db, current_user, "UPDATE_SMTP_SETTINGS", "SystemSettings", "smtp", old_state, new_state)
    
    return {"message": "SMTP Settings updated successfully."}
