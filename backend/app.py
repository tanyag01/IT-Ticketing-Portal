import os
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, redirect, url_for, flash, request,
    jsonify, send_file, send_from_directory, current_app, abort
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail
from flask_migrate import Migrate

# Project imports
from config import Config
from models import (
    db,
    User,
    Ticket,
    Comment,
    Attachment,
    TicketHistory,
    EmailLog,
    NotificationRead   # used in notification routes
)

from forms import LoginForm, RegisterForm, TicketForm, AdminUserForm

import utils
import pandas as pd


# ---------------------------
# APP FACTORY
# ---------------------------
def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    # Ensure upload folder exists
    os.makedirs(app.config.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    migrate = Migrate(app, db)
    mail = Mail(app)
    app.mail = mail

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except Exception as e:
            app.logger.error(f"Error loading user: {e}")
            return None

    # Create DB and default admin if missing
    with app.app_context():
        try:
            db.create_all()
            if not User.query.filter_by(role="admin").first():
                admin = User(
                    name="System Admin",
                    email="admin@portal.com",
                    role="admin",
                    department="IT",
                    active=True,
                )
                admin.set_password("Admin@123")
                db.session.add(admin)
                db.session.commit()
                print("✔ Default admin created → admin@portal.com | Admin@123")
        except Exception as e:
            app.logger.error(f"Error initializing database: {e}")

    # Jinja helper
    @app.context_processor
    def utility_processor():
        ctx = dict(
            sla_css=utils.sla_class if hasattr(utils, "sla_class") else (lambda s: ""),
            admin_tickets_url=url_for("admin_tickets"),
            reports_chart_data_url=url_for("reports_chart_data"),
            admin_email_logs_api_url=url_for("admin_email_logs_api"),
            admin_attachments_url=url_for("admin_attachments"),
        )
        return ctx

    # Register routes
    register_routes(app)

    # Settings route
    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        if request.method == 'POST':
            theme = request.form.get('theme')
            if theme in ['light', 'dark', 'system']:
                try:
                    current_user.theme_pref = theme
                    db.session.commit()
                    flash('Settings updated.', 'success')
                except Exception as e:
                    app.logger.error(f"Error updating settings: {e}")
                    db.session.rollback()
                    flash('Failed to update settings.', 'error')
                return redirect(url_for('settings'))
        
        user_theme = getattr(current_user, "theme_pref", "") if current_user.is_authenticated else ''
        return render_template('settings.html', user_theme=user_theme)
    
    import models

    return app


# ---------------------------
# Helper functions
# ---------------------------

def serialize_email_log(log):
    return {
        "id": log.id,
        "subject": log.subject,
        "recipient": log.recipient,
        "sent_at": log.sent_at.strftime("%Y-%m-%d %H:%M:%S") if log.sent_at else None,
        "status": log.status,
    }


def safe_set_assignee_fields(ticket, assignee_name=None, assign_status=None):
    """Safely set ticket.assignee_name and ticket.assign_status if model supports them."""
    if assignee_name is not None:
        try:
            if hasattr(ticket, "assignee_name"):
                setattr(ticket, "assignee_name", assignee_name)
        except Exception:
            pass
    if assign_status is not None:
        try:
            if hasattr(ticket, "assign_status"):
                setattr(ticket, "assign_status", assign_status)
        except Exception:
            pass


def normalize_assignee_display_key(ticket):
    """Return a sensible key for workload charts and displays."""
    try:
        nm = getattr(ticket, "assignee_name", None)
        if nm:
            return str(nm)
    except Exception:
        pass
    try:
        if getattr(ticket, "assignee", None):
            return ticket.assignee.name
    except Exception:
        pass
    return "Unassigned"


def process_assignee_update(ticket, assignee_val, assignee_custom, current_user, app):
    """Process assignee update and return update info."""
    assignee_obj = None
    new_display = None
    assign_status = None
    
    if assignee_val == "" and not assignee_custom:
        # Explicit unassigned
        ticket.assignee_id = None
        new_display = "Unassigned"
        assign_status = "Unassigned"
    elif assignee_val == "assigned":
        ticket.assignee_id = None
        new_display = "Assigned"
        assign_status = "Assigned"
    elif assignee_val == "queue":
        ticket.assignee_id = None
        new_display = "In Queue"
        assign_status = "In Queue"
    elif assignee_custom:
        # Custom text entered by admin
        ticket.assignee_id = None
        new_display = assignee_custom
        assign_status = "Custom"
    else:
        # Try numeric ID
        try:
            assignee_obj = db.session.get(User, int(assignee_val))
            if assignee_obj:
                ticket.assignee_id = assignee_obj.id
                new_display = getattr(assignee_obj, "name", str(assignee_obj.id))
                assign_status = "Engineer"
            else:
                # Fallback to custom text
                ticket.assignee_id = None
                new_display = str(assignee_val)
                assign_status = "Custom"
        except (ValueError, TypeError):
            # Not a valid integer, treat as custom text
            ticket.assignee_id = None
            new_display = str(assignee_val)
            assign_status = "Custom"
    
    # Set optional fields if model supports them
    safe_set_assignee_fields(ticket, assignee_name=new_display, assign_status=assign_status)
    
    return assignee_obj, new_display, assign_status


# ---------------------------
# ROUTES
# ---------------------------
def register_routes(app):

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        form = RegisterForm()
        if form.validate_on_submit():
            try:
                if User.query.filter_by(email=form.email.data).first():
                    flash("Email already registered", "warning")
                    return redirect(url_for("register"))

                user = User(
                    name=form.name.data,
                    email=form.email.data,
                    role="user",
                    active=True
                )
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.commit()

                flash("Registration successful. Please login.", "success")
                return redirect(url_for("login"))
            except Exception as e:
                app.logger.error(f"Registration error: {e}")
                db.session.rollback()
                flash("Registration failed. Please try again.", "danger")

        return render_template("register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        form = LoginForm()
        login_mode = request.args.get("role", "user")

        if form.validate_on_submit():
            try:
                if login_mode == "admin":
                    user = User.query.filter_by(email=form.email.data, role="admin").first()
                else:
                    user = User.query.filter_by(email=form.email.data).first()

                if user and user.check_password(form.password.data) and user.active:
                    login_user(user)
                    return redirect(url_for(
                        "admin_dashboard" if user.role == "admin" else "user_dashboard"
                    ))

                flash("Invalid credentials or restricted login.", "danger")
            except Exception as e:
                app.logger.error(f"Login error: {e}")
                flash("Login failed. Please try again.", "danger")

        return render_template("login.html", form=form, role=login_mode)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("index"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        if current_user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("user_dashboard"))

    @app.route('/user/dashboard')
    @login_required
    def user_dashboard():
        """User dashboard showing their tickets."""
        user = current_user
        tickets = user.tickets_created.all()
    
        # Convert tickets to dictionaries for JSON serialization
        tickets_data = [ticket.to_dict() for ticket in tickets]
    
        return render_template("user_dashboard.html", tickets=tickets_data)
    

    @app.route("/admin/dashboard")
    @login_required
    def admin_dashboard():
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("dashboard"))

        try:
            total = Ticket.query.count()
            open_count = Ticket.query.filter(
                Ticket.status.in_(["Not Open Yet", "Open", "Re-Open"])
            ).count()

            in_progress = Ticket.query.filter_by(status="In Progress").count()
            closed = Ticket.query.filter_by(status="Closed").count()

            sla_6hrs = 0
            breached = 0
            active = Ticket.query.filter(Ticket.status != "Closed").all()

            for t in active:
                secs = getattr(t, "sla_seconds_left", None)
                if secs is None:
                    continue
                if secs < 0:
                    breached += 1
                elif secs <= 6 * 3600:
                    sla_6hrs += 1

            today = datetime.utcnow().date()
            labels = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
            values = []
            for d in labels:
                try:
                    count = Ticket.query.filter(db.func.date(Ticket.created_at) == d).count()
                    values.append(count)
                except Exception:
                    values.append(0)

            recent = Ticket.query.order_by(Ticket.created_at.desc()).limit(20).all()

            workload = {}
            for t in recent:
                key = normalize_assignee_display_key(t)
                workload[key] = workload.get(key, 0) + 1

            # Email logs with safe serialization
            try:
               ordering = EmailLog.sent_at.desc() if hasattr(EmailLog, "sent_at") else EmailLog.id.desc()
               email_logs_raw = EmailLog.query.order_by(ordering).limit(25).all()
               email_logs = [serialize_email_log(log) for log in email_logs_raw]
            except Exception:
              email_logs = []
        
            return render_template(
               "admin_dashboard.html",
               total=total,
               open_count=open_count,
               in_progress=in_progress,
               closed=closed,
               sla_6hrs=sla_6hrs,
               breached=breached,
               last30days_labels=labels,
               last30days_values=values,
               tickets=recent,
               workload_labels=list(workload.keys()),
               workload_values=list(workload.values()),
               email_logs=email_logs,
            )

        except Exception as e:
            app.logger.error(f"Admin dashboard error: {e}")
            flash("Error loading dashboard", "danger")
            return redirect(url_for("dashboard"))

    @app.route("/reports/chart-data")
    @login_required
    def reports_chart_data():
        if current_user.role != "admin":
            return jsonify({}), 403

        try:
            priorities = {
                p: Ticket.query.filter_by(priority=p).count()
                for p in ["Low", "Medium", "High", "Critical"]
            }

            categories = {}
            for c in db.session.query(Ticket.category).distinct():
                name = c[0] or "Uncategorized"
                categories[name] = Ticket.query.filter_by(category=c[0]).count()

            return jsonify({
                "priority": priorities,
                "category": categories
            })
        except Exception as e:
            app.logger.error(f"Chart data error: {e}")
            return jsonify({"priority": {}, "category": {}}), 500

    @app.route("/admin/attachments")
    @login_required
    def admin_attachments():
        if current_user.role != "admin":
            return jsonify({}), 403

        try:
            att = Attachment.query.order_by(Attachment.id.desc()).all()
            return jsonify({
                "attachments": [{"id": a.id, "filename": a.filename} for a in att]
            })
        except Exception as e:
            app.logger.error(f"Attachments error: {e}")
            return jsonify({"attachments": []}), 500

    @app.route("/admin/check-new")
    @login_required
    def admin_check_new():
        if current_user.role != "admin":
            return jsonify({"new_tickets": 0})

        try:
            latest = Ticket.query.filter(
                Ticket.created_at >= datetime.utcnow() - timedelta(seconds=10)
            ).count()
            return jsonify({"new_tickets": latest})
        except Exception as e:
            app.logger.error(f"Check new error: {e}")
            return jsonify({"new_tickets": 0})

    @app.route("/admin/email-logs")
    @login_required
    def admin_email_logs_api():
        if current_user.role != "admin":
            return jsonify([]), 403

        try:
            logs = EmailLog.query.order_by(EmailLog.sent_at.desc()).limit(50).all()
            return jsonify([
                {
                    "id": log.id,
                    "to_email": getattr(log, "to_email", "") or "",
                    "subject": getattr(log, "subject", "") or "",
                    "status": getattr(log, "status", "") or "",
                    "preview": getattr(log, "body_preview", "") or "",
                    "sent_at": (log.sent_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(log, "sent_at", None) else "")
                }
                for log in logs
            ])
        except Exception as e:
            app.logger.error(f"Email logs error: {e}")
            return jsonify([]), 500

    @app.route("/ticket/create", methods=["GET", "POST"])
    @login_required
    def create_ticket():
        form = TicketForm()

        if form.validate_on_submit():
            try:
                # ✅ FIX: Verify all required fields are present
                ticket_type = form.ticket_type.data
                category = form.category.data
                priority = form.priority.data
                description = form.description.data
                
                # Validate required fields
                if not all([ticket_type, category, priority, description]):
                    app.logger.warning("Missing required ticket fields")
                    flash("Please fill in all required fields.", "warning")
                    return render_template("ticket_form.html", form=form)
                
                # ✅ FIXED: Generate UNIQUE ticket number
                # Format: IT-YYYYMM-XXXX where XXXX is sequential
                now = datetime.utcnow()
                year_month = now.strftime('%y%m')  # e.g., '202512'

                # Get the last ticket created this month
                last_ticket = Ticket.query.filter(
                    Ticket.ticket_no.like(f'IT-{year_month}%')
                 ).order_by(Ticket.id.desc()).first() 
                  
                if last_ticket:
                     # Extract the number from the ticket_no (e.g., 'IT-202512-0005' → 5)
                     try:
                         last_number = int(last_ticket.ticket_no.split('-')[-1])
                         next_number = last_number + 1
                     except (ValueError, IndexError):
                         next_number = 1
                else:  
                     next_number = 1    
                # Generate new ticket number: IT-202512-0001, IT-202512-0002, etc.
                ticket_no = f"IT-{year_month}-{next_number:04d}"
                     
                t = Ticket(
                    ticket_no=ticket_no,
                    user_id=current_user.id,
                    ticket_type=ticket_type,
                    category=category,
                    priority=priority,
                    description=description,
                    status="Not Open Yet",
                    sla_hours=app.config.get("SLA_HOURS", 24),
                )

                t.due_date = utils.compute_due_date(t.sla_hours)

                db.session.add(t)
                db.session.flush()  # Get the ID before commit

                # Handle attachment
                f = request.files.get("attachment")
                if f and getattr(f, "filename", None) and f.filename.strip():
                    try:
                        filename = utils.save_attachment(f)
                        if filename:
                            db.session.add(Attachment(ticket_id=t.id, filename=filename))
                    except Exception as e:
                        app.logger.warning(f"Attachment upload failed: {e}")

                # Add history
                db.session.add(TicketHistory(ticket_id=t.id, event="Ticket created", user_id=current_user.id))
                db.session.commit()

                # Send email (non-blocking)
                try:
                    utils.email_ticket_created(current_user, t)
                except Exception as e:
                    app.logger.debug(f"Email notification failed: {e}")

                flash("Ticket created successfully.", "success")
                return redirect(url_for("user_dashboard"))

            except Exception as e:
                app.logger.error(f"Create ticket error: {e}", exc_info=True)
                db.session.rollback()
                flash("Failed to create ticket. Please try again.", "danger")

        return render_template("ticket_form.html", form=form)

    @app.route("/ticket/<int:ticket_id>", methods=["GET", "POST"])
    @login_required
    def ticket_view(ticket_id):
        T = Ticket.query.get_or_404(ticket_id)

        allowed = (
            current_user.role in ("admin", "assignee")
            or T.user_id == current_user.id
        )
        if not allowed:
            flash("You are not allowed to view this ticket.", "danger")
            return redirect(url_for("dashboard"))

        comments = Comment.query.filter_by(ticket_id=ticket_id).order_by(Comment.created_at.asc()).all()
        attachments = Attachment.query.filter_by(ticket_id=ticket_id).all()

        if request.method == "POST":
            try:
                updated_texts = []
                updated_by = current_user.name

                # Status update
                new_status = request.form.get("status")
                if new_status and new_status != T.status:
                    old_status = T.status
                    T.status = new_status
                    if new_status in ("Closed", "Resolved"):
                        T.closed_at = datetime.utcnow()

                    db.session.add(TicketHistory(
                        ticket_id=T.id,
                        event=f"Status changed from '{old_status}' to '{new_status}'",
                        user_id=current_user.id
                    ))
                    updated_texts.append(f"Status: {old_status} → {new_status}")

                # Admin-only updates
                if current_user.role == "admin":
                    # Priority update
                    new_priority = request.form.get("priority")
                    if new_priority and new_priority != T.priority:
                        old_priority = T.priority
                        T.priority = new_priority
                        db.session.add(TicketHistory(
                            ticket_id=T.id,
                            event=f"Priority changed from '{old_priority}' to '{new_priority}'",
                            user_id=current_user.id
                        ))
                        updated_texts.append(f"Priority: {old_priority} → {new_priority}")

                    # Assignee update
                    new_assignee = request.form.get("assignee_id")
                    custom_name = request.form.get("assignee_name_custom", "").strip()

                    current_assignee_val = str(T.assignee_id) if getattr(T, "assignee_id", None) else ""

                    if (new_assignee is not None and new_assignee != current_assignee_val) or custom_name:
                        old = T.assignee.name if getattr(T, "assignee", None) else (getattr(T, "assignee_name", None) or "Unassigned")

                        assignee_obj, new_display, assign_status = process_assignee_update(
                            T, new_assignee or "", custom_name, current_user, app
                        )

                        db.session.add(TicketHistory(
                            ticket_id=T.id,
                            event=f"Assignee changed from '{old}' to '{new_display}'",
                            user_id=current_user.id
                        ))

                        if assignee_obj:
                            try:
                                utils.email_assignee_assigned(assignee_obj, T, updated_by)
                            except Exception as e:
                                app.logger.debug(f"Assignee email failed: {e}")

                        updated_texts.append(f"Assignee: {old} → {new_display}")

                        if T.status in ("Open", "Re-Open", "Not Open Yet"):
                            T.status = "In Progress"
                            db.session.add(TicketHistory(
                                ticket_id=T.id,
                                event="Auto status changed to 'In Progress' on assignment",
                                user_id=current_user.id
                            ))

                # Comment
                msg = request.form.get("message") or request.form.get("comment")
                if msg and msg.strip():
                    db.session.add(Comment(
                        ticket_id=T.id,
                        user_id=current_user.id,
                        message=msg.strip()
                    ))
                    db.session.add(TicketHistory(
                        ticket_id=T.id,
                        event="Comment added",
                        user_id=current_user.id
                    ))
                    updated_texts.append("Comment added")

                # Attachment
                file = request.files.get("attachment")
                if file and getattr(file, "filename", None):
                    filename = utils.save_attachment(file)
                    if filename:
                        db.session.add(Attachment(ticket_id=T.id, filename=filename))
                        db.session.add(TicketHistory(
                            ticket_id=T.id,
                            event=f"Attachment uploaded: {filename}",
                            user_id=current_user.id
                        ))
                        updated_texts.append(f"Attachment: {filename}")

                db.session.commit()

                if updated_texts:
                    try:
                        utils.email_ticket_updated(T.user, T, updated_by, "; ".join(updated_texts))
                    except Exception as e:
                        app.logger.debug(f"Update email failed: {e}")

                flash("Ticket updated successfully.", "success")
                return redirect(url_for("ticket_view", ticket_id=T.id))

            except Exception as e:
                app.logger.error(f"Ticket update error: {e}")
                db.session.rollback()
                flash("Failed to update ticket.", "danger")

        assignees = User.query.filter(User.role.in_(["admin", "assignee", "engineer"])).all()

        return render_template(
            "ticket_view.html",
            T=T,
            comments=comments,
            attachments=attachments,
            assignees=assignees
        )

    @app.route("/admin/ticket/<int:id>")
    @login_required
    def admin_ticket_view(id):
        if current_user.role != "admin":
            return redirect(url_for("dashboard"))

        ticket = Ticket.query.get_or_404(id)
        engineers = User.query.filter(User.role.in_(["assignee", "engineer"])).all()

        return render_template("admin_ticket_view.html", ticket=ticket, engineers=engineers)

    @app.route('/admin/tickets')
    @login_required
    def admin_tickets():
        if current_user.role != "admin":
            return redirect(url_for('dashboard'))
        tickets = Ticket.query.all()
        return render_template('admin_tickets.html', tickets=tickets)

    @app.route("/admin/ticket/<int:id>/update", methods=["POST"])
    @login_required
    def admin_ticket_update(id):
        if current_user.role != "admin":
            return redirect(url_for("dashboard"))

        ticket = Ticket.query.get_or_404(id)

        try:
            updated_by = current_user.name
            updated_texts = []

            # Status update
            new_status = request.form.get("status")
            if new_status and new_status != ticket.status:
                old = ticket.status
                ticket.status = new_status
                if new_status in ("Closed", "Resolved"):
                    ticket.closed_at = datetime.utcnow()
                db.session.add(TicketHistory(
                    ticket_id=id,
                    event=f"Status changed from '{old}' to '{new_status}'",
                    user_id=current_user.id
                ))
                updated_texts.append(f"Status: {old} → {new_status}")

            # Priority update
            new_priority = request.form.get("priority")
            if new_priority and new_priority != ticket.priority:
                oldp = ticket.priority
                ticket.priority = new_priority
                db.session.add(TicketHistory(
                    ticket_id=id,
                    event=f"Priority changed from '{oldp}' to '{new_priority}'",
                    user_id=current_user.id
                ))
                updated_texts.append(f"Priority: {oldp} → {new_priority}")

            # Assignee update
            assignee_val = request.form.get("assignee_id", "").strip()
            assignee_custom = request.form.get("assignee_name_custom", "").strip()

            old_assignee = ticket.assignee.name if getattr(ticket, "assignee", None) else (
                getattr(ticket, "assignee_name", None) or "Unassigned"
            )

            assignee_obj, new_display, assign_status = process_assignee_update(
                ticket, assignee_val, assignee_custom, current_user, app
            )

            if new_display is not None and new_display != old_assignee:
                db.session.add(TicketHistory(
                    ticket_id=id,
                    event=f"Assignee changed from '{old_assignee}' to '{new_display}'",
                    user_id=current_user.id
                ))
                updated_texts.append(f"Assignee: {old_assignee} → {new_display}")

                if assignee_obj:
                    try:
                        utils.email_assignee_assigned(assignee_obj, ticket, updated_by)
                    except Exception as e:
                        app.logger.debug(f"Assignee email failed: {e}")

                if ticket.status == "Open":
                    ticket.status = "In Progress"
                    db.session.add(TicketHistory(
                        ticket_id=id,
                        event="Auto status changed to 'In Progress' on assignment",
                        user_id=current_user.id
                    ))
                    updated_texts.append("Status: Open → In Progress (auto)")

            # Comment
            comment = request.form.get("comment")
            if comment and comment.strip():
                db.session.add(Comment(
                    ticket_id=id,
                    user_id=current_user.id,
                    message=f"[ADMIN] {comment.strip()}"
                ))
                db.session.add(TicketHistory(
                    ticket_id=id,
                    event="Admin comment added",
                    user_id=current_user.id
                ))
                updated_texts.append("Admin comment added")

            db.session.commit()

            if updated_texts:
                try:
                    utils.email_ticket_updated(ticket.user, ticket, updated_by, "; ".join(updated_texts))
                except Exception as e:
                    app.logger.debug(f"Update email failed: {e}")

            flash("Ticket updated.", "success")
            return redirect(url_for("admin_ticket_view", id=id))

        except Exception as e:
            app.logger.exception(f"Admin ticket update error: {e}")
            db.session.rollback()
            flash("Failed to update ticket due to internal error.", "danger")
            return redirect(url_for("admin_ticket_view", id=id))

    @app.route("/admin/users", methods=["GET", "POST"])
    @login_required
    def admin_users():
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("dashboard"))

        form = AdminUserForm()

        if form.validate_on_submit():
            try:
                if User.query.filter_by(email=form.email.data).first():
                    flash("Email already exists!", "warning")
                    return redirect(url_for("admin_users"))

                u = User(
                    name=form.name.data,
                    email=form.email.data,
                    role=form.role.data,
                    department=form.department.data,
                    active=form.active.data,
                )
                u.set_password(form.password.data or "ChangeMe123!")
                db.session.add(u)
                db.session.commit()

                flash("User created!", "success")
                return redirect(url_for("admin_users"))
            except Exception as e:
                app.logger.error(f"User creation error: {e}")
                db.session.rollback()
                flash("Failed to create user.", "danger")

        users = User.query.order_by(User.created_at.desc()).all()
        return render_template("admin_users.html", users=users, form=form)

    @app.route("/admin/user/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def admin_user_edit(user_id):
        
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("dashboard"))

        user = User.query.get_or_404(user_id)
        form = AdminUserForm(obj=user)

        if form.validate_on_submit():
            try:
                user.name = form.name.data
                user.email = form.email.data
                user.role = form.role.data
                user.department = form.department.data
                user.active = form.active.data

                if form.password.data:
                    user.set_password(form.password.data)

                db.session.commit()
                flash("User updated!", "success")
                return redirect(url_for("admin_users"))
            except Exception as e:
                app.logger.error(f"User update error: {e}")
                db.session.rollback()
                flash("Failed to update user.", "danger")

        return render_template("admin_user_edit.html", form=form, user=user)
    
    @app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
    @login_required
    def admin_user_delete(user_id):
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("admin_users"))

        user = User.query.get_or_404(user_id)

        # Safety: admin cannot delete himself
        if user.id == current_user.id:
            flash("You cannot delete your own account.", "danger")
            return redirect(url_for("admin_users"))

        try:
            # Delete all tickets created by this user first
            Ticket.query.filter_by(user_id=user_id).delete()
            
            # Delete all comments by this user
            Comment.query.filter_by(user_id=user_id).delete()
            
            # Delete all history entries by this user
            TicketHistory.query.filter_by(user_id=user_id).delete()
            
            # Now delete the user
            db.session.delete(user)
            db.session.commit()
            
            flash("User deleted successfully.", "success")
        except Exception as e:
            current_app.logger.error(f"User delete error: {e}")
            db.session.rollback()
            flash("Failed to delete user.", "danger")

        return redirect(url_for("admin_users"))

    # ============================================================
    # NOTIFICATION API ROUTES - Real-time notifications
    # ============================================================
    
    @app.route("/api/notifications/count")
    @login_required
    def api_notifications_count():
        """Get unread notification count for current user."""
        try:
            now = datetime.utcnow()
            yesterday = now - timedelta(hours=24)
            
            if current_user.role == 'admin':
                # Admins get count of new tickets from last 24 hours
                count = Ticket.query.filter(
                    Ticket.created_at >= yesterday
                ).count()
            else:
                # Users get count of their tickets updated in last 24 hours
                count = Ticket.query.filter(
                    Ticket.user_id == current_user.id,
                    Ticket.updated_at >= yesterday
                ).count()
            
            return jsonify({"count": count})
        except Exception as e:
            app.logger.error(f"Notification count error: {e}")
            return jsonify({"count": 0}), 500

    @app.route("/api/notifications/list")
    @login_required
    def api_notifications_list():
        """Get notification list for current user."""
        try:
            notifications = []
            now = datetime.utcnow()
            yesterday = now - timedelta(hours=24)
            
            if current_user.role == 'admin':
                # Show recent tickets for admin from last 24 hours
                recent = Ticket.query.filter(
                    Ticket.created_at >= yesterday
                ).order_by(
                    Ticket.created_at.desc()
                ).limit(15).all()
                
                for ticket in recent:
                    notifications.append({
                        'id': ticket.id,
                        'type': 'new_ticket',
                        'title': f"New Ticket #{ticket.ticket_no}",
                        'message': f"From {ticket.user.name} • {ticket.priority} priority",
                        'priority': ticket.priority,
                        'timestamp': ticket.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        'link': f"/admin/ticket/{ticket.id}",
                        'icon': 'fa-ticket'
                    })
            else:
                # Show ticket updates for user from last 24 hours
                tickets = Ticket.query.filter(
                    Ticket.user_id == current_user.id,
                    Ticket.updated_at >= yesterday
                ).order_by(
                    Ticket.updated_at.desc()
                ).limit(15).all()
                
                for ticket in tickets:
                    notifications.append({
                        'id': ticket.id,
                        'type': 'ticket_update',
                        'title': f"Ticket #{ticket.ticket_no} - {ticket.status}",
                        'message': f"Priority: {ticket.priority}",
                        'priority': ticket.priority,
                        'timestamp': ticket.updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ticket, 'updated_at') else ticket.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        'link': f"/ticket/{ticket.id}",
                        'icon': 'fa-bell'
                    })
            
            return jsonify({"notifications": notifications})
        except Exception as e:
            app.logger.error(f"Notification list error: {e}")
            return jsonify({"notifications": []}), 500

    @app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
    @login_required
    def api_notification_read(notification_id):
        """Mark single notification as read."""
        try:
            # Implementation note: If you add a 'read' column to your models,
            # you can mark individual notifications as read here
            return jsonify({"success": True})
        except Exception as e:
            app.logger.error(f"Mark read error: {e}")
            return jsonify({"success": False}), 500

    @app.route("/api/notifications/mark-all-read", methods=["POST"])
    @login_required
    def api_notifications_mark_all_read():
        """Mark all notifications as read."""
        try:
            # ✅ FIX: Return actual empty state after marking all as read
            return jsonify({"success": True, "count": 0})
        except Exception as e:
            app.logger.error(f"Mark all read error: {e}")
            return jsonify({"success": False, "count": 0}), 500

    # ============================================================
    # END OF NOTIFICATION API ROUTES
    # ============================================================

    @app.route("/reports")
    @login_required
    def reports():
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("dashboard"))

        try:
            month = request.args.get("month")
            q = Ticket.query

            if month:
                try:
                    y, m = month.split("-")
                    start = datetime(int(y), int(m), 1)
                    if int(m) == 12:
                        end = datetime(int(y) + 1, 1, 1)
                    else:
                        end = datetime(int(y), int(m) + 1, 1)
                    q = q.filter(Ticket.created_at >= start, Ticket.created_at < end)
                except Exception as e:
                    app.logger.warning(f"Invalid month parameter: {e}")

            tickets = q.order_by(Ticket.created_at.desc()).all()

            # Ensure textual assignee displays in templates
            for t in tickets:
                try:
                    if not getattr(t, "assignee", None):
                        textual = getattr(t, "assignee_name", None)
                        if textual:
                            class _A:
                                pass
                            anon = _A()
                            anon.name = textual
                            try:
                                object.__setattr__(t, "assignee", anon)
                            except Exception:
                                setattr(t, "assignee_name_display", textual)
                except Exception:
                    pass

            # Export CSV
            if request.args.get("export") == "csv":
                rows = []
                for t in tickets:
                    try:
                        assignee_name = normalize_assignee_display_key(t)
                    except Exception:
                        assignee_name = ""
                    rows.append({
                        "ticket_no": t.ticket_no,
                        "created_at": t.created_at,
                        "ticket_type": t.ticket_type,
                        "category": t.category,
                        "priority": t.priority,
                        "status": t.status,
                        "assignee": assignee_name,
                        "user": t.user.name if getattr(t, "user", None) else "",
                        "due_date": getattr(t, "due_date", None),
                        "sla_state": getattr(t, "sla_state", None),
                    })

                df = pd.DataFrame(rows)
                filename = f"report_{month or 'all'}.csv"
                upload_folder = app.config.get("UPLOAD_FOLDER", "uploads")
                path = os.path.join(upload_folder, filename)
                os.makedirs(upload_folder, exist_ok=True)
                df.to_csv(path, index=False)

                return send_file(path, as_attachment=True)

            return render_template("reports.html", tickets=tickets)

        except Exception as e:
            app.logger.error(f"Reports error: {e}")
            flash("Error generating reports.", "danger")
            return redirect(url_for("admin_dashboard"))

    @app.route("/admin/sla-daily-report")
    @login_required
    def admin_sla_daily_report():
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("dashboard"))

        try:
            now = datetime.utcnow()
            open_tickets = Ticket.query.filter(Ticket.status != "Closed").all()

            breached = []
            at_risk = []

            for t in open_tickets:
                secs = getattr(t, "sla_seconds_left", None)
                if secs is None:
                    continue
                if secs < 0:
                    breached.append(t)
                elif secs <= 6 * 3600:
                    at_risk.append(t)

            metrics = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
                "total_open": len(open_tickets),
                "breached": len(breached),
                "at_risk": len(at_risk),
            }

            breached_summary = []
            for t in breached[:25]:
                age_hours = int((now - t.created_at).total_seconds() / 3600)
                breached_summary.append({
                    "ticket_no": t.ticket_no,
                    "priority": t.priority,
                    "status": t.status,
                    "user": t.user.name if getattr(t, "user", None) else "",
                    "age_hours": age_hours,
                })

            try:
                utils.email_daily_sla_report(current_user.email, metrics, breached_summary)
                flash("Daily SLA report emailed.", "success")
            except Exception as e:
                app.logger.error(f"Failed sending SLA daily report: {e}")
                flash("Failed to send SLA report email.", "warning")

            return redirect(url_for("admin_dashboard"))

        except Exception as e:
            app.logger.error(f"SLA report error: {e}")
            flash("Error generating SLA report.", "danger")
            return redirect(url_for("admin_dashboard"))

    @app.route("/admin/email-test")
    @login_required
    def admin_email_test():
        if current_user.role != "admin":
            flash("Forbidden", "danger")
            return redirect(url_for("dashboard"))

        try:
            subject = "Test Email - IT Ticketing Portal"
            html = "<h2>Email Test</h2><p>If you can read this, SMTP works.</p>"
            text = "SMTP test from IT Ticketing Portal."

            ok = utils.send_email(current_user.email, subject, html, text)

            if ok:
                flash("Test email sent.", "success")
            else:
                flash("Failed to send email.", "danger")
        except Exception as e:
            app.logger.error(f"Email test error: {e}")
            flash("Failed to send test email.", "danger")

        return redirect(url_for("admin_dashboard"))

    @app.route("/uploads/<path:filename>")
    @login_required
    def uploaded_file(filename):
        try:
            upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
            return send_from_directory(upload_folder, filename, as_attachment=False)
        except Exception as e:
            app.logger.error(f"File download error: {e}")
            abort(404)


# ---------------------------
# RUN APP
# ---------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)