import os
import sys
from datetime import datetime, timedelta
from app import create_app
from models import db, User, Ticket, Comment, Attachment, TicketHistory, EmailLog
from werkzeug.security import generate_password_hash


def reset_database():
    """
    Reset entire database: drop all tables and recreate them.
    Creates default admin user for initial access.
    """
    app = create_app()

    with app.app_context():
        print("\n" + "="*60)
        print("DATABASE RESET")
        print("="*60)
        
        # Confirm destructive action
        if not os.getenv("FORCE_RESET"):
            response = input("\n⚠️  This will DELETE ALL DATA. Continue? (yes/no): ").strip().lower()
            if response != "yes":
                print("❌ Reset cancelled.")
                return

        db.drop_all()
        db.create_all()
        print("✓ Database tables dropped and recreated")

        # Create default admin
        create_default_admin(app)
        
        print("="*60 + "\n")


def create_default_admin(app):
    """
    Create default admin user if none exists.
    """
    with app.app_context():
        if User.query.filter_by(role="admin").first():
            print("✓ Admin user already exists (skipping)")
            return

        admin = User(
            name="System Administrator",
            email="admin@portal.com",
            role="admin",
            department="IT",
            active=True,
            theme_pref="dark"
        )
        admin.set_password("Admin@123")

        db.session.add(admin)
        db.session.commit()

        print("✓ Default admin created")
        print("  Email: admin@portal.com")
        print("  Password: Admin@123")
        print("  ⚠️  Change this password immediately after first login!")


def create_sample_data(app):
    """
    Create sample users, tickets, and comments for testing.
    Call only on clean database.
    """
    with app.app_context():
        print("\n" + "="*60)
        print("CREATING SAMPLE DATA")
        print("="*60)

        # Check if data already exists
        if User.query.filter_by(role="user").first():
            print("✓ Sample data already exists (skipping)")
            return

        # Create sample users
        users_data = [
            {
                "name": "John Smith",
                "email": "john@example.com",
                "role": "user",
                "department": "Sales",
            },
            {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "role": "user",
                "department": "Marketing",
            },
            {
                "name": "Engineer One",
                "email": "engineer1@example.com",
                "role": "engineer",
                "department": "IT Support",
            },
            {
                "name": "Engineer Two",
                "email": "engineer2@example.com",
                "role": "engineer",
                "department": "IT Support",
            },
            {
                "name": "Support Manager",
                "email": "manager@example.com",
                "role": "assignee",
                "department": "IT Support",
            },
        ]

        users = []
        for user_data in users_data:
            user = User(**user_data)
            user.set_password("Test@1234")
            db.session.add(user)
            users.append(user)

        db.session.commit()
        print(f"✓ Created {len(users)} sample users")

        # Create sample tickets
        tickets_data = [
            {
                "ticket_type": "Hardware",
                "category": "Hardware Support",
                "priority": "High",
                "description": "Laptop screen is flickering and displaying artifacts. Need immediate replacement.",
                "status": "Open",
                "user_id": users[0].id,
                "assignee_id": users[2].id,
                "sla_hours": 24,
            },
            {
                "ticket_type": "Software",
                "category": "Software Support",
                "priority": "Medium",
                "description": "Microsoft Office license activation issue. Error code 0x80070005.",
                "status": "In Progress",
                "user_id": users[1].id,
                "assignee_id": users[3].id,
                "sla_hours": 48,
            },
            {
                "ticket_type": "Access",
                "category": "Account Management",
                "priority": "Critical",
                "description": "Locked out of corporate email account. Cannot access important messages.",
                "status": "Open",
                "user_id": users[0].id,
                "assignee_id": users[4].id,
                "sla_hours": 4,
            },
            {
                "ticket_type": "Network",
                "category": "Network & Connectivity",
                "priority": "Medium",
                "description": "VPN connection drops frequently during video calls.",
                "status": "Pending",
                "user_id": users[1].id,
                "assignee_id": users[2].id,
                "sla_hours": 48,
            },
            {
                "ticket_type": "Other",
                "category": "Other",
                "priority": "Low",
                "description": "Request for additional monitor for dual-display setup.",
                "status": "On Hold",
                "user_id": users[0].id,
                "assignee_id": None,
                "sla_hours": 72,
            },
        ]

        tickets = []
        now = datetime.utcnow()
        
        for idx, ticket_data in enumerate(tickets_data):
            ticket = Ticket(**ticket_data)
            # Calculate due date based on SLA hours
            ticket.due_date = datetime.utcnow() + timedelta(hours=ticket.sla_hours)
            # Manually set ticket number to avoid auto-generation
            seq = idx + 1
            ticket.ticket_no = f"IT-{now.strftime('%Y%m')}-{seq:04d}"
            db.session.add(ticket)
            tickets.append(ticket)

        db.session.commit()
        print(f"✓ Created {len(tickets)} sample tickets")

        # Add some comments to tickets
        if len(tickets) > 0:
            comments = [
                {
                    "ticket_id": tickets[0].id,
                    "user_id": users[2].id,
                    "message": "I've ordered a replacement display. Should arrive within 2 business days.",
                    "is_internal": False,
                },
                {
                    "ticket_id": tickets[0].id,
                    "user_id": users[0].id,
                    "message": "Thank you! How will I use my laptop in the meantime?",
                    "is_internal": False,
                },
                {
                    "ticket_id": tickets[1].id,
                    "user_id": users[3].id,
                    "message": "Checking license server. Will provide update shortly.",
                    "is_internal": True,
                },
                {
                    "ticket_id": tickets[2].id,
                    "user_id": users[4].id,
                    "message": "Password reset link has been sent to your recovery email.",
                    "is_internal": False,
                },
            ]

            for comment_data in comments:
                comment = Comment(**comment_data)
                db.session.add(comment)

            db.session.commit()
            print(f"✓ Created {len(comments)} sample comments")

        # Add history entries
        for ticket in tickets:
            history_entry = TicketHistory(
                ticket_id=ticket.id,
                event=f"Ticket created",
                event_type="created",
                user_id=ticket.user_id,
            )
            db.session.add(history_entry)

            if ticket.assignee_id:
                assign_entry = TicketHistory(
                    ticket_id=ticket.id,
                    event=f"Assigned to {ticket.assignee.name}",
                    event_type="assigned",
                    user_id=None,
                    new_value=str(ticket.assignee_id),
                )
                db.session.add(assign_entry)

        db.session.commit()
        print(f"✓ Created history entries for {len(tickets)} tickets")

        print("="*60 + "\n")
        print("Sample data creation complete!")
        print("\nDefault Test Credentials:")
        print("  User: john@example.com / Test@1234")
        print("  Engineer: engineer1@example.com / Test@1234")
        print("  Admin: admin@portal.com / Admin@123")


