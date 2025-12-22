import os
from datetime import datetime, timedelta
from flask import current_app, url_for
from werkzeug.utils import secure_filename
from flask_mail import Message
from threading import Thread

# ============================================================
# FILE UPLOAD HELPERS
# ============================================================

def allowed_file(filename):
    """
    Check if uploaded file has an allowed extension.
    
    Args:
        filename (str): Name of the file to check
        
    Returns:
        bool: True if extension is allowed, False otherwise
    """
    if not filename or "." not in filename:
        return False
    
    ext = filename.rsplit(".", 1)[1].lower()
    allowed_extensions = current_app.config.get(
        "ALLOWED_EXTENSIONS", 
        ["png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "txt", "zip"]
    )
    return ext in allowed_extensions


def save_attachment(file_storage):
    """
    Save uploaded file to the upload folder with timestamp prefix.
    
    Args:
        file_storage: FileStorage object from Flask request
        
    Returns:
        str: Saved filename, or None if save failed
    """
    if not file_storage or not hasattr(file_storage, 'filename') or file_storage.filename == "":
        return None

    if not allowed_file(file_storage.filename):
        current_app.logger.warning(f"File upload rejected: {file_storage.filename} (invalid extension)")
        return None

    try:
        # Secure the filename
        filename = secure_filename(file_storage.filename)
        
        # Ensure upload folder exists
        folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
        os.makedirs(folder, exist_ok=True)

        # Add timestamp to avoid collisions
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{filename}"
        
        # Save file
        path = os.path.join(folder, filename)
        file_storage.save(path)
        
        current_app.logger.info(f"File saved: {filename}")
        return filename
        
    except Exception as e:
        current_app.logger.error(f"Error saving file: {e}")
        return None


def get_file_size(filename):
    """
    Get size of uploaded file in bytes.
    
    Args:
        filename (str): Name of the file
        
    Returns:
        int: File size in bytes, or None if file doesn't exist
    """
    try:
        folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            return os.path.getsize(path)
    except Exception as e:
        current_app.logger.error(f"Error getting file size: {e}")
    return None


# ============================================================
# SLA HELPERS
# ============================================================

def compute_due_date(hours):
    """
    Compute due date for SLA based on hours from now.
    
    Args:
        hours (int): Number of hours until deadline
        
    Returns:
        datetime: Due date timestamp
    """
    return datetime.utcnow() + timedelta(hours=hours)


def sla_class(ticket):
    """
    Return CSS class for SLA status visualization.
    
    Args:
        ticket: Ticket object with sla_state property
        
    Returns:
        str: CSS class name for styling
    """
    sla_state = getattr(ticket, "sla_state", "Met")
    
    return {
        "Met": "sla-met sla-green",
        "At Risk": "sla-at-risk sla-yellow",
        "Breached": "sla-breached sla-red",
    }.get(sla_state, "sla-met sla-green")


def calculate_sla_compliance_rate(tickets):
    """
    Calculate SLA compliance rate for a list of tickets.
    
    Args:
        tickets: List of ticket objects
        
    Returns:
        float: Compliance rate as percentage (0-100)
    """
    if not tickets:
        return 100.0
    
    closed_tickets = [t for t in tickets if t.status in ("Closed", "Resolved")]
    if not closed_tickets:
        return 100.0
    
    met_sla = sum(1 for t in closed_tickets if t.sla_state == "Met")
    return (met_sla / len(closed_tickets)) * 100


# ============================================================
# INTERNAL: EMAIL LOGGING
# ============================================================

def _log_email(to_email, subject, html_body, status="SUCCESS", ticket_id=None, extra_error=None):
    """
    Write email log entry to database. Fails silently on error.
    
    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        html_body (str): Email HTML body
        status (str): Email status (SUCCESS/FAILED/PENDING)
        ticket_id (int, optional): Related ticket ID
        extra_error (str, optional): Error message if failed
    """
    try:
        from models import EmailLog, db

        # Create preview from body (first 480 chars)
        preview_source = html_body or ""
        preview = (preview_source[:480] + "…") if len(preview_source) > 480 else preview_source

        log = EmailLog(
            to_email=to_email,
            from_email=current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@portal.com"),
            subject=subject,
            body_preview=preview,
            status=status,
            ticket_id=ticket_id,
            error_message=extra_error,
        )
        db.session.add(log)
        db.session.commit()
        
        current_app.logger.info(f"Email logged: {to_email} - {status}")

    except Exception as e:
        current_app.logger.error(f"[EMAILLOG ERROR] {e}")
        print(f"[EMAILLOG ERROR] {e}")


# ============================================================
# EMAIL CORE
# ============================================================

def send_async_email(app, msg, ticket_id=None):
    """
    Send email asynchronously in background thread.
    
    Args:
        app: Flask application instance
        msg: Flask-Mail Message object
        ticket_id (int, optional): Related ticket ID for logging
    """
    with app.app_context():
        mail = current_app.extensions.get("mail")
        
        if not mail:
            error_msg = "Flask-Mail not initialized"
            current_app.logger.error(f"[MAIL ERROR] {error_msg}")
            _log_email(
                to_email=",".join(msg.recipients),
                subject=msg.subject,
                html_body=msg.html or msg.body,
                status="FAILED",
                ticket_id=ticket_id,
                extra_error=error_msg,
            )
            return

        error_text = None
        status = "SUCCESS"

        try:
            mail.send(msg)
            current_app.logger.info(f"[EMAIL SENT] -> {msg.recipients}")
            print(f"[EMAIL SENT] -> {msg.recipients}")
        except Exception as e:
            status = "FAILED"
            error_text = str(e)
            current_app.logger.error(f"[EMAIL ERROR] {e}")
            print(f"[EMAIL ERROR] {e}")

        # Log the email attempt
        _log_email(
            to_email=",".join(msg.recipients),
            subject=msg.subject,
            html_body=msg.html or msg.body,
            status=status,
            ticket_id=ticket_id,
            extra_error=error_text,
        )


def send_email(to, subject, html_body, text_body=None, attachments=None, ticket_id=None):
    """
    Send email with optional attachments. Executes asynchronously.
    
    Args:
        to (str): Recipient email address
        subject (str): Email subject
        html_body (str): HTML version of email body
        text_body (str, optional): Plain text version of email body
        attachments (list, optional): List of file paths to attach
        ticket_id (int, optional): Related ticket ID for logging
        
    Returns:
        bool: True if email was queued successfully, False otherwise
    """
    try:
        app = current_app._get_current_object()
        mail = current_app.extensions.get("mail")

        if not mail:
            error_msg = "Flask-Mail not initialized"
            current_app.logger.error(f"[MAIL ERROR] {error_msg}")
            _log_email(
                to_email=to,
                subject=subject,
                html_body=html_body or text_body,
                status="FAILED",
                ticket_id=ticket_id,
                extra_error=error_msg,
            )
            return False

        # Create message
        msg = Message(
            subject=subject,
            recipients=[to],
            sender=current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@portal.com"),
        )

        msg.body = text_body or "Your email client does not support HTML."
        msg.html = html_body

        # Attach files if provided
        if attachments:
            for file_path in attachments:
                try:
                    with app.open_resource(file_path) as fp:
                        msg.attach(
                            os.path.basename(file_path),
                            "application/octet-stream",
                            fp.read(),
                        )
                except Exception as e:
                    current_app.logger.error(f"[ATTACHMENT ERROR] {e}")
                    print(f"[ATTACHMENT ERROR] {e}")

        # Send asynchronously
        Thread(target=send_async_email, args=(app, msg, ticket_id)).start()
        return True
        
    except Exception as e:
        current_app.logger.error(f"Error preparing email: {e}")
        return False


# ============================================================
# EMAIL HTML TEMPLATE WRAPPER
# ============================================================

def _email_shell(title, intro_html, content_html, footer_html="", ticket_url=None):
    """
    Generate HTML email template with consistent branding.
    
    Args:
        title (str): Email title/heading
        intro_html (str): Introduction paragraph HTML
        content_html (str): Main content HTML
        footer_html (str, optional): Footer text
        ticket_url (str, optional): URL to view ticket
        
    Returns:
        str: Complete HTML email
    """
    footer = footer_html or "This is an automated notification from IT Ticketing Portal."
    
    action_button = ""
    if ticket_url:
        action_button = f"""
        <tr>
            <td style="padding:0 24px 18px 24px;" align="center">
                <a href="{ticket_url}" style="display:inline-block;padding:12px 32px;background:#0a4b78;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px;">
                    View Ticket
                </a>
            </td>
        </tr>
        """
    
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellspacing="0" cellpadding="0" style="padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 10px 30px rgba(15,23,42,0.18);">
          
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg, #0a4b78, #0d5a91);color:#ffffff;padding:24px;text-align:center;">
              <h1 style="margin:0;font-size:24px;font-weight:700;">IT Ticketing Portal</h1>
            </td>
          </tr>
          
          <!-- Title -->
          <tr>
            <td style="padding:24px 24px 12px 24px;">
              <h2 style="margin:0;font-size:20px;color:#0f172a;font-weight:700;">{title}</h2>
            </td>
          </tr>
          
          <!-- Intro -->
          <tr>
            <td style="padding:0 24px 16px 24px;">
              <p style="margin:0;font-size:14px;color:#4b5563;line-height:1.6;">{intro_html}</p>
            </td>
          </tr>
          
          <!-- Content -->
          <tr>
            <td style="padding:0 24px 24px 24px;font-size:14px;color:#111827;line-height:1.6;">
              {content_html}
            </td>
          </tr>
          
          <!-- Action Button -->
          {action_button}
          
          <!-- Footer -->
          <tr>
            <td style="padding:16px 24px;font-size:12px;color:#6b7280;border-top:1px solid #e5e7eb;background:#f9fafb;">
              <p style="margin:0 0 8px 0;">{footer}</p>
              <p style="margin:0;color:#9ca3af;">
                © {datetime.utcnow().year} IT Ticketing Portal. All rights reserved.
              </p>
            </td>
          </tr>
          
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


# ============================================================
# SPECIFIC EMAIL NOTIFICATIONS
# ============================================================

def email_ticket_created(user, ticket):
    """
    Send email notification when a new ticket is created.
    
    Args:
        user: User object who created the ticket
        ticket: Ticket object that was created
    """
    subject = f"New Ticket Created - {ticket.ticket_no}"

    intro = "Your support ticket has been created successfully and assigned a tracking number."
    
    details = f"""
    <div style="background:#f9fafb;padding:16px;border-radius:8px;margin:16px 0;">
        <table cellpadding="8" cellspacing="0" style="width:100%;font-size:14px;">
          <tr>
            <td style="color:#6b7280;width:140px;"><strong>Ticket No:</strong></td>
            <td style="color:#0f172a;"><strong>{ticket.ticket_no}</strong></td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Type:</strong></td>
            <td style="color:#0f172a;">{ticket.ticket_type}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Priority:</strong></td>
            <td style="color:#0f172a;">{ticket.priority}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Category:</strong></td>
            <td style="color:#0f172a;">{ticket.category}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;vertical-align:top;"><strong>Description:</strong></td>
            <td style="color:#0f172a;">{ticket.description[:200]}{'...' if len(ticket.description) > 200 else ''}</td>
          </tr>
        </table>
    </div>
    <p style="margin:16px 0 0 0;color:#6b7280;">
        <strong>Next Steps:</strong> Our IT team will review your ticket and respond as soon as possible.
    </p>
    """

    # Generate ticket URL (if possible)
    ticket_url = None
    try:
        with current_app.test_request_context():
            ticket_url = url_for('ticket_view', ticket_id=ticket.id, _external=True)
    except Exception:
        pass

    html = _email_shell(subject, intro, details, ticket_url=ticket_url)
    
    text = f"""
New Ticket Created

Your support ticket has been created successfully.

Ticket No: {ticket.ticket_no}
Type: {ticket.ticket_type}
Priority: {ticket.priority}
Category: {ticket.category}
Description: {ticket.description}

Our IT team will review your ticket and respond as soon as possible.
"""

    # Send to ticket creator
    if user and user.email:
        send_email(user.email, subject, html, text, ticket_id=ticket.id)

    # Optionally notify admin
    admin_email = current_app.config.get("ADMIN_EMAIL")
    if admin_email and admin_email != user.email:
        send_email(admin_email, subject, html, text, ticket_id=ticket.id)


def email_ticket_updated(user, ticket, updated_by, update_text):
    """
    Send email notification when a ticket is updated.
    
    Args:
        user: User object who owns the ticket
        ticket: Ticket object that was updated
        updated_by (str): Name of person who updated the ticket
        update_text (str): Description of what was updated
    """
    if not user or not user.email:
        return

    subject = f"Ticket Updated - {ticket.ticket_no}"
    intro = f"Your ticket was updated by <strong>{updated_by}</strong>."
    
    content = f"""
    <div style="background:#eff6ff;padding:14px;border-radius:8px;border-left:4px solid #3b82f6;margin:16px 0;">
        <p style="margin:0;color:#1e40af;font-weight:600;">Update:</p>
        <p style="margin:8px 0 0 0;color:#1e3a8a;">{update_text}</p>
    </div>

    <div style="background:#f9fafb;padding:16px;border-radius:8px;margin:16px 0;">
        <table cellpadding="8" cellspacing="0" style="width:100%;font-size:14px;">
          <tr>
            <td style="color:#6b7280;width:140px;"><strong>Ticket No:</strong></td>
            <td style="color:#0f172a;">{ticket.ticket_no}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Current Status:</strong></td>
            <td style="color:#0f172a;">{ticket.status}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Priority:</strong></td>
            <td style="color:#0f172a;">{ticket.priority}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Assigned To:</strong></td>
            <td style="color:#0f172a;">{ticket.assignee.name if ticket.assignee else (ticket.assignee_name if hasattr(ticket, 'assignee_name') and ticket.assignee_name else 'Unassigned')}</td>
          </tr>
        </table>
    </div>
    """

    # Generate ticket URL
    ticket_url = None
    try:
        with current_app.test_request_context():
            ticket_url = url_for('ticket_view', ticket_id=ticket.id, _external=True)
    except Exception:
        pass

    html = _email_shell(subject, intro, content, ticket_url=ticket_url)
    
    text = f"""
Ticket Updated

Your ticket was updated by {updated_by}.

Update: {update_text}

Ticket No: {ticket.ticket_no}
Status: {ticket.status}
Priority: {ticket.priority}
Assigned To: {ticket.assignee.name if ticket.assignee else 'Unassigned'}
"""

    send_email(user.email, subject, html, text, ticket_id=ticket.id)


def email_assignee_assigned(assignee, ticket, assigned_by):
    """
    Send email notification when a ticket is assigned to an engineer.
    
    Args:
        assignee: User object who is assigned the ticket
        ticket: Ticket object that was assigned
        assigned_by (str): Name of person who made the assignment
    """
    if not assignee or not assignee.email:
        return

    subject = f"New Ticket Assigned - {ticket.ticket_no}"
    intro = f"You have been assigned a new support ticket by <strong>{assigned_by}</strong>."
    
    content = f"""
    <div style="background:#f9fafb;padding:16px;border-radius:8px;margin:16px 0;">
        <table cellpadding="8" cellspacing="0" style="width:100%;font-size:14px;">
          <tr>
            <td style="color:#6b7280;width:140px;"><strong>Ticket No:</strong></td>
            <td style="color:#0f172a;"><strong>{ticket.ticket_no}</strong></td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Priority:</strong></td>
            <td style="color:#0f172a;">{ticket.priority}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Type:</strong></td>
            <td style="color:#0f172a;">{ticket.ticket_type}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Category:</strong></td>
            <td style="color:#0f172a;">{ticket.category}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;vertical-align:top;"><strong>Description:</strong></td>
            <td style="color:#0f172a;">{ticket.description[:200]}{'...' if len(ticket.description) > 200 else ''}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>Created By:</strong></td>
            <td style="color:#0f172a;">{ticket.user.name if ticket.user else 'Unknown'}</td>
          </tr>
        </table>
    </div>
    <p style="margin:16px 0 0 0;color:#6b7280;">
        <strong>Action Required:</strong> Please review and begin working on this ticket.
    </p>
    """

    # Generate ticket URL
    ticket_url = None
    try:
        with current_app.test_request_context():
            ticket_url = url_for('admin_ticket_view', id=ticket.id, _external=True)
    except Exception:
        pass

    html = _email_shell(subject, intro, content, ticket_url=ticket_url)
    
    text = f"""
New Ticket Assigned

You have been assigned a new support ticket by {assigned_by}.

Ticket No: {ticket.ticket_no}
Priority: {ticket.priority}
Type: {ticket.ticket_type}
Category: {ticket.category}
Description: {ticket.description}
Created By: {ticket.user.name if ticket.user else 'Unknown'}

Please review and begin working on this ticket.
"""

    send_email(assignee.email, subject, html, text, ticket_id=ticket.id)


def email_daily_sla_report(admin_email, metrics, breached_tickets):
    """
    Send daily SLA compliance report to administrators.
    
    Args:
        admin_email (str): Administrator email address
        metrics (dict): Dictionary with report metrics
        breached_tickets (list): List of breached ticket summaries
    """
    subject = f"Daily SLA Report - {metrics.get('timestamp', 'N/A')}"
    intro = "Here is your daily SLA compliance report."
    
    # Build breached tickets table
    breached_html = ""
    if breached_tickets:
        rows = "".join([
            f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{t['ticket_no']}</td>
                <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{t['priority']}</td>
                <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{t['status']}</td>
                <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{t['user']}</td>
                <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{t['age_hours']}h</td>
            </tr>
            """
            for t in breached_tickets
        ])
        
        breached_html = f"""
        <h3 style="color:#0f172a;font-size:16px;margin:24px 0 12px 0;">Breached Tickets ({len(breached_tickets)})</h3>
        <table cellpadding="0" cellspacing="0" style="width:100%;font-size:13px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
            <tr style="background:#f9fafb;">
                <th style="padding:10px 8px;text-align:left;font-weight:600;">Ticket</th>
                <th style="padding:10px 8px;text-align:left;font-weight:600;">Priority</th>
                <th style="padding:10px 8px;text-align:left;font-weight:600;">Status</th>
                <th style="padding:10px 8px;text-align:left;font-weight:600;">User</th>
                <th style="padding:10px 8px;text-align:left;font-weight:600;">Age</th>
            </tr>
            {rows}
        </table>
        """
    
    content = f"""
    <div style="background:#f9fafb;padding:16px;border-radius:8px;margin:16px 0;">
        <h3 style="color:#0f172a;font-size:16px;margin:0 0 16px 0;">Summary</h3>
        <table cellpadding="8" cellspacing="0" style="width:100%;font-size:14px;">
          <tr>
            <td style="color:#6b7280;width:200px;"><strong>Total Open Tickets:</strong></td>
            <td style="color:#0f172a;">{metrics.get('total_open', 0)}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>SLA Breached:</strong></td>
            <td style="color:#ef4444;font-weight:600;">{metrics.get('breached', 0)}</td>
          </tr>
          <tr>
            <td style="color:#6b7280;"><strong>At Risk (&lt; 6h):</strong></td>
            <td style="color:#f59e0b;font-weight:600;">{metrics.get('at_risk', 0)}</td>
          </tr>
        </table>
    </div>
    
    {breached_html}
    """

    html = _email_shell(subject, intro, content)
    
    text = f"""
Daily SLA Report

Timestamp: {metrics.get('timestamp', 'N/A')}

Summary:
- Total Open Tickets: {metrics.get('total_open', 0)}
- SLA Breached: {metrics.get('breached', 0)}
- At Risk: {metrics.get('at_risk', 0)}

Breached Tickets: {len(breached_tickets)}
"""

    send_email(admin_email, subject, html, text)


# ============================================================
# ADDITIONAL UTILITY FUNCTIONS
# ============================================================

def format_datetime(dt, format_str="%Y-%m-%d %H:%M:%S"):
    """
    Format datetime object to string.
    
    Args:
        dt (datetime): Datetime object to format
        format_str (str): Format string
        
    Returns:
        str: Formatted datetime string
    """
    if not dt:
        return "N/A"
    return dt.strftime(format_str)


def get_time_ago(dt):
    """
    Get human-readable time difference from now.
    
    Args:
        dt (datetime): Past datetime object
        
    Returns:
        str: Human-readable time difference
    """
    if not dt:
        return "N/A"
    
    delta = datetime.utcnow() - dt
    seconds = delta.total_seconds()
    
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    elif seconds < 604800:
        return f"{int(seconds // 86400)}d ago"
    else:
        return f"{int(seconds // 604800)}w ago"


def truncate_text(text, length=100):
    """
    Truncate text to specified length with ellipsis.
    
    Args:
        text (str): Text to truncate
        length (int): Maximum length
        
    Returns:
        str: Truncated text
    """
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length] + "..."


def paginate_query(query, page=1, per_page=20):
    """
    Paginate a SQLAlchemy query.
    
    Args:
        query: SQLAlchemy query object
        page (int): Page number (1-indexed)
        per_page (int): Items per page
        
    Returns:
        tuple: (items, total_count, total_pages)
    """
    total = query.count()
    pages = (total + per_page - 1) // per_page
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return items, total, pages