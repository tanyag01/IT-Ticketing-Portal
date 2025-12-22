from datetime import datetime, timedelta  
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import event
from sqlalchemy.ext.hybrid import hybrid_property

db = SQLAlchemy()


# ============================================================
#  TICKET STATUS DEFINITIONS
# ============================================================

TICKET_STATUSES = (
    "Not Open Yet",
    "Open",
    "In Progress",
    "Re-Open",
    "Resolved",
    "Closed",
)

STATUS_COLORS = {
    "Not Open Yet": "gray",
    "Open": "blue",
    "In Progress": "orange",
    "Re-Open": "red",
    "Resolved": "green",
    "Closed": "green",
}


# ============================================================
#  USER MODEL
# ============================================================
class User(db.Model, UserMixin):
    """
    User model for authentication and authorization.
    Supports multiple roles: user, admin, assignee, engineer.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)

    # Role-based access control
    role = db.Column(db.String(20), default="user", nullable=False)  # user / admin / assignee / engineer
    department = db.Column(db.String(120), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # User preferences
    theme_pref = db.Column(db.String(10), default="system")  # light / dark / system

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tickets_created = db.relationship(
        "Ticket", 
        foreign_keys="Ticket.user_id", 
        backref="creator", 
        lazy="dynamic"
    )
    tickets_assigned = db.relationship(
        "Ticket", 
        foreign_keys="Ticket.assignee_id", 
        backref="assigned_engineer", 
        lazy="dynamic"
    )

    def set_password(self, password):
        """Hash and set user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify user password."""
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        """Check if user is admin."""
        return self.role == "admin"

    def is_engineer(self):
        """Check if user is engineer or assignee."""
        return self.role in ("admin", "engineer", "assignee")

    def get_assigned_tickets(self, status=None):
        """Get tickets assigned to this user."""
        query = self.tickets_assigned
        if status:
            query = query.filter_by(status=status)
        return query.all()

    def get_created_tickets(self, status=None):
        """Get tickets created by this user."""
        query = self.tickets_created
        if status:
            query = query.filter_by(status=status)
        return query.all()

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


# ============================================================
#  TICKET MODEL
# ============================================================
class Ticket(db.Model):
    """
    Main ticket model for IT support requests.
    Includes SLA tracking, status management, and assignment.
    """
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    ticket_no = db.Column(db.String(30), unique=True, nullable=False, index=True)

    # Ownership
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    user = db.relationship("User", foreign_keys=[user_id], overlaps="creator,tickets_created")

    # Ticket details
    ticket_type = db.Column(db.String(100), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)
    priority = db.Column(db.String(20), nullable=False, index=True, default="Medium")
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Open", nullable=False, index=True)

    # Assignment - supports both User objects and textual assignments
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    assignee = db.relationship("User", foreign_keys=[assignee_id], overlaps="assigned_engineer,tickets_assigned")
    
    # Optional: Store assignee name as text (for custom assignments like "In Queue", "Assigned", or custom names)
    assignee_name = db.Column(db.String(120), nullable=True)
    assign_status = db.Column(db.String(20), nullable=True)  # Unassigned / Engineer / Assigned / In Queue / Custom

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True, index=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # SLA tracking
    sla_hours = db.Column(db.Integer, default=24, nullable=False)

    # Aging (calculated field)
    aging = db.Column(db.Integer, default=0)

    # Relationships
    attachments = db.relationship(
        "Attachment", 
        backref="ticket", 
        lazy="dynamic",
        cascade="all, delete-orphan"
    )
    comments = db.relationship(
        "Comment", 
        backref="ticket", 
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="Comment.created_at.asc()"
    )
    history = db.relationship(
        "TicketHistory",
        backref="ticket",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="TicketHistory.created_at.desc()"
    )

    # ============================================================
    # SLA COMPUTED PROPERTIES
    # ============================================================
    
    @hybrid_property
    def sla_seconds_left(self):
        """Calculate seconds remaining until SLA deadline."""
        if not self.due_date:
            return None
        if self.status in ("Closed", "Resolved", "Not Open Yet"):
            return None
        delta = self.due_date - datetime.utcnow()
        return int(delta.total_seconds())

    @hybrid_property
    def sla_state(self):
        """
        Get current SLA state.
        Returns: "Met" / "At Risk" / "Breached" / None
        """
        if self.status in ("Closed", "Resolved"):
            # Check if closed within SLA
            if self.closed_at and self.due_date:
                if self.closed_at <= self.due_date:
                    return "Met"
                else:
                    return "Breached"
            return "Met"
        
        secs = self.sla_seconds_left
        if secs is None:
            return None
        
        if secs < 0:
            return "Breached"
        elif secs <= 6 * 3600:  # Less than 6 hours
            return "At Risk"
        else:
            return "Met"

    @hybrid_property
    def sla_countdown_human(self):
        """Get human-readable SLA countdown."""
        secs = self.sla_seconds_left
        if secs is None:
            return "N/A"

        if secs < 0:
            overdue = abs(secs)
            hours = overdue // 3600
            minutes = (overdue % 3600) // 60
            return f"Overdue by {hours}h {minutes}m"

        hours = secs // 3600
        minutes = (secs % 3600) // 60
        return f"{hours}h {minutes}m remaining"

    @hybrid_property
    def is_open(self):
        """Check if ticket is still active/open."""
        return self.status not in ("Open", "In Progress", "Re-Open")

    @hybrid_property
    def is_breached(self):
        """Check if ticket SLA is breached."""
        return self.sla_state == "Breached"

    @hybrid_property
    def is_at_risk(self):
        """Check if ticket SLA is at risk."""
        return self.sla_state == "At Risk"

    def add_comment(self, user, message, is_internal=False):
        """Add a comment to the ticket."""
        comment = Comment(
            ticket_id=self.id,
            user_id=user.id,
            message=message,
            is_internal=is_internal
        )
        db.session.add(comment)
        return comment

    def add_history_entry(self, user, event, event_type=None, old_value=None, new_value=None):
        """Add a history entry for ticket changes."""
        history = TicketHistory(
            ticket_id=self.id,
            event=event,
            event_type=event_type,
            user_id=user.id if user else None,
            old_value=old_value,
            new_value=new_value
        )
        db.session.add(history)
        return history

    def close_ticket(self):
        """Close the ticket and set closed timestamp."""
        self.status = "Closed"
        self.closed_at = datetime.utcnow()

    def reopen_ticket(self):
        """Reopen a closed ticket."""
        if self.status in ("Closed", "Resolved"):
            self.status = "Re-Open"
            self.closed_at = None

    def to_dict(self):
        """Convert ticket to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "ticket_no": self.ticket_no,
            "ticket_type": self.ticket_type,
            "category": self.category,
            "priority": self.priority,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.strftime('%b %d, %Y') if self.created_at else "N/A",
            "created_at_iso": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.strftime('%b %d, %Y') if self.updated_at else "N/A",
            "updated_at_iso": self.updated_at.isoformat() if self.updated_at else None,
            "due_date": self.due_date.strftime('%b %d, %Y') if self.due_date else "N/A",
            "due_date_iso": self.due_date.isoformat() if self.due_date else None,
            "closed_at": self.closed_at.strftime('%b %d, %Y') if self.closed_at else "N/A",
            "closed_at_iso": self.closed_at.isoformat() if self.closed_at else None,
            "sla_hours": self.sla_hours,
            "sla_state": self.sla_state,
            "sla_countdown_human": self.sla_countdown_human,
            "aging": self.aging,
            "user_name": self.user.name if self.user else "Unknown",
            "assignee_name": self.assignee.name if self.assignee else (self.assignee_name or "Unassigned"),
        }

    def __repr__(self):
        return f"<Ticket {self.ticket_no} - {self.status}>"


