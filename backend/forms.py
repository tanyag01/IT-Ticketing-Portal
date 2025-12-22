from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import (
    StringField, 
    PasswordField, 
    TextAreaField, 
    SelectField, 
    FileField, 
    BooleanField,
    SubmitField,
    IntegerField
)
from wtforms.validators import (
    InputRequired, 
    Length, 
    Email, 
    EqualTo, 
    Optional,
    ValidationError,
    Regexp,
    NumberRange
)
from models import User


# ============================================================
# FORM CHOICES (from config or hardcoded)
# ============================================================
PRIORITY_CHOICES = [
    ("Low", "Low"),
    ("Medium", "Medium"),
    ("High", "High"),
    ("Critical", "Critical")
]

TICKET_TYPES = [
    ("Hardware", "Hardware"),
    ("Software", "Software"),
    ("Network", "Network"),
    ("Access", "Access"),
    ("Other", "Other")
]

CATEGORY_CHOICES = [
    ("Account Management", "Account Management"),
    ("Hardware Support", "Hardware Support"),
    ("Software Support", "Software Support"),
    ("Network & Connectivity", "Network & Connectivity"),
    ("Email", "Email"),
    ("VPN", "VPN"),
    ("Other", "Other")
]

# ======= USER STATUS (Limited for regular users) =======
TICKET_STATUS_CHOICES_USER = [
    ("Not Open Yet", "Not Open Yet")
]

# ======= ADMIN STATUS (Full options for admins) =======
TICKET_STATUS_CHOICES_ADMIN = [
    ("Not Open Yet", "Not Open Yet"),
    ("Open", "Open"),
    ("In Progress", "In Progress"),
    ("Re-Open", "Re-Open"),
    ("Closed", "Closed"),
    ("Resolved", "Resolved")
]

# For backward compatibility
TICKET_STATUS_CHOICES = TICKET_STATUS_CHOICES_ADMIN

ROLE_CHOICES = [
    ("user", "Regular User"),
    ("engineer", "Engineer"),
    ("assignee", "Ticket Assignee"),
    ("admin", "Administrator")
]

DEPARTMENT_CHOICES = [
    ("IT", "IT"),
    ("Sales", "Sales"),
    ("Marketing", "Marketing"),
    ("Finance", "Finance"),
    ("HR", "HR"),
    ("Operations", "Operations"),
    ("Other", "Other")
]

THEME_CHOICES = [
    ("light", "Light"),
    ("dark", "Dark"),
    ("system", "System Default")
]


# ============================================================
# VALIDATORS (Custom)
# ============================================================
class PasswordValidator:
    """
    Validate password strength based on config requirements.
    """
    def __init__(self, min_length=8, require_upper=True, require_numbers=True, require_special=False):
        self.min_length = min_length
        self.require_upper = require_upper
        self.require_numbers = require_numbers
        self.require_special = require_special

    def __call__(self, form, field):
        password = field.data
        
        if len(password) < self.min_length:
            raise ValidationError(f"Password must be at least {self.min_length} characters long.")
        
        if self.require_upper and not any(c.isupper() for c in password):
            raise ValidationError("Password must contain at least one uppercase letter.")
        
        if self.require_numbers and not any(c.isdigit() for c in password):
            raise ValidationError("Password must contain at least one number.")
        
        if self.require_special and not any(c in "!@#$%^&*" for c in password):
            raise ValidationError("Password must contain at least one special character (!@#$%^&*).")


def email_exists(form, field):
    """Validate that email is not already registered."""
    user = User.query.filter_by(email=field.data).first()
    if user:
        raise ValidationError("Email already registered. Please login or use a different email.")


def email_unique(form, field, exclude_user_id=None):
    """Validate email uniqueness with optional exclusion."""
    query = User.query.filter_by(email=field.data)
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    
    if query.first():
        raise ValidationError("This email is already in use.")


# ============================================================
# AUTHENTICATION FORMS
# ============================================================
class LoginForm(FlaskForm):
    """User login form."""
    email = StringField(
        "Email",
        validators=[
            InputRequired(message="Email is required"),
            Email(message="Invalid email address"),
            Length(max=180)
        ],
        render_kw={"placeholder": "your@email.com", "class": "form-control"}
    )
    
    password = PasswordField(
        "Password",
        validators=[InputRequired(message="Password is required")],
        render_kw={"placeholder": "Enter your password", "class": "form-control"}
    )
    
    remember_me = BooleanField(
        "Remember me",
        default=False,
        render_kw={"class": "form-check-input"}
    )
    
    submit = SubmitField("Login", render_kw={"class": "btn btn-primary w-100"})


