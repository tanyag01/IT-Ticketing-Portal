import os
import logging
from datetime import datetime, timedelta
from celery import Celery, Task
from flask import current_app
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery = Celery("it_portal", broker=REDIS_URL, backend=REDIS_URL)

# Celery configuration
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
)


# ============================================================
# FLASK APP CONTEXT HELPER
# ============================================================
class FlaskTask(Task):
    """
    Custom Celery Task class that provides Flask app context.
    Ensures tasks can access Flask config and database.
    """
    def __call__(self, *args, **kwargs):
        from app import create_app
        app = create_app()
        with app.app_context():
            return self.run(*args, **kwargs)


celery.Task = FlaskTask


# ============================================================
# PERIODIC TASK SCHEDULE
# ============================================================
@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    Configure periodic (scheduled) tasks.
    Runs at Celery beat startup.
    """
    # Check SLA breaches every hour
    sender.add_periodic_task(
        3600.0,
        check_sla.s(),
        name="Check SLA breaches (hourly)"
    )
    
    # Send daily SLA report (9 AM UTC by default)
    sender.add_periodic_task(
        86400.0,
        daily_sla_report.s(),
        name="Daily SLA report"
    )
    
    # Send reminder emails for tickets expiring soon (every 4 hours)
    sender.add_periodic_task(
        14400.0,
        send_sla_reminders.s(),
        name="SLA reminder notifications (every 4h)"
    )
    
    # Clean up old email logs (daily)
    sender.add_periodic_task(
        86400.0,
        cleanup_old_email_logs.s(),
        name="Clean up old email logs (daily)"
    )

    logger.info("✓ Periodic tasks configured")


# ============================================================
# SLA MONITORING TASKS
# ============================================================
@celery.task(bind=True)
def check_sla(self):
    """
    Check for SLA breaches and notify relevant parties.
    Runs hourly to identify tickets that have breached their SLA.
    
    Returns:
        dict: Summary of breached tickets
    """
    try:
        from models import db, Ticket, User, TicketHistory
        from utils import send_email, sla_class

        logger.info("[TASK] check_sla: Starting SLA breach check")
        
        # Get all open tickets
        open_tickets = Ticket.query.filter(
            Ticket.status.in_(["Open", "In Progress", "Pending"])
        ).all()
        
        breached_count = 0
        notified_count = 0
        
        for ticket in open_tickets:
            # Check if SLA is breached
            if ticket.sla_state == "Breached":
                breached_count += 1
                
                # Check if already notified (via history)
                last_breach_notify = TicketHistory.query.filter(
                    TicketHistory.ticket_id == ticket.id,
                    TicketHistory.event_type == "sla_breach_notified"
                ).order_by(TicketHistory.created_at.desc()).first()
                
                # Only notify once per breach (not repeatedly)
                if not last_breach_notify:
                    recipient_emails = []
                    
                    # Notify assignee
                    if ticket.assignee and ticket.assignee.email:
                        recipient_emails.append(ticket.assignee.email)
                    
                    # Notify ticket creator
                    if ticket.user and ticket.user.email:
                        recipient_emails.append(ticket.user.email)
                    
                    # Notify admins
                    admins = User.query.filter_by(role="admin", active=True).all()
                    admin_emails = [a.email for a in admins if a.email]
                    recipient_emails.extend(admin_emails)
                    
                    # Remove duplicates
                    recipient_emails = list(set(recipient_emails))
                    
                    if recipient_emails:
                        try:
                            subject = f"🚨 URGENT: SLA Breached - {ticket.ticket_no}"
                            
                            html_body = f"""
                            <div style="color: #dc2626; font-weight: bold; margin: 16px 0;">
                                SLA BREACH ALERT
                            </div>
                            <p><strong>Ticket:</strong> {ticket.ticket_no}</p>
                            <p><strong>Priority:</strong> {ticket.priority}</p>
                            <p><strong>Status:</strong> {ticket.status}</p>
                            <p><strong>Overdue:</strong> {ticket.sla_countdown_human}</p>
                            <p><strong>Created:</strong> {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
                            <p><strong>Assigned To:</strong> {ticket.assignee.name if ticket.assignee else 'Unassigned'}</p>
                            <p style="margin-top: 16px; color: #666;">
                                Please take immediate action to resolve this ticket.
                            </p>
                            """
                            
                            text_body = f"""
URGENT: SLA BREACH ALERT

Ticket: {ticket.ticket_no}
Priority: {ticket.priority}
Status: {ticket.status}
Overdue: {ticket.sla_countdown_human}
Created: {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')}
Assigned To: {ticket.assignee.name if ticket.assignee else 'Unassigned'}

Please take immediate action to resolve this ticket.
                            """
                            
                            send_email(
                                to=", ".join(recipient_emails),
                                subject=subject,
                                html_body=html_body,
                                text_body=text_body,
                                ticket_id=ticket.id
                            )
                            
                            notified_count += 1
                            
                            # Record notification in history
                            history = TicketHistory(
                                ticket_id=ticket.id,
                                event="SLA breach notification sent",
                                event_type="sla_breach_notified",
                                user_id=None
                            )
                            db.session.add(history)
                            db.session.commit()
                            
                        except Exception as e:
                            logger.error(f"Error sending SLA breach email for ticket {ticket.ticket_no}: {e}")
        
        result = {
            "breached_count": breached_count,
            "notified_count": notified_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"[TASK] check_sla: Complete - {result}")
        return result
        
    except Exception as e:
        logger.error(f"[TASK] check_sla: Error - {e}", exc_info=True)
        self.retry(exc=e, countdown=60, max_retries=3)


@celery.task(bind=True)
def send_sla_reminders(self):
    """
    Send reminder notifications for tickets approaching SLA deadline.
    Runs every 4 hours.
    Only reminds once per ticket to avoid spam.
    
    Returns:
        dict: Summary of reminders sent
    """
    try:
        from models import db, Ticket, TicketHistory
        from utils import send_email

        logger.info("[TASK] send_sla_reminders: Starting reminder check")
        
        # Get all open tickets
        open_tickets = Ticket.query.filter(
            Ticket.status.in_(["Open", "In Progress", "Pending"])
        ).all()
        
        reminders_sent = 0
        
        for ticket in open_tickets:
            if not ticket.due_date:
                continue
            
            secs_left = ticket.sla_seconds_left
            
            if secs_left is None:
                continue
            
            # Remind if at risk (< 6 hours) and positive (not breached)
            if 0 < secs_left <= 6 * 3600:
                # Check if already reminded in last 4 hours
                four_hours_ago = datetime.utcnow() - timedelta(hours=4)
                recent_reminder = TicketHistory.query.filter(
                    TicketHistory.ticket_id == ticket.id,
                    TicketHistory.event_type == "sla_reminder_sent",
                    TicketHistory.created_at >= four_hours_ago
                ).first()
                
                if not recent_reminder and ticket.assignee and ticket.assignee.email:
                    try:
                        hours_left = int(secs_left // 3600)
                        minutes_left = int((secs_left % 3600) // 60)
                        
                        subject = f"⏰ Reminder: {ticket.ticket_no} due in {hours_left}h {minutes_left}m"
                        
                        html_body = f"""
                        <p><strong>Ticket:</strong> {ticket.ticket_no}</p>
                        <p><strong>Priority:</strong> {ticket.priority}</p>
                        <p><strong>Time Remaining:</strong> <span style="color: #f59e0b; font-weight: bold;">{hours_left}h {minutes_left}m</span></p>
                        <p style="margin-top: 16px; color: #666;">
                            Please complete or update this ticket before the SLA deadline.
                        </p>
                        """
                        
                        text_body = f"""
Reminder: Ticket {ticket.ticket_no} due in {hours_left}h {minutes_left}m

Priority: {ticket.priority}

Please complete or update this ticket before the SLA deadline.
                        """
                        
                        send_email(
                            to=ticket.assignee.email,
                            subject=subject,
                            html_body=html_body,
                            text_body=text_body,
                            ticket_id=ticket.id
                        )
                        
                        reminders_sent += 1
                        
                        # Record reminder in history
                        history = TicketHistory(
                            ticket_id=ticket.id,
                            event=f"SLA reminder sent ({hours_left}h remaining)",
                            event_type="sla_reminder_sent",
                            user_id=None
                        )
                        db.session.add(history)
                        db.session.commit()
                        
                    except Exception as e:
                        logger.error(f"Error sending reminder for ticket {ticket.ticket_no}: {e}")
        
        result = {
            "reminders_sent": reminders_sent,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"[TASK] send_sla_reminders: Complete - {result}")
        return result
        
    except Exception as e:
        logger.error(f"[TASK] send_sla_reminders: Error - {e}", exc_info=True)
        self.retry(exc=e, countdown=60, max_retries=3)


# ============================================================
# REPORTING TASKS
# ============================================================
@celery.task(bind=True)
def daily_sla_report(self):
    """
    Send daily SLA compliance report to administrators.
    Includes summary metrics and list of breached tickets.
    
    Returns:
        dict: Report summary
    """
    try:
        from models import db, Ticket, User
        from utils import send_email, email_daily_sla_report

        logger.info("[TASK] daily_sla_report: Starting report generation")
        
        admin_users = User.query.filter_by(role="admin", active=True).all()
        admin_emails = [a.email for a in admin_users if a.email]
        
        if not admin_emails:
            logger.warning("[TASK] daily_sla_report: No admin emails found")
            return {"status": "skipped", "reason": "No admin emails"}
        
        # Get all open tickets
        open_tickets = Ticket.query.filter(
            Ticket.status.in_(["Open", "In Progress", "Pending"])
        ).all()
        
        # Calculate metrics
        breached = [t for t in open_tickets if t.sla_state == "Breached"]
        at_risk = [t for t in open_tickets if t.sla_state == "At Risk"]
        
        metrics = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "total_open": len(open_tickets),
            "breached": len(breached),
            "at_risk": len(at_risk),
            "on_track": len(open_tickets) - len(breached) - len(at_risk)
        }
        
        # Format breached tickets for report
        breached_summaries = [
            {
                "ticket_no": t.ticket_no,
                "priority": t.priority,
                "status": t.status,
                "user": t.user.name if t.user else "Unknown",
                "age_hours": int((datetime.utcnow() - t.created_at).total_seconds() / 3600)
            }
            for t in breached[:10]  # Top 10 most recent breaches
        ]
        
        # Send to each admin
        for admin_email in admin_emails:
            try:
                email_daily_sla_report(admin_email, metrics, breached_summaries)
            except Exception as e:
                logger.error(f"Error sending report to {admin_email}: {e}")
        
        result = {
            "status": "sent",
            "admin_count": len(admin_emails),
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"[TASK] daily_sla_report: Complete - {result}")
        return result
        
    except Exception as e:
        logger.error(f"[TASK] daily_sla_report: Error - {e}", exc_info=True)
        self.retry(exc=e, countdown=60, max_retries=3)


# ============================================================
# MAINTENANCE TASKS
# ============================================================
@celery.task(bind=True)
def cleanup_old_email_logs(self):
    """
    Clean up old email logs to save database space.
    Deletes logs older than 30 days by default.
    
    Returns:
        dict: Cleanup summary
    """
    try:
        from models import db, EmailLog

        logger.info("[TASK] cleanup_old_email_logs: Starting cleanup")
        
        # Delete logs older than 30 days
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        deleted = db.session.query(EmailLog).filter(
            EmailLog.sent_at < cutoff_date
        ).delete()
        
        db.session.commit()
        
        result = {
            "deleted_count": deleted,
            "cutoff_date": cutoff_date.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"[TASK] cleanup_old_email_logs: Complete - {result}")
        return result
        
    except Exception as e:
        logger.error(f"[TASK] cleanup_old_email_logs: Error - {e}", exc_info=True)
        self.retry(exc=e, countdown=60, max_retries=3)


@celery.task(bind=True)
def archive_closed_tickets(self, days=90):
    """
    Archive (mark as archived) tickets closed longer than N days.
    Optional: Can be extended to move to separate table.
    
    Args:
        days (int): Archive tickets closed more than N days ago
        
    Returns:
        dict: Archive summary
    """
    try:
        from models import db, Ticket

        logger.info(f"[TASK] archive_closed_tickets: Starting archive (>{days} days)")
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        archived = db.session.query(Ticket).filter(
            Ticket.status.in_(["Closed", "Resolved"]),
            Ticket.closed_at < cutoff_date
        ).count()
        
        # Future: Add archive column and mark as archived
        # db.session.query(Ticket).filter(...).update({"archived": True})
        
        db.session.commit()
        
        result = {
            "archived_count": archived,
            "cutoff_date": cutoff_date.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"[TASK] archive_closed_tickets: Complete - {result}")
        return result
        
    except Exception as e:
        logger.error(f"[TASK] archive_closed_tickets: Error - {e}", exc_info=True)
        self.retry(exc=e, countdown=60, max_retries=3)


# ============================================================
# ON-DEMAND TASKS
# ============================================================
@celery.task(bind=True)
def send_ticket_notification(self, ticket_id, template_type="created", recipient_email=None):
    """
    Send ticket notification email (on-demand).
    Called when ticket events occur in real-time.
    
    Args:
        ticket_id (int): Ticket ID
        template_type (str): Email template type (created, updated, assigned, etc.)
        recipient_email (str, optional): Override recipient
        
    Returns:
        dict: Task result
    """
    try:
        from models import Ticket
        from utils import (
            email_ticket_created,
            email_ticket_updated,
            email_assignee_assigned
        )

        logger.info(f"[TASK] send_ticket_notification: ticket_id={ticket_id}, type={template_type}")
        
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        if template_type == "created":
            email_ticket_created(ticket.user, ticket)
        elif template_type == "updated":
            email_ticket_updated(ticket.user, ticket, "System", "Ticket updated")
        elif template_type == "assigned":
            email_assignee_assigned(ticket.assignee, ticket, "System")
        
        result = {
            "status": "sent",
            "ticket_id": ticket_id,
            "template_type": template_type,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"[TASK] send_ticket_notification: Complete")
        return result
        
    except Exception as e:
        logger.error(f"[TASK] send_ticket_notification: Error - {e}", exc_info=True)
        self.retry(exc=e, countdown=30, max_retries=2)