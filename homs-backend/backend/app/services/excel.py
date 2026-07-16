import os
import logging
from datetime import datetime, timedelta
import pandas as pd
from bson import ObjectId
from app.core.database import get_database

logger = logging.getLogger("homs_excel")

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")

def ensure_reports_directory():
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)
        logger.info(f"Created reports directory at: {REPORTS_DIR}")

async def generate_daily_excel_report(target_date: datetime = None) -> str:
    """
    Generates an Excel spreadsheet containing all outpass events within the 24-hour range of target_date.
    If target_date is not specified, defaults to the previous 24 hours (yesterday).
    Columns: Student Name, Roll Number, Destination, Reason, OUT DateTime, IN DateTime, Status.
    Returns the absolute path to the generated Excel file.
    """
    try:
        ensure_reports_directory()
        
        if target_date is None:
            # Previous 24h
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=1)
        else:
            # 24h around target_date
            start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)
            
        db = get_database()
        
        # Query outpasses that marked exit or entry within this range
        query = {
            "$or": [
                {"exit_time": {"$gte": start_time, "$lt": end_time}},
                {"entry_time": {"$gte": start_time, "$lt": end_time}}
            ]
        }
        
        cursor = db.outpasses.find(query)
        outpasses = await cursor.to_list(length=1000)
        
        data_rows = []
        for op in outpasses:
            data_rows.append({
                "Student Name": op.get("student_name", "N/A"),
                "Roll Number": op.get("roll_number", "N/A"),
                "Destination": op.get("destination", ""),
                "Reason": op.get("reason", ""),
                "OUT DateTime": op.get("exit_time").strftime("%Y-%m-%d %H:%M:%S") if op.get("exit_time") else "Not Exited Yet",
                "IN DateTime": op.get("entry_time").strftime("%Y-%m-%d %H:%M:%S") if op.get("entry_time") else "Not Returned Yet",
                "Status": op.get("status", "N/A")
            })
            
        df = pd.DataFrame(data_rows)
        
        if df.empty:
            # Create a mock DataFrame with correct columns if empty
            df = pd.DataFrame(columns=[
                "Student Name", "Roll Number", "Destination", "Reason", "OUT DateTime", "IN DateTime", "Status"
            ])
            
        date_str = (target_date or (datetime.utcnow() - timedelta(days=1))).strftime("%Y-%m-%d")
        filename = f"outpass_activity_{date_str}.xlsx"
        file_path = os.path.join(REPORTS_DIR, filename)
        
        # Use pandas ExcelWriter to write and format
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Outpass Activity")
            
            # Formatting using openpyxl (adjust columns widths)
            workbook = writer.book
            worksheet = writer.sheets["Outpass Activity"]
            
            # Simple column width adjustment
            for col in worksheet.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)
                
        logger.info(f"Excel report generated successfully at: {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Failed to generate Excel report: {str(e)}")
        # Return none or raise, but we handle gracefully
        return ""
