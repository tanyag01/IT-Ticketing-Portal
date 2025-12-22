import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # ============================================================
    # CORE SETTINGS
    # ============================================================
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "txt", "log", "docx", "doc", "zip", "xlsx"}

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # ============================================================
    # SLA SETTINGS
    # ============================================================
    # Default SLA = 24 hours unless overridden in environment
    SLA_HOURS = int(os.getenv("SLA_HOURS", "24"))

    # SLA warning threshold (send alert BEFORE breach)
    SLA_WARNING_HOURS = int(os.getenv("SLA_WARNING_HOURS", "2"))

    # Allow admin to receive summary emails
    DAILY_SUMMARY_EMAIL = os.getenv("DAILY_SUMMARY_EMAIL", "True") == "True"

    # Time to schedule daily report (24-hour format, UTC)
    DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "9"))

    # ============================================================
    # EMAIL CONFIGURATION (SMTP)
    # ============================================================
    """
    This mail config supports:
    - Gmail (with App Passwords)
    - Outlook / Office365
    - Custom corporate SMTP
    - SendGrid
    - Mailgun
    
    Gmail Setup:
    - Enable 2FA
    - Generate App Password (16 chars)
    - MAIL_USERNAME = your_email@gmail.com
    - MAIL_PASSWORD = your_app_password
    """

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))

    # Gmail & many SMTP providers use TLS
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True") == "True"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False") == "True"

    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

    # Default sender → same as login email (usually)
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME or "noreply@portal.com")

    # Suppress email sending in testing
    TESTING = os.getenv("TESTING", "False") == "True"

    # ============================================================
    # BACKGROUND TASKS & CELERY (OPTIONAL)
    # ============================================================
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TIMEZONE = "UTC"

    # ============================================================
    # PROJECT BRANDING & GENERAL
    # ============================================================
    PROJECT_NAME = os.getenv("PROJECT_NAME", "IT Ticketing Portal")
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Your Company")
    COMPANY_LOGO_URL = os.getenv("COMPANY_LOGO_URL", "/static/logo.png")

    # Support contact info
    SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@company.com")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@portal.com")

    # ============================================================
    # LOGGING & DEBUGGING
    # ============================================================
    # Enable debug email printing in development (prints instead of sending)
    DEBUG_EMAIL_OUTPUT = os.getenv("DEBUG_EMAIL_OUTPUT", "False") == "True"

    # Logging level
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Log file location
    LOG_FILE = os.getenv("LOG_FILE", str(BASE_DIR / "logs" / "app.log"))

    # ============================================================
    # SECURITY SETTINGS
    # ============================================================
    # Session config
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"  # Only HTTPS
    SESSION_COOKIE_HTTPONLY = os.getenv("SESSION_COOKIE_HTTPONLY", "True") == "True"
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")  # Lax / Strict / None
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days in seconds

    # Password policy
    MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "8"))
    REQUIRE_PASSWORD_UPPERCASE = os.getenv("REQUIRE_PASSWORD_UPPERCASE", "True") == "True"
    REQUIRE_PASSWORD_NUMBERS = os.getenv("REQUIRE_PASSWORD_NUMBERS", "True") == "True"
    REQUIRE_PASSWORD_SPECIAL = os.getenv("REQUIRE_PASSWORD_SPECIAL", "False") == "True"

    # ============================================================
    # PAGINATION & DEFAULTS
    # ============================================================
    # Items per page for list views
    ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", "20"))

    # Default ticket priority
    DEFAULT_TICKET_PRIORITY = os.getenv("DEFAULT_TICKET_PRIORITY", "Medium")

    # Allowed ticket statuses
    TICKET_STATUSES = ["Open", "In Progress", "Pending", "On Hold", "Closed", "Resolved"]

    # Allowed ticket types
    TICKET_TYPES = ["Hardware", "Software", "Network", "Access", "Other"]

    # Allowed ticket priorities
    TICKET_PRIORITIES = ["Low", "Medium", "High", "Critical"]

    # Allowed ticket categories
    TICKET_CATEGORIES = [
        "Account Management",
        "Hardware Support",
        "Software Support",
        "Network & Connectivity",
        "Email",
        "VPN",
        "Other"
    ]

    # ============================================================
    # ENVIRONMENT-SPECIFIC CONFIGS
    # ============================================================
    @classmethod
    def from_env(cls, env_name=None):
        """Load config based on environment variable or parameter."""
        env = env_name or os.getenv("FLASK_ENV", "development").lower()
        
        if env == "production":
            return ProductionConfig()
        elif env == "testing":
            return TestingConfig()
        else:
            return DevelopmentConfig()


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    DEBUG_EMAIL_OUTPUT = True
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_ECHO = True
    LOG_LEVEL = "DEBUG"


class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = False
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    DEBUG_EMAIL_OUTPUT = True
    SESSION_COOKIE_SECURE = False
    MAIL_DEFAULT_SENDER = "test@example.com"


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SQLALCHEMY_ECHO = False
    LOG_LEVEL = "WARNING"

    # In production, all these MUST be set via environment variables
    def __init__(self):
        super().__init__()
        
        # Validate critical production settings
        required_vars = ["SECRET_KEY", "MAIL_USERNAME", "MAIL_PASSWORD", "ADMIN_EMAIL"]
        missing = [var for var in required_vars if not os.getenv(var)]
        
        if missing:
            raise ValueError(f"Missing required production config vars: {', '.join(missing)}")

    @property
    def DATABASE_URL(self):
        """Ensure production uses proper database."""
        uri = os.getenv("DATABASE_URL", "")
        if uri.startswith("sqlite"):
            raise ValueError("SQLite not allowed in production. Use PostgreSQL or MySQL.")
        return uri