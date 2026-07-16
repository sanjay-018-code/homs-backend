import secrets
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from app.core.database import get_database
from app.models.user import UserResponse
from app.models.outpass import OutpassCreate, OutpassResponse, OutpassApprove, OutpassReject
from app.routes.dependencies import get_current_user, RoleChecker, get_role_based_outpass_filter
from app.services.email import (
    send_approval_notification,
    send_submission_notification,
    send_rejection_notification,
    send_gate_movement_notification,
    send_intermediate_approval_notification
)
from app.services.excel import generate_daily_excel_report

logger = logging.getLogger("homs_outpass")
router = APIRouter(prefix="/api/outpass", tags=["Outpass Management"])

@router.post("/apply", response_model=OutpassResponse, status_code=status.HTTP_201_CREATED)
async def apply_outpass(
    outpass_in: OutpassCreate,
    current_user: UserResponse = Depends(RoleChecker(["student"]))
):
    db = get_database()
    
    # Check if there is already an active/pending outpass for this student
    existing_pending = await db.outpasses.find_one({
        "student_id": ObjectId(current_user.id),
        "status": {"$in": ["Pending", "Advisor Approved", "Warden Approved", "Approved", "Student Left"]}
    })
    if existing_pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a pending or active outpass request"
        )
        
    outpass_dict = outpass_in.dict()
    outpass_dict["student_id"] = ObjectId(current_user.id)
    outpass_dict["student_name"] = current_user.name
    outpass_dict["roll_number"] = current_user.roll_number or "N/A"
    outpass_dict["room"] = current_user.hostel_details.room if current_user.hostel_details else "N/A"
    outpass_dict["hostel_name"] = current_user.hostel_details.hostel_name if current_user.hostel_details else "N/A"
    outpass_dict["status"] = "Pending"
    outpass_dict["qr_token"] = None
    outpass_dict["rejection_reason"] = None
    outpass_dict["exit_time"] = None
    outpass_dict["entry_time"] = None
    outpass_dict["created_at"] = datetime.utcnow()
    
    # Initialize history
    outpass_dict["history"] = [{
        "status": "Pending",
        "updated_by": ObjectId(current_user.id),
        "updated_by_name": current_user.name,
        "updated_at": datetime.utcnow(),
        "comments": "Outpass submitted by student."
    }]
    
    result = await db.outpasses.insert_one(outpass_dict)
    outpass_dict["_id"] = result.inserted_id
    
    # Retrieve Advisor email to notify them of new pending outpass
    advisor_user = await db.users.find_one({"role": "advisor"})
    advisor_email = advisor_user.get("email") if advisor_user else "advisor@faculty.com"
    try:
        await send_submission_notification(
            student_email=current_user.email,
            advisor_email=advisor_email,
            student_name=outpass_dict["student_name"],
            roll_number=outpass_dict["roll_number"],
            destination=outpass_dict["destination"],
            out_date=outpass_dict["out_date"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(outpass_dict["out_date"], datetime) else str(outpass_dict["out_date"]),
            in_date=outpass_dict["in_date"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(outpass_dict["in_date"], datetime) else str(outpass_dict["in_date"])
        )
    except Exception as e:
        logger.error(f"Failed to send submission outpass email: {str(e)}")
        
    return OutpassResponse(**outpass_dict)

@router.get("/my-requests", response_model=list[OutpassResponse])
async def get_my_requests(current_user: UserResponse = Depends(get_current_user)):
    db = get_database()
    query = get_role_based_outpass_filter(current_user)
    cursor = db.outpasses.find(query).sort("created_at", -1)
    results = await cursor.to_list(length=100)
    return [OutpassResponse(**op) for op in results]

@router.get("/pending", response_model=list[OutpassResponse])
async def get_pending_outpasses(current_user: UserResponse = Depends(get_current_user)):
    db = get_database()
    query = get_role_based_outpass_filter(current_user)
    
    # Filter by specific pending status relevant to current user's review level
    if current_user.role == "advisor":
        query["status"] = "Pending"
    elif current_user.role == "warden":
        query["status"] = "Advisor Approved"
    elif current_user.role == "hod":
        query["status"] = "Warden Approved"
    elif current_user.role == "security":
        query["status"] = "Approved"
        
    cursor = db.outpasses.find(query).sort("created_at", -1)
    results = await cursor.to_list(length=100)
    return [OutpassResponse(**op) for op in results]

@router.post("/{id}/approve", response_model=OutpassResponse)
async def approve_outpass(
    id: str,
    approve_data: OutpassApprove,
    current_user: UserResponse = Depends(RoleChecker(["advisor", "warden", "hod"]))
):
    db = get_database()
    try:
        outpass_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid outpass ID format")
        
    outpass = await db.outpasses.find_one({"_id": outpass_oid})
    if not outpass:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outpass request not found")
        
    current_status = outpass["status"]
    new_status = None
    
    # Strict validation of sequence
    if current_user.role == "advisor":
        if current_status != "Pending":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Advisor can only approve 'Pending' outpasses")
        new_status = "Advisor Approved"
        
    elif current_user.role == "warden":
        if current_status != "Advisor Approved":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Warden can only approve 'Advisor Approved' outpasses")
        new_status = "Warden Approved"
        
    elif current_user.role == "hod":
        if current_status != "Warden Approved":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="HOD can only approve 'Warden Approved' outpasses")
        new_status = "Approved"
        
    if not new_status:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status progression transition")
        
    update_fields = {
        "status": new_status,
    }
    
    # Generate QR Token if approved by HOD
    qr_token = None
    if new_status == "Approved":
        qr_token = f"OUT-{secrets.token_hex(8).upper()}"
        update_fields["qr_token"] = qr_token
        
    history_item = {
        "status": new_status,
        "updated_by": ObjectId(current_user.id),
        "updated_by_name": current_user.name,
        "updated_at": datetime.utcnow(),
        "comments": approve_data.comments or f"Approved by {current_user.role}"
    }

    # Atomic guard: the status condition is part of the update filter itself,
    # so if two requests race, only the first one to reach Mongo can match
    # current_status and flip it. The second gets a null result instead of
    # silently double-applying the transition.
    updated_outpass = await db.outpasses.find_one_and_update(
        {"_id": outpass_oid, "status": current_status},
        {
            "$set": update_fields,
            "$push": {"history": history_item}
        },
        return_document=True
    )

    if not updated_outpass:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This outpass was already updated by another action. Please refresh."
        )
    
    # If intermediate approval, notify next approver
    if new_status in ["Advisor Approved", "Warden Approved"]:
        next_role = "warden" if new_status == "Advisor Approved" else "hod"
        next_user = await db.users.find_one({"role": next_role})
        next_email = next_user.get("email") if next_user else f"{next_role}@college.edu"
        try:
            await send_intermediate_approval_notification(
                next_approver_email=next_email,
                next_approver_role=next_role,
                student_name=outpass.get("student_name"),
                roll_number=outpass.get("roll_number", "N/A"),
                destination=outpass.get("destination"),
                out_date=outpass.get("out_date").strftime("%Y-%m-%d %H:%M:%S") if isinstance(outpass.get("out_date"), datetime) else str(outpass.get("out_date")),
                in_date=outpass.get("in_date").strftime("%Y-%m-%d %H:%M:%S") if isinstance(outpass.get("in_date"), datetime) else str(outpass.get("in_date"))
            )
        except Exception as e:
            logger.error(f"Failed to send intermediate approval email: {str(e)}")
            
    # If final approval (HOD), trigger Email Notifications
    if new_status == "Approved" and qr_token:
        # Retrieve student parent email
        student = await db.users.find_one({"_id": outpass["student_id"]})
        student_email = student.get("email") if student else "student@college.edu"
        parent_email = student.get("parent_email") if student and student.get("parent_email") else student_email
        
        # Warden/HOD email details
        hod_email = current_user.email
        warden_user = await db.users.find_one({"role": "warden"})
        warden_email = warden_user.get("email") if warden_user else "warden@college.edu"
        
        try:
            await send_approval_notification(
                student_email=student_email,
                parent_email=parent_email,
                hod_email=hod_email,
                warden_email=warden_email,
                student_name=outpass.get("student_name"),
                roll_number=outpass.get("roll_number", "N/A"),
                destination=outpass.get("destination"),
                out_date=outpass.get("out_date").strftime("%Y-%m-%d %H:%M:%S"),
                in_date=outpass.get("in_date").strftime("%Y-%m-%d %H:%M:%S"),
                qr_token=qr_token
            )
        except Exception as e:
            logger.error(f"Failed to send outpass approval emails: {str(e)}")

    return OutpassResponse(**updated_outpass)

