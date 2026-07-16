import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

logger = logging.getLogger("homs_email")

# --- Brevo SMTP Configuration (hardcoded) ---
BREVO_SMTP_HOST = "smtp-relay.brevo.com"
BREVO_SMTP_PORT = 587
BREVO_SMTP_USER = "b2285c001@smtp-brevo.com"
BREVO_SMTP_PASSWORD = "xsmtpsib-7a784285f3c0c7dce10f38c24ccc99af1dd7f62a92046560f2a735ceeb3a7c9b-cxWjbgeWWs1jhIE6"
BREVO_EMAIL_FROM = "contact.zenlyft@gmail.com"

async def send_smtp_email(to_emails: List[str], subject: str, html_content: str):
    """
    Sends SMTP email via Brevo relay to a list of recipients.
    Gracefully logs email to console and returns on failure.
    """
    to_emails_filtered = [email for email in to_emails if email]
    if not to_emails_filtered:
        logger.warning("No recipient emails provided. Skipping email send.")
        return

    logger.info(f"Preparing to send email via Brevo. Recipients: {to_emails_filtered}. Subject: {subject}")

    msg = MIMEMultipart()
    msg["From"] = BREVO_EMAIL_FROM
    msg["To"] = ", ".join(to_emails_filtered)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_content, "html"))

    try:
        import asyncio
        loop = asyncio.get_running_loop()

        def _send():
            server = smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT)
            server.starttls()
            server.login(BREVO_SMTP_USER, BREVO_SMTP_PASSWORD)
            server.sendmail(BREVO_EMAIL_FROM, to_emails_filtered, msg.as_string())
            server.quit()

        await loop.run_in_executor(None, _send)
        logger.info("Email sent successfully via Brevo SMTP.")
    except Exception as e:
        logger.error(f"Brevo SMTP Send Failed: {str(e)}. Fallback to console log:")
        logger.info(f"To: {to_emails_filtered}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Body: {html_content}")