class RegisterForm(FlaskForm):
    """User registration form."""
    name = StringField(
        "Full Name",
        validators=[
            InputRequired(message="Name is required"),
            Length(min=2, max=120, message="Name must be 2-120 characters")
        ],
        render_kw={"placeholder": "John Smith", "class": "form-control"}
    )
    
    email = StringField(
        "Email",
        validators=[
            InputRequired(message="Email is required"),
            Email(message="Invalid email address"),
            Length(max=180),
            email_exists
        ],
        render_kw={"placeholder": "your@email.com", "class": "form-control"}
    )
    
    password = PasswordField(
        "Password",
        validators=[
            InputRequired(message="Password is required"),
            Length(min=8, message="Password must be at least 8 characters"),
            PasswordValidator(min_length=8, require_upper=True, require_numbers=True)
        ],
        render_kw={"placeholder": "Min 8 chars, 1 uppercase, 1 number", "class": "form-control"}
    )
    
    password_confirm = PasswordField(
        "Confirm Password",
        validators=[
            InputRequired(message="Please confirm your password"),
            EqualTo("password", message="Passwords must match")
        ],
        render_kw={"placeholder": "Confirm your password", "class": "form-control"}
    )
    
    submit = SubmitField("Register", render_kw={"class": "btn btn-primary w-100"})


class ChangePasswordForm(FlaskForm):
    """Change password form."""
    current_password = PasswordField(
        "Current Password",
        validators=[InputRequired(message="Current password is required")],
        render_kw={"class": "form-control"}
    )
    
    new_password = PasswordField(
        "New Password",
        validators=[
            InputRequired(message="New password is required"),
            Length(min=8),
            PasswordValidator(min_length=8, require_upper=True, require_numbers=True),
            EqualTo("new_password_confirm", message="Passwords must match")
        ],
        render_kw={"placeholder": "Min 8 chars, 1 uppercase, 1 number", "class": "form-control"}
    )
    
    new_password_confirm = PasswordField(
        "Confirm New Password",
        validators=[InputRequired(message="Please confirm new password")],
        render_kw={"class": "form-control"}
    )
    
    submit = SubmitField("Change Password", render_kw={"class": "btn btn-primary"})


# ============================================================
# TICKET FORMS - USER VERSION (Limited Status)
# ============================================================
class TicketForm(FlaskForm):
    """Create ticket form for REGULAR USERS - Status limited to 'Not Open Yet' only."""

    # ✅ USER VERSION: Limited to "Not Open Yet" ONLY
    status = SelectField(
        "Status",
        choices=TICKET_STATUS_CHOICES_USER,
        default="Not Open Yet",
        validators=[InputRequired(message="Status is required")],
        render_kw={"class": "form-select"}
    )

    ticket_type = SelectField(
        "Ticket Type",
        choices=TICKET_TYPES,
        validators=[InputRequired(message="Ticket type is required")],
        render_kw={"class": "form-select"}
    )
    
    category = SelectField(
        "Category",
        choices=CATEGORY_CHOICES,
        validators=[InputRequired(message="Category is required")],
        render_kw={"class": "form-select"}
    )
    
    priority = SelectField(
        "Priority",
        choices=PRIORITY_CHOICES,
        default="Medium",
        validators=[InputRequired(message="Priority is required")],
        render_kw={"class": "form-select"}
    )
    
    description = TextAreaField(
        "Description",
        validators=[
            InputRequired(message="Description is required"),
            Length(min=10, max=5000, message="Description must be 10-5000 characters")
        ],
        render_kw={"class": "form-control", "rows": 6, "placeholder": "Describe your issue in detail..."}
    )
    
    attachment = FileField(
        "Attachment (optional)",
        validators=[
            Optional(),
            FileAllowed(
                ["pdf", "doc", "docx", "txt", "png", "jpg", "jpeg", "gif", "zip"],
                message="File type not allowed. Max 16MB."
            )
        ],
        render_kw={"class": "form-control", "accept": ".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.gif,.zip"}
    )
    
    submit = SubmitField("Create Ticket", render_kw={"class": "btn btn-primary"})