@router.post("/{id}/reject", response_model=OutpassResponse)
async def reject_outpass(
    id: str,
    reject_data: OutpassReject,
    current_user: UserResponse = Depends(RoleChecker(["advisor", "warden", "hod"]))
):
    db = get_database()
    try:
        outpass_oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid outpass ID format")
        
    outpass = await db.outpasses.find_one({"_id": outpass_oid})
    if not outpass:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outpass request not found")
        
    # Check that it's in a status they can review
    current_status = outpass["status"]
    if current_user.role == "advisor" and current_status != "Pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Advisor can only reject 'Pending' requests")
    elif current_user.role == "warden" and current_status != "Advisor Approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Warden can only reject 'Advisor Approved' requests")
    elif current_user.role == "hod" and current_status != "Warden Approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="HOD can only reject 'Warden Approved' requests")
        
    history_item = {
        "status": "Rejected",
        "updated_by": ObjectId(current_user.id),
        "updated_by_name": current_user.name,
        "updated_at": datetime.utcnow(),
        "comments": f"Rejected by {current_user.role}: {reject_data.rejection_reason}"
    }
    
    updated_outpass = await db.outpasses.find_one_and_update(
        {"_id": outpass_oid, "status": current_status},
        {
            "$set": {
                "status": "Rejected",
                "rejection_reason": reject_data.rejection_reason
            },
            "$push": {"history": history_item}
        },
        return_document=True
    )

    if not updated_outpass:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This outpass was already updated by another action. Please refresh."
        )
    
    # Retrieve student email to notify them of rejection
    student = await db.users.find_one({"_id": outpass["student_id"]})
    student_email = student.get("email") if student else "student@college.edu"
    try:
        await send_rejection_notification(
            student_email=student_email,
            student_name=outpass.get("student_name"),
            roll_number=outpass.get("roll_number", "N/A"),
            destination=outpass.get("destination"),
            rejected_by_role=current_user.role,
            rejection_reason=reject_data.rejection_reason
        )
    except Exception as e:
        logger.error(f"Failed to send rejection outpass email: {str(e)}")
        
    return OutpassResponse(**updated_outpass)