def init_app_db(app=None):
    """
    Initialize application database.
    Creates tables if they don't exist.
    """
    if app is None:
        app = create_app()

    with app.app_context():
        db.create_all()
        print("✓ Database tables created/verified")


def seed_ticket_categories(app=None):
    """
    Pre-populate reference data (if needed).
    Can be extended for other lookup tables.
    """
    if app is None:
        app = create_app()

    with app.app_context():
        print("✓ Reference data verified")


def main():
    """
    Main CLI interface for database operations.
    """
    print("\n" + "="*60)
    print("IT TICKETING PORTAL - DATABASE MANAGEMENT")
    print("="*60 + "\n")

    if len(sys.argv) < 2:
        print("Usage: python db_init.py <command>")
        print("\nAvailable commands:")
        print("  init       - Initialize database (create tables)")
        print("  reset      - Reset database (DROP ALL DATA)")
        print("  seed       - Create sample data for testing")
        print("  fresh      - Reset + create sample data (full restart)")
        print("\nExample: python db_init.py fresh")
        return

    command = sys.argv[1].lower()
    app = create_app()

    if command == "init":
        init_app_db(app)
        print("\n✓ Database initialized successfully")

    elif command == "reset":
        reset_database()

    elif command == "seed":
        init_app_db(app)
        create_sample_data(app)

    elif command == "fresh":
        reset_database()
        create_sample_data(app)

    else:
        print(f"❌ Unknown command: {command}")
        print("Use: python db_init.py <init|reset|seed|fresh>")


if __name__ == "__main__":
    main()