def get_base_html_template(accent_class: str, body_content: str) -> str:
    # accent_class: 'accent-student' (#2563eb), 'accent-staff' (#7c3aed), 'accent-parent' (#0f766e), 'accent-alert' (#dc2626)
    accent_colors = {
        "accent-student": "#2563eb",
        "accent-staff": "#7c3aed",
        "accent-parent": "#0f766e",
        "accent-alert": "#dc2626"
    }
    color = accent_colors.get(accent_class, "#2563eb")
    
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #334155;
      margin: 0;
      padding: 0;
      -webkit-font-smoothing: antialiased;
    }}
    .wrapper {{
      width: 100%;
      background-color: #f8fafc;
      padding: 30px 15px;
      box-sizing: border-box;
    }}
    .container {{
      max-width: 580px;
      margin: 0 auto;
      background-color: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
    }}
    .accent-bar {{
      height: 4px;
      width: 100%;
      background-color: {color};
    }}
    .content {{
      padding: 35px;
    }}
    .logo {{
      font-size: 11px;
      font-weight: 800;
      color: #64748b;
      letter-spacing: 1.5px;
      margin-bottom: 25px;
      text-transform: uppercase;
      border-bottom: 1px solid #f1f5f9;
      padding-bottom: 15px;
    }}
    h2 {{
      font-size: 18px;
      font-weight: 700;
      color: #0f172a;
      margin-top: 0;
      margin-bottom: 15px;
      line-height: 1.3;
    }}
    p {{
      font-size: 14px;
      line-height: 1.6;
      color: #475569;
      margin-top: 0;
      margin-bottom: 15px;
    }}
    .highlight-box {{
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 20px;
      margin: 25px 0;
    }}
    .table-details {{
      width: 100%;
      border-collapse: collapse;
    }}
    .table-details td {{
      padding: 8px 0;
      font-size: 13.5px;
      line-height: 1.5;
      vertical-align: top;
    }}
    .table-details td.label {{
      width: 35%;
      font-weight: 600;
      color: #64748b;
    }}
    .table-details td.value {{
      color: #1e293b;
      font-weight: 500;
    }}
    .footer {{
      font-size: 11px;
      color: #94a3b8;
      text-align: center;
      margin-top: 35px;
      border-top: 1px solid #f1f5f9;
      padding-top: 15px;
    }}
    .qr-container {{
      text-align: center;
      margin: 25px 0 10px 0;
      padding: 20px;
      background-color: #f8fafc;
      border: 1px dashed #cbd5e1;
      border-radius: 8px;
    }}
    .qr-code {{
      width: 150px;
      height: 150px;
      margin-bottom: 10px;
    }}
    .qr-token {{
      font-family: monospace;
      font-weight: 700;
      font-size: 14px;
      color: #0f172a;
      letter-spacing: 0.5px;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="container">
      <div class="accent-bar"></div>
      <div class="content">
        <div class="logo">Hostel Outpass Management System</div>
        {body_content}
        <div class="footer">
          This is an automated system notification from H.O.M.S. Please do not reply directly to this email.
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""

async def send_approval_notification(
    student_email: str,
    parent_email: str,
    hod_email: str,
    warden_email: str,
    student_name: str,
    roll_number: str,
    destination: str,
    out_date: str,
    in_date: str,
    qr_token: str
):
    # 1. Email to Student (Includes QR Code block)
    student_body = f"""
    <h2>Your Outpass Request Has Been Approved</h2>
    <p>Dear {student_name},</p>
    <p>Your outpass request to <strong>{destination}</strong> has received final authorization from the HOD.</p>
    <p>Please present the digital QR code below to the security gate officers during departure and return checking:</p>
    
    <div class="qr-container">
        <img class="qr-code" src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={qr_token}" alt="Outpass QR Code" />
        <div class="qr-token">{qr_token}</div>
    </div>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
            <tr><td class="label">Leaving Date</td><td class="value">{out_date}</td></tr>
            <tr><td class="label">Return Date</td><td class="value">{in_date}</td></tr>
        </table>
    </div>
    <p>Kindly ensure you check-in before the designated return deadline to avoid automatic escalation warnings.</p>
    """
    student_html = get_base_html_template("accent-student", student_body)
    await send_smtp_email([student_email], f"APPROVED: Outpass Digital Pass - {student_name}", student_html)

    # 2. Email to Parent (Clear Reassurance Notice)
    parent_body = f"""
    <h2>Outpass Approval Notification</h2>
    <p>Dear Parent / Guardian,</p>
    <p>This is to formally notify you that an outpass request for your ward, <strong>{student_name}</strong> (Roll No: {roll_number}), has been approved by the college hostel administration.</p>
    <p>The student is authorized to travel for the following duration:</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
            <tr><td class="label">Planned Departure</td><td class="value">{out_date}</td></tr>
            <tr><td class="label">Expected Return</td><td class="value">{in_date}</td></tr>
        </table>
    </div>
    <p>You will receive automated follow-up notices when the student checks out and returns at the campus security gate.</p>
    """
    parent_html = get_base_html_template("accent-parent", parent_body)
    await send_smtp_email([parent_email], f"Parent Notice: Campus Outpass Authorized - {student_name}", parent_html)

    # 3. Email to Staff (Warden / HOD)
    staff_body = f"""
    <h2>Outpass Approved Log</h2>
    <p>Dear Administrator,</p>
    <p>This is to confirm that outpass registration for <strong>{student_name}</strong> ({roll_number}) has been fully approved by the HOD.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Student Name</td><td class="value">{student_name} ({roll_number})</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
            <tr><td class="label">Validity Range</td><td class="value">{out_date} to {in_date}</td></tr>
            <tr><td class="label">QR Token</td><td class="value">{qr_token}</td></tr>
        </table>
    </div>
    <p>The system has generated the QR code pass and dispatched notification to the student's registered guardian.</p>
    """
    staff_html = get_base_html_template("accent-staff", staff_body)
    await send_smtp_email([hod_email, warden_email], f"Clearance Log: Outpass Approved - {student_name}", staff_html)


async def send_deadline_reminder(
    student_email: str,
    parent_email: str,
    hod_email: str,
    warden_email: str,
    student_name: str,
    roll_number: str,
    destination: str,
    in_date: str
):
    # 1. Email to Student
    student_body = f"""
    <h2>URGENT: Return Deadline Approaching</h2>
    <p>Dear {student_name},</p>
    <p>This is a critical reminder that your outpass return check-in deadline is approaching within the next 24 hours.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Expected Return</td><td class="value" style="color: #dc2626; font-weight: 700;">{in_date}</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
        </table>
    </div>
    <p>You must present your QR code pass and check in at the campus security gate before the time listed above to avoid disciplinary actions.</p>
    """
    student_html = get_base_html_template("accent-alert", student_body)
    await send_smtp_email([student_email], "URGENT REMINDER: Outpass Return Deadline Approaching", student_html)

    # 2. Email to Parent
    parent_body = f"""
    <h2>Security Notice: Ward Return Deadline Reminder</h2>
    <p>Dear Parent / Guardian,</p>
    <p>This is to inform you that your ward, <strong>{student_name}</strong> ({roll_number}), is scheduled to return to the campus hostel within the next 24 hours.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Return Deadline</td><td class="value" style="color: #dc2626; font-weight: 700;">{in_date}</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
        </table>
    </div>
    <p>This is an automated safety alert to keep you informed of your ward's scheduled hostel return timeline.</p>
    """
    parent_html = get_base_html_template("accent-alert", parent_body)
    await send_smtp_email([parent_email], f"Safety Alert: Return Deadline Approaching - {student_name}", parent_html)

    # 3. Email to Staff
    staff_body = f"""
    <h2>Deadline Warning: Overdue / Return Pending</h2>
    <p>Dear Administrator,</p>
    <p>The student <strong>{student_name}</strong> ({roll_number}) is nearing their outpass return deadline.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Student Name</td><td class="value">{student_name} ({roll_number})</td></tr>
            <tr><td class="label">Return Deadline</td><td class="value" style="color: #dc2626; font-weight: 700;">{in_date}</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
        </table>
    </div>
    <p>If the student fails to check in at the security desk before the deadline, they will be flagged in the registry logs.</p>
    """
    staff_html = get_base_html_template("accent-alert", staff_body)
    await send_smtp_email([hod_email, warden_email], f"Deadline Alert: Pending Check-in - {student_name}", staff_html)


async def send_submission_notification(
    student_email: str,
    advisor_email: str,
    student_name: str,
    roll_number: str,
    destination: str,
    out_date: str,
    in_date: str
):
    # 1. Email to Student
    student_body = f"""
    <h2>Outpass Request Submitted Successfully</h2>
    <p>Dear {student_name},</p>
    <p>Your outpass request to <strong>{destination}</strong> has been successfully registered in the system. It is currently pending review by your Academic Advisor.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
            <tr><td class="label">Planned Departure</td><td class="value">{out_date}</td></tr>
            <tr><td class="label">Expected Return</td><td class="value">{in_date}</td></tr>
        </table>
    </div>
    <p>You will receive email notifications as the request is processed by the hostel staff and HOD.</p>
    """
    student_html = get_base_html_template("accent-student", student_body)
    await send_smtp_email([student_email], "Outpass Request Submitted", student_html)

    # 2. Email to Advisor (Action Required)
    staff_body = f"""
    <h2>ACTION REQUIRED: Pending Outpass Review</h2>
    <p>Dear Academic Advisor,</p>
    <p>A new outpass request has been submitted by student <strong>{student_name}</strong> ({roll_number}) and requires your review.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Student Name</td><td class="value">{student_name} ({roll_number})</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
            <tr><td class="label">Planned Out Date</td><td class="value">{out_date}</td></tr>
            <tr><td class="label">Planned In Date</td><td class="value">{in_date}</td></tr>
        </table>
    </div>
    <p>Please log in to your H.O.M.S Approver Workspace to approve or reject this request.</p>
    """
    staff_html = get_base_html_template("accent-staff", staff_body)
    await send_smtp_email([advisor_email], f"ACTION REQUIRED: Pending Outpass - {student_name}", staff_html)


async def send_rejection_notification(
    student_email: str,
    student_name: str,
    roll_number: str,
    destination: str,
    rejected_by_role: str,
    rejection_reason: str
):
    # Email to Student
    student_body = f"""
    <h2>Outpass Request Rejected</h2>
    <p>Dear {student_name},</p>
    <p>We regret to inform you that your outpass request to <strong>{destination}</strong> has been rejected during the clearance process.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Rejected By</td><td class="value" style="text-transform: uppercase; font-weight: 700; color: #dc2626;">{rejected_by_role}</td></tr>
            <tr><td class="label">Reason for Rejection</td><td class="value" style="font-style: italic;">"{rejection_reason}"</td></tr>
        </table>
    </div>
    <p>Please review the comments above, make necessary adjustments, and resubmit a new request if needed.</p>
    """
    student_html = get_base_html_template("accent-alert", student_body)
    await send_smtp_email([student_email], "Outpass Request Rejected", student_html)


async def send_gate_movement_notification(
    student_email: str,
    parent_email: str,
    student_name: str,
    roll_number: str,
    destination: str,
    direction: str,  # "OUT" or "IN"
    timestamp: str
):
    direction_action = "Departed (Checked Out)" if direction == "OUT" else "Returned (Checked In)"
    status_color = "#dc2626" if direction == "OUT" else "#16a34a"

    # 1. Email to Student
    student_body = f"""
    <h2>Gate Security Scan Notification</h2>
    <p>Dear {student_name},</p>
    <p>Your outpass QR code scan has been successfully recorded at the campus security gate.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Movement</td><td class="value" style="color: {status_color}; font-weight: 700;">{direction_action}</td></tr>
            <tr><td class="label">Gate Scan Time</td><td class="value">{timestamp}</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
        </table>
    </div>
    """
    student_html = get_base_html_template("accent-student", student_body)
    await send_smtp_email([student_email], f"Gate Scan Record: {direction_action} - {student_name}", student_html)

    # 2. Email to Parent
    parent_body = f"""
    <h2>Parent Security Alert: Campus Movement Notice</h2>
    <p>Dear Parent / Guardian,</p>
    <p>This is to formally confirm that your ward, <strong>{student_name}</strong> ({roll_number}), has officially checked at the campus security gate.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Ward Name</td><td class="value">{student_name}</td></tr>
            <tr><td class="label">Movement Logged</td><td class="value" style="color: {status_color}; font-weight: 700;">{direction_action}</td></tr>
            <tr><td class="label">Exact Gate Time</td><td class="value">{timestamp}</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
        </table>
    </div>
    <p>This notification is generated automatically by security logs for safety compliance.</p>
    """
    parent_html = get_base_html_template("accent-parent", parent_body)
    await send_smtp_email([parent_email], f"Safety Alert: Gate Check-in/out Notice - {student_name}", parent_html)


async def send_intermediate_approval_notification(
    next_approver_email: str,
    next_approver_role: str,
    student_name: str,
    roll_number: str,
    destination: str,
    out_date: str,
    in_date: str
):
    # Email to Staff
    staff_body = f"""
    <h2>ACTION REQUIRED: Pending Outpass Approval</h2>
    <p>Dear {next_approver_role.upper()},</p>
    <p>An outpass request for student <strong>{student_name}</strong> ({roll_number}) is awaiting your clearance step.</p>
    
    <div class="highlight-box">
        <table class="table-details">
            <tr><td class="label">Student Name</td><td class="value">{student_name} ({roll_number})</td></tr>
            <tr><td class="label">Destination</td><td class="value">{destination}</td></tr>
            <tr><td class="label">Departure Date</td><td class="value">{out_date}</td></tr>
            <tr><td class="label">Return Date</td><td class="value">{in_date}</td></tr>
        </table>
    </div>
    <p>Please log in to your H.O.M.S Approver Workspace to review and authorize this request.</p>
    """
    staff_html = get_base_html_template("accent-staff", staff_body)
    await send_smtp_email([next_approver_email], f"ACTION REQUIRED: Pending Clearance Review - {student_name}", staff_html)