@router.post("/mark-gate", response_model=OutpassResponse)
async def mark_gate(
    payload: dict,
    current_user: UserResponse = Depends(RoleChecker(["security", "admin"]))
):
    outpass_id = payload.get("outpassId")
    action = payload.get("action")
    
    if not outpass_id or action not in ["EXIT", "ENTRY"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="outpassId and action ('EXIT' or 'ENTRY') are required"
        )
        
    db = get_database()
    
    # Try finding by MongoDB ID or QR Token
    query = {}
    try:
        query["_id"] = ObjectId(outpass_id)
    except Exception:
        # Fallback to match by qr_token
        query["qr_token"] = outpass_id
        
    outpass = await db.outpasses.find_one(query)
    if not outpass:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outpass record not found")
        
    current_status = outpass["status"]
    history_item = None
    update_fields = {}
    
    if action == "EXIT":
        if current_status != "Approved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot mark EXIT. Outpass status is: {current_status}. Must be Approved."
            )
        update_fields["status"] = "Student Left"
        update_fields["exit_time"] = datetime.utcnow()
        history_item = {
            "status": "Student Left",
            "updated_by": ObjectId(current_user.id),
            "updated_by_name": current_user.name,
            "updated_at": datetime.utcnow(),
            "comments": "Gate EXIT scanned and recorded."
        }
    elif action == "ENTRY":
        if current_status != "Student Left":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot mark ENTRY. Outpass status is: {current_status}. Must be Student Left."
            )
        update_fields["status"] = "Student Returned"
        update_fields["entry_time"] = datetime.utcnow()
        history_item = {
            "status": "Student Returned",
            "updated_by": ObjectId(current_user.id),
            "updated_by_name": current_user.name,
            "updated_at": datetime.utcnow(),
            "comments": "Gate ENTRY scanned and recorded."
        }
        
    await db.outpasses.update_one(
        {"_id": outpass["_id"]},
        {
            "$set": update_fields,
            "$push": {"history": history_item}
        }
    )
    
    # Immediately trigger spreadsheet update for daily record
    try:
        await generate_daily_excel_report(datetime.utcnow())
    except Exception as e:
        logger.error(f"Failed to update Excel report on gate action: {str(e)}")
        
    updated_outpass = await db.outpasses.find_one({"_id": outpass["_id"]})
    
    # Retrieve student and parent email to notify them of gate movement
    student = await db.users.find_one({"_id": outpass["student_id"]})
    if student:
        student_email = student.get("email")
        parent_email = student.get("parent_email") if student.get("parent_email") else student_email
        direction = "OUT" if action == "EXIT" else "IN"
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " UTC"
        try:
            await send_gate_movement_notification(
                student_email=student_email,
                parent_email=parent_email,
                student_name=outpass.get("student_name"),
                roll_number=outpass.get("roll_number", "N/A"),
                destination=outpass.get("destination"),
                direction=direction,
                timestamp=timestamp
            )
        except Exception as e:
            logger.error(f"Failed to send gate movement outpass email: {str(e)}")
            
    return OutpassResponse(**updated_outpass)
