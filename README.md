🎫 IT Ticketing Portal

A full-stack IT Ticketing Management System built with Flask to streamline internal IT support operations within an organization.

The system enables employees to raise IT support tickets, track progress, and communicate with IT teams, while administrators can manage users, tickets, priorities, and reports from a centralized dashboard.

🚀 Features
### 👤 User Features
- Secure user registration & login
- Raise IT support tickets
- Track ticket status (Open / In Progress / Resolved)
- Upload attachments (PDFs, images)
- View ticket history and updates

### 🛠️ Admin Features
- Admin dashboard with ticket statistics
- View and manage all tickets
- Update ticket status and priority
- Manage users and roles
- Generate reports (CSV)
- Role-based access control
  
## 🧰 Tech Stack

| Layer | Technology |
|------|-----------|
| Backend | Python, Flask |
| Database | SQLite (upgradeable to PostgreSQL / MySQL) |
| ORM | SQLAlchemy |
| Frontend | HTML, CSS, Bootstrap |
| Authentication | Flask-Login |
| Migrations | Flask-Migrate |
| Deployment | Gunicorn + Cloudflare |
| Version Control | Git & GitHub |

📂 Project Structure
IT-Ticketing-Portal/
│

├── backend/

│   ├── app.py

│   ├── config.py

│   ├── models.py

│   ├── forms.py

│   ├── utils.py

│   ├── tasks.py

│   ├── db_init.py

│   ├── requirements.txt

│   ├── migrations/

│   ├── templates/

│   └── static/
│
├── .gitignore

└── README.md

⚙️ Local Installation & Setup
1️⃣ Clone the repository
git clone https://github.com/tanyag01/IT-Ticketing-Portal.git
cd IT-Ticketing-Portal

2️⃣ Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows PowerShell
# source .venv/bin/activate   # macOS/Linux

3️⃣ Install dependencies
pip install -r backend/requirements.txt

4️⃣ Initialize the database (first time only)
python backend/db_init.py

5️⃣ Run the application
cd backend
flask run


Access the application at:
👉 http://127.0.0.1:5000

🎨 UI Enhancements
Clean blue gradient header
Improved card shadows and spacing
Responsive sidebar layout
Added favicon
Minor UI polish (no core logic changes)

🔐 Security Notes
Sensitive files (.env, database files, uploads) are excluded via .gitignore
Passwords are securely hashed
Role-based authorization enforced across the app
Production deployment should use a WSGI server (Gunicorn)
⚠️ Do not use the Flask development server in production.


🚧 Notes & Limitations
Virtual environments (venv, .venv) are intentionally excluded from the repository
SQLite is used for development; production should use PostgreSQL or MySQL
This version focuses on stability and clarity rather than feature expansion

🌱 Future Enhancements
Email notifications
SLA & priority automation
Ticket assignment to engineers
API support
Analytics dashboard

👩‍💻 Author
Tanya Gupta
IT Ticketing Portal — Full-Stack Flask Project