# ============================================================
#  AUTO UPDATE AGING ON LOAD
# ============================================================
@event.listens_for(Ticket, "load")
def update_ticket_aging(target, context):
    """
    Automatically calculate ticket aging when loaded from database.
    Aging = days since ticket creation (only for non-closed tickets).
    """
    if target.created_at:
        if target.status in ("Closed", "Resolved"):
            # For closed tickets, calculate aging from creation to closure
            if target.closed_at:
                target.aging = (target.closed_at.date() - target.created_at.date()).days
            else:
                target.aging = 0
        else:
            # For open tickets, calculate aging from creation to now
            target.aging = (datetime.utcnow().date() - target.created_at.date()).days


# ============================================================
#  COMMENT MODEL
# ============================================================
class Comment(db.Model):
    """
    Comments and updates on tickets.
    Used for communication between users and support staff.
    """
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    user = db.relationship("User", backref="comments")

    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Optional: Mark as internal (admin-only) comment
    is_internal = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Comment on Ticket #{self.ticket_id} by User #{self.user_id}>"


# ============================================================
#  ATTACHMENT MODEL
# ============================================================
class Attachment(db.Model):
    """
    File attachments for tickets.
    Stores filename and metadata.
    """
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)

    filename = db.Column(db.String(256), nullable=False)
    original_filename = db.Column(db.String(256), nullable=True)  # Store original name
    file_size = db.Column(db.Integer, nullable=True)  # Size in bytes
    mime_type = db.Column(db.String(100), nullable=True)
    
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def __repr__(self):
        return f"<Attachment {self.filename} on Ticket #{self.ticket_id}>"


