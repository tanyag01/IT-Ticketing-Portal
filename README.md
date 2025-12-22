# IT Ticketing Portal (Cleaned)

This archive is a cleaned, runnable copy of the **IT Ticketing Portal** project.
I removed bundled virtual environments and temporary __pycache__ files to keep the package lightweight.

## What's included
- backend/ : Flask application (app.py, templates, static, models, etc.)
- requirements.txt : Python dependencies for the backend

## To run locally (recommended)
1. Create a Python virtual environment (Python 3.11+ recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .venv\Scripts\activate    # Windows PowerShell
   ```

2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. Set environment variables (optional) or edit `config.py`:
   - `FLASK_APP=app.py`
   - `FLASK_ENV=development`

4. Initialize database (if needed):
   ```bash
   python backend/db_init.py
   ```

5. Run:
   ```bash
   cd backend
   flask run
   ```

## UI tweaks
- Header now has a blue gradient and improved card shadows.
- Added a small favicon.
- Minor responsive improvements for sidebar.

## Notes / Limitations
- I removed the `venv` and `.venv` folders that were bundled; please recreate one locally as shown above.
- I made modest UI updates (style.css + layout.html + favicon). I did NOT change major app logic or add new features beyond visual polish.
- If you'd like specific feature changes (export formats, auth, APIs, or exact UI mockups) tell me and I will modify files accordingly.