# ============================================================
# TICKET FORMS - ADMIN VERSION (Full Status)
# ============================================================
class TicketEditForm(FlaskForm):
    """Edit ticket form for ADMINS/ENGINEERS - Full status options available."""
    
    # ✅ ADMIN VERSION: Full status options for administrators
    status = SelectField(
        "Status",
        choices=TICKET_STATUS_CHOICES_ADMIN,
        validators=[InputRequired(message="Status is required")],
        render_kw={"class": "form-select"}
    )
    
    priority = SelectField(
        "Priority",
        choices=PRIORITY_CHOICES,
        validators=[InputRequired(message="Priority is required")],
        render_kw={"class": "form-select"}
    )
    
    assignee_id = SelectField(
        "Assign To",
        coerce=int,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    description = TextAreaField(
        "Description",
        validators=[
            InputRequired(message="Description is required"),
            Length(min=10, max=5000)
        ],
        render_kw={"class": "form-control", "rows": 6}
    )
    
    sla_hours = IntegerField(
        "SLA Hours",
        validators=[
            InputRequired(message="SLA hours is required"),
            NumberRange(min=1, max=720, message="SLA must be 1-720 hours")
        ],
        render_kw={"class": "form-control"}
    )
    
    submit = SubmitField("Update Ticket", render_kw={"class": "btn btn-primary"})


# ============================================================
# ADMIN TICKET CREATION FORM (if admins can create tickets)
# ============================================================
class AdminCreateTicketForm(FlaskForm):
    """Create ticket form for ADMINS - with full status options."""
    
    # ✅ Admin can set any status when creating
    status = SelectField(
        "Status",
        choices=TICKET_STATUS_CHOICES_ADMIN,
        default="Not Open Yet",
        validators=[InputRequired(message="Status is required")],
        render_kw={"class": "form-select"}
    )

    ticket_type = SelectField(
        "Ticket Type",
        choices=TICKET_TYPES,
        validators=[InputRequired(message="Ticket type is required")],
        render_kw={"class": "form-select"}
    )
    
    category = SelectField(
        "Category",
        choices=CATEGORY_CHOICES,
        validators=[InputRequired(message="Category is required")],
        render_kw={"class": "form-select"}
    )
    
    priority = SelectField(
        "Priority",
        choices=PRIORITY_CHOICES,
        default="Medium",
        validators=[InputRequired(message="Priority is required")],
        render_kw={"class": "form-select"}
    )
    
    description = TextAreaField(
        "Description",
        validators=[
            InputRequired(message="Description is required"),
            Length(min=10, max=5000, message="Description must be 10-5000 characters")
        ],
        render_kw={"class": "form-control", "rows": 6, "placeholder": "Describe the issue..."}
    )
    
    attachment = FileField(
        "Attachment (optional)",
        validators=[
            Optional(),
            FileAllowed(
                ["pdf", "doc", "docx", "txt", "png", "jpg", "jpeg", "gif", "zip"],
                message="File type not allowed. Max 16MB."
            )
        ],
        render_kw={"class": "form-control", "accept": ".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.gif,.zip"}
    )
    
    submit = SubmitField("Create Ticket", render_kw={"class": "btn btn-primary"})


# ============================================================
# COMMENT FORM
# ============================================================
class CommentForm(FlaskForm):
    """Add comment to ticket."""
    message = TextAreaField(
        "Add Comment",
        validators=[
            InputRequired(message="Comment cannot be empty"),
            Length(min=1, max=2000, message="Comment must be 1-2000 characters")
        ],
        render_kw={"class": "form-control", "rows": 3, "placeholder": "Type your comment..."}
    )
    
    is_internal = BooleanField(
        "Internal Comment (admin/engineer only)",
        default=False,
        render_kw={"class": "form-check-input"}
    )
    
    submit = SubmitField("Post Comment", render_kw={"class": "btn btn-sm btn-primary"})


# ============================================================
# USER MANAGEMENT FORMS (ADMIN)
# ============================================================
class AdminUserForm(FlaskForm):
    """Create/edit user form (admin only)."""
    name = StringField(
        "Full Name",
        validators=[
            InputRequired(message="Name is required"),
            Length(min=2, max=120)
        ],
        render_kw={"class": "form-control"}
    )
    
    email = StringField(
        "Email",
        validators=[
            InputRequired(message="Email is required"),
            Email(message="Invalid email"),
            Length(max=180)
        ],
        render_kw={"class": "form-control"}
    )
    
    role = SelectField(
        "Role",
        choices=ROLE_CHOICES,
        validators=[InputRequired()],
        render_kw={"class": "form-select"}
    )
    
    department = SelectField(
        "Department",
        choices=DEPARTMENT_CHOICES,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    active = BooleanField(
        "Active User",
        default=True,
        render_kw={"class": "form-check-input"}
    )
    
    password = PasswordField(
        "Password (leave blank to keep current)",
        validators=[Optional()],
        render_kw={"class": "form-control", "placeholder": "Leave blank to skip password change"}
    )
    
    submit = SubmitField("Save User", render_kw={"class": "btn btn-primary"})


class AdminCreateUserForm(FlaskForm):
    """Create new user form (admin only)."""
    name = StringField(
        "Full Name",
        validators=[
            InputRequired(message="Name is required"),
            Length(min=2, max=120)
        ],
        render_kw={"class": "form-control"}
    )
    
    email = StringField(
        "Email",
        validators=[
            InputRequired(message="Email is required"),
            Email(message="Invalid email"),
            Length(max=180),
            email_exists
        ],
        render_kw={"class": "form-control"}
    )
    
    role = SelectField(
        "Role",
        choices=ROLE_CHOICES,
        default="user",
        validators=[InputRequired()],
        render_kw={"class": "form-select"}
    )
    
    department = SelectField(
        "Department",
        choices=DEPARTMENT_CHOICES,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    password = PasswordField(
        "Password",
        validators=[
            InputRequired(message="Password is required"),
            Length(min=8),
            PasswordValidator(min_length=8, require_upper=True, require_numbers=True)
        ],
        render_kw={"class": "form-control"}
    )
    
    password_confirm = PasswordField(
        "Confirm Password",
        validators=[
            InputRequired(),
            EqualTo("password", message="Passwords must match")
        ],
        render_kw={"class": "form-control"}
    )
    
    active = BooleanField(
        "Active User",
        default=True,
        render_kw={"class": "form-check-input"}
    )
    
    submit = SubmitField("Create User", render_kw={"class": "btn btn-primary"})


# ============================================================
# USER PROFILE FORMS
# ============================================================
class UserProfileForm(FlaskForm):
    """Edit user profile form."""
    name = StringField(
        "Full Name",
        validators=[
            InputRequired(message="Name is required"),
            Length(min=2, max=120)
        ],
        render_kw={"class": "form-control"}
    )
    
    email = StringField(
        "Email",
        validators=[
            InputRequired(message="Email is required"),
            Email(message="Invalid email"),
            Length(max=180)
        ],
        render_kw={"class": "form-control"}
    )
    
    department = SelectField(
        "Department",
        choices=DEPARTMENT_CHOICES,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    theme_pref = SelectField(
        "Theme Preference",
        choices=THEME_CHOICES,
        default="system",
        render_kw={"class": "form-select"}
    )
    
    submit = SubmitField("Update Profile", render_kw={"class": "btn btn-primary"})


# ============================================================
# SEARCH & FILTER FORMS
# ============================================================
class TicketSearchForm(FlaskForm):
    """Search and filter tickets."""
    search_query = StringField(
        "Search",
        validators=[Optional(), Length(max=100)],
        render_kw={"class": "form-control", "placeholder": "Search by ticket #, title, description..."}
    )
    
    status = SelectField(
        "Status",
        choices=[("", "All Statuses")] + TICKET_STATUS_CHOICES_ADMIN,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    priority = SelectField(
        "Priority",
        choices=[("", "All Priorities")] + PRIORITY_CHOICES,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    category = SelectField(
        "Category",
        choices=[("", "All Categories")] + CATEGORY_CHOICES,
        validators=[Optional()],
        render_kw={"class": "form-select"}
    )
    
    sort_by = SelectField(
        "Sort By",
        choices=[
            ("created_desc", "Newest First"),
            ("created_asc", "Oldest First"),
            ("due_date", "Due Date"),
            ("priority_desc", "Priority (High to Low)")
        ],
        default="created_desc",
        render_kw={"class": "form-select"}
    )
    
    submit = SubmitField("Search", render_kw={"class": "btn btn-primary"})