# ============================================================
#  TICKET HISTORY MODEL
# ============================================================
class TicketHistory(db.Model):
    """
    Audit trail for ticket changes.
    Records all modifications to tickets.
    """
    __tablename__ = "ticket_history"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    
    event = db.Column(db.String(200), nullable=False)
    event_type = db.Column(db.String(50), nullable=True)  # created / updated / assigned / commented / closed
    
    # Track who made the change
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    user = db.relationship("User", backref="ticket_history_entries")
    
    # Optional: Store old and new values for changes
    old_value = db.Column(db.String(200), nullable=True)
    new_value = db.Column(db.String(200), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<TicketHistory #{self.id}: {self.event}>"


# ============================================================
#  EMAIL LOG MODEL
# ============================================================
class EmailLog(db.Model):
    """
    Log of all emails sent by the system.
    Used for auditing and troubleshooting email delivery.
    """
    __tablename__ = "email_logs"

    id = db.Column(db.Integer, primary_key=True)

    to_email = db.Column(db.String(255), nullable=False, index=True)
    from_email = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(255), nullable=False)
    body_preview = db.Column(db.Text, nullable=True)  # First 200 chars of body
    
    status = db.Column(db.String(20), default="SUCCESS", nullable=False, index=True)  # SUCCESS / FAILED / PENDING
    
    # Link to ticket if email is ticket-related
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True, index=True)
    ticket = db.relationship("Ticket", backref="email_logs")
    
    # Timestamps
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Error tracking
    error_message = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<EmailLog to={self.to_email} status={self.status}>"


# ============================================================
#  NOTIFICATION READ TRACKING MODEL
# ============================================================
class NotificationRead(db.Model):
    """
    Track which notifications have been marked as read by users.
    Each record represents a user marking a specific ticket notification as read.
    """
    __tablename__ = "notification_reads"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    
    # Timestamp when the notification was marked as read
    marked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship("User", backref="notification_reads")
    ticket = db.relationship("Ticket", backref="notification_reads")
    
    # Unique constraint to ensure one read record per user-ticket pair
    __table_args__ = (
        db.UniqueConstraint('user_id', 'ticket_id', name='unique_user_ticket_read'),
    )

    def __repr__(self):
        return f"<NotificationRead user={self.user_id} ticket={self.ticket_id} marked_at={self.marked_at}>"


# ============================================================
#  AUTO-GENERATE TICKET NUMBER
# ============================================================
@event.listens_for(Ticket, "before_insert")
def generate_ticket_no(mapper, connect, target):
    """
    Automatically generate unique ticket number before insert.
    Format: IT-YYYYMM-XXXX (e.g., IT-202412-0001)
    Sequential counter resets monthly.
    
    Only generates if ticket_no is not already set.
    """
    # Skip if ticket_no is already set (e.g., during testing/seeding)
    if target.ticket_no:
        return
    
    from sqlalchemy import select, func

    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)

    tbl = Ticket.__table__

    # Count tickets created this month
    res = connect.execute(
        select(func.count()).where(tbl.c.created_at >= month_start)
    ).scalar_one()

    seq = (res or 0) + 1
    target.ticket_no = f"IT-{now.strftime('%Y%m')}-{seq:04d}"


# ============================================================
#  DATABASE INITIALIZATION HELPER
# ============================================================
def init_db(app):
    """
    Initialize database with app context.
    Creates all tables if they don't exist.
    """
    with app.app_context():
        db.create_all()
        print("✓ Database tables created successfully")


def create_default_admin(app):
    """
    Create default admin user if none exists.
    Should be called after init_db.
    """
    with app.app_context():
        if not User.query.filter_by(role="admin").first():
            admin = User(
                name="System Administrator",
                email="admin@portal.com",
                role="admin",
                department="IT",
                active=True,
            )
            admin.set_password("Admin@123")
            db.session.add(admin)
            db.session.commit()
            print("✓ Default admin user created: admin@portal.com / Admin@123")
        else:
            print("✓ Admin user already exists")


