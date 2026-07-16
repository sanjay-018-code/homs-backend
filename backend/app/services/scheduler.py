import logging
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.database import get_database
from app.services.excel import generate_daily_excel_report
from app.services.email import send_deadline_reminder

logger = logging.getLogger("homs_scheduler")
scheduler = AsyncIOScheduler()

async def run_daily_excel_job():
    logger.info("Scheduler: Running daily Excel generation job...")
    # Generate for the previous day
    yesterday = datetime.utcnow() - timedelta(days=1)
    file_path = await generate_daily_excel_report(yesterday)
    if file_path:
        logger.info(f"Scheduler: Daily Excel report generated successfully: {file_path}")
    else:
        logger.error("Scheduler: Daily Excel report generation failed.")

async def run_deadline_reminders_check():
    logger.info("Scheduler: Scanning for outpass deadline reminders (<= 24h)...")
    db = get_database()
    now = datetime.utcnow()
    deadline_threshold = now + timedelta(days=1)
    
    # Query outpasses where return time is within 24 hours, not yet returned, and reminder not sent
    query = {
        "status": {"$in": ["Approved", "Student Left"]},
        "in_date": {"$gte": now, "$lte": deadline_threshold},
        "reminder_sent": {"$ne": True}
    }
    
    cursor = db.outpasses.find(query)
    outpasses = await cursor.to_list(length=500)
    
    if not outpasses:
        logger.info("Scheduler: No outpasses require reminders at this time.")
        return

    logger.info(f"Scheduler: Found {len(outpasses)} outpasses requiring deadline reminders.")
    
    for op in outpasses:
        try:
            # Retrieve emails
            student_id = op.get("student_id")
            student_user = await db.users.find_one({"_id": student_id})
            if not student_user:
                logger.warning(f"Scheduler: Student user {student_id} not found for outpass {op['_id']}. Skipping.")
                continue
                
            student_email = student_user.get("email")
            parent_email = student_user.get("parent_email") or student_email # fallback
            
            # Retrieve HOD and Warden emails (can fetch admin/role emails or standard config defaults)
            warden_user = await db.users.find_one({"role": "warden"})
            hod_user = await db.users.find_one({"role": "hod"})
            
            warden_email = warden_user.get("email") if warden_user else "warden@college.edu"
            hod_email = hod_user.get("email") if hod_user else "hod@college.edu"
            
            # Send Email
            await send_deadline_reminder(
                student_email=student_email,
                parent_email=parent_email,
                hod_email=hod_email,
                warden_email=warden_email,
                student_name=student_user.get("name"),
                roll_number=student_user.get("roll_number", "N/A"),
                destination=op.get("destination"),
                in_date=op.get("in_date").strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Mark reminder as sent
            await db.outpasses.update_one(
                {"_id": op["_id"]},
                {"$set": {"reminder_sent": True}}
            )
            logger.info(f"Scheduler: Sent deadline reminder for outpass {op['_id']}")
            
        except Exception as e:
            logger.error(f"Scheduler: Failed to process reminder for outpass {op['_id']}: {str(e)}")

def start_scheduler():
    if not scheduler.running:
        # Schedule daily Excel job at 00:05 UTC every day
        scheduler.add_job(run_daily_excel_job, 'cron', hour=0, minute=5)
        # Check deadline reminders every hour
        scheduler.add_job(run_deadline_reminders_check, 'interval', hours=1)
        scheduler.start()
        logger.info("Scheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shutdown.")