# ============================================================
#  DATABASE QUERY HELPERS
# ============================================================
def get_open_tickets():
    """Get all open tickets."""
    return Ticket.query.filter(Ticket.status.in_(["Open", "In Progress", "Re-Open"])).all()


def get_breached_tickets():
    """Get all breached SLA tickets."""
    open_tickets = get_open_tickets()
    return [t for t in open_tickets if t.is_breached]


def get_at_risk_tickets():
    """Get all at-risk SLA tickets."""
    open_tickets = get_open_tickets()
    return [t for t in open_tickets if t.is_at_risk]


def get_tickets_by_priority(priority):
    """Get tickets by priority level."""
    return Ticket.query.filter_by(priority=priority).all()


def get_tickets_by_assignee(user_id):
    """Get tickets assigned to a specific user."""
    return Ticket.query.filter_by(assignee_id=user_id).all()


def get_recent_tickets(days=7):
    """Get tickets created in the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    return Ticket.query.filter(Ticket.created_at >= cutoff).all()


def get_user_by_email(email):
    """Get user by email address."""
    return User.query.filter_by(email=email).first()


def get_user_by_id(user_id):
    """Get user by ID."""
    return User.query.get(user_id)


def get_active_engineers():
    """Get all active engineers."""
    return User.query.filter_by(role="engineer", active=True).all()


def get_active_admins():
    """Get all active admins."""
    return User.query.filter_by(role="admin", active=True).all()


# ============================================================
#  NOTIFICATION HELPER FUNCTIONS
# ============================================================
def mark_notification_as_read(user_id, ticket_id):
    """
    Mark a specific ticket notification as read for a user.
    Creates or updates the read record.
    """
    try:
        read_record = NotificationRead.query.filter_by(
            user_id=user_id, 
            ticket_id=ticket_id
        ).first()
        
        if not read_record:
            read_record = NotificationRead(
                user_id=user_id,
                ticket_id=ticket_id,
                marked_at=datetime.utcnow()
            )
            db.session.add(read_record)
        else:
            read_record.marked_at = datetime.utcnow()
        
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error marking notification as read: {e}")
        return False


def mark_all_notifications_as_read(user_id):
    """
    Mark all unread notifications as read for a user.
    """
    try:
        # Get all tickets relevant to this user
        if user_id:
            user = User.query.get(user_id)
            if user and user.role == 'admin':
                # Admin: mark all recent tickets as read
                recent_tickets = Ticket.query.order_by(
                    Ticket.created_at.desc()
                ).limit(100).all()
            else:
                # User: mark their own tickets as read
                recent_tickets = Ticket.query.filter_by(
                    user_id=user_id
                ).order_by(Ticket.updated_at.desc()).limit(100).all()
            
            for ticket in recent_tickets:
                mark_notification_as_read(user_id, ticket.id)
        
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error marking all notifications as read: {e}")
        return False


def get_unread_notifications(user_id):
    """
    Get count of unread notifications for a user.
    """
    try:
        if not user_id:
            return 0
        
        user = User.query.get(user_id)
        if not user:
            return 0
        
        yesterday = datetime.utcnow() - timedelta(hours=24)
        
        if user.role == 'admin':
            # Admin: unread new tickets from last 24 hours
            unread = Ticket.query.filter(
                Ticket.created_at >= yesterday
            ).filter(
                ~Ticket.notification_reads.any(
                    NotificationRead.user_id == user_id
                )
            ).count()
        else:
            # User: unread updates to their tickets from last 24 hours
            unread = Ticket.query.filter(
                Ticket.user_id == user_id,
                Ticket.updated_at >= yesterday
            ).filter(
                ~Ticket.notification_reads.any(
                    NotificationRead.user_id == user_id
                )
            ).count()
        
        return unread
    except Exception as e:
        print(f"Error getting unread notification count: {e}")
        return 0


def is_notification_read(user_id, ticket_id):
    """
    Check if a specific notification has been marked as read.
    """
    try:
        read = NotificationRead.query.filter_by(
            user_id=user_id,
            ticket_id=ticket_id
        ).first()
        return read is not None
    except Exception as e:
        print(f"Error checking notification read status: {e}")
        return False
    

    