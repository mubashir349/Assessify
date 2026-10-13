# Assessify Backend (Flask + SQL Server)

## Phase 0 checklist — every teammate does this on their own PC

### 1. Install once
- **Python 3.10+** (tick "Add python.exe to PATH" in the installer)
- **SQL Server Express** (or Developer) + **SSMS**
- **ODBC Driver 18 for SQL Server** (Microsoft download)

### 2. Create your own database (in SSMS)
Connect to your server, then run:
```sql
CREATE DATABASE AssessifyDB;
```

### 3. Set up the project (PowerShell, inside `backend/`)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
If PowerShell blocks the activate script, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4. Edit `.env`
- `DB_SERVER` — the server name shown in SSMS's connect box (e.g. `localhost\SQLEXPRESS` or `.\SQLEXPRESS`)
- Windows login: keep `DB_TRUSTED=yes`
- SQL login: set `DB_TRUSTED=no` and fill `DB_USER` / `DB_PASSWORD`

### 5. Check everything
```powershell
python check_setup.py
```
It prints exactly what is missing (driver, `.env`, database, connection).

### 6. Run the API
```powershell
python run.py
```
Open in a browser:
- http://127.0.0.1:5000/api/v1/health → `{"data": {"status": "ok", ...}}`
- http://127.0.0.1:5000/api/v1/health/db → shows your SQL Server version

**Phase 0 is done when all four of you see the second URL succeed.**

## Common problems
| Message | Fix |
|---|---|
| `Data source name not found` | ODBC Driver 18 not installed, or `DB_DRIVER` name differs. `check_setup.py` lists installed drivers. |
| `Login failed` | Wrong SQL login, or use `DB_TRUSTED=yes` |
| `Cannot open database "AssessifyDB"` | Create it in SSMS (step 2) |
| `Named Pipes / server not found` | Wrong `DB_SERVER`, or SQL Server service is stopped (open *SQL Server Configuration Manager*) |
| Certificate error | Already handled by `TrustServerCertificate=yes` for local dev |

## Phase 1 — accounts, login, institution approval

### One-time setup after pulling Phase 1
```powershell
pip install -r requirements.txt        # new: Flask-JWT-Extended
flask --app run db upgrade             # creates the tables in YOUR AssessifyDB
python seed.py                         # creates the Super Admin (asks for a password, min 10 chars)
python run.py
```
Check in SSMS: Databases → AssessifyDB → Tables → `institutions`, `users`, `alembic_version`.

Set a long random `SECRET_KEY` in `.env` (generate one: `python -c "import secrets; print(secrets.token_hex(32))"`).

### Run the tests (no SQL Server needed — they use an in-memory database)
```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

### Try it with the frontend
1. Open the `frontend` folder with VS Code **Live Server** (port 5500) and open `aptitude/institution-login.html` via `http://127.0.0.1:5500/...`
2. Use `127.0.0.1` for BOTH the site and the API (don't mix with `localhost`) — the login cookie only travels between the same host.
3. Register an institution -> sign in as the Super Admin (the email you seeded) -> approve it -> sign in as the institution.

### Changing tables later (the team rule)
Edit the model -> ONE person runs `flask --app run db migrate -m "what changed"` -> commit the new file in `migrations/versions/` -> everyone else runs `flask --app run db upgrade`. Never edit tables by hand in SSMS.

Full route list and error codes: `docs/API.md`

## Folder layout
```
backend/
  run.py                 start the server
  check_setup.py         setup diagnostics
  app/
    __init__.py          create_app(): registers every module
    config.py            reads .env
    extensions.py        db, migrate, cors
    common/              responses.py (JSON shape), errors.py (ApiError)
    models/              database tables (institution.py, user.py)
    modules/
      health/            routes.py  <- pattern every future module follows
      auth/              login, logout, me
      institutions/      public signup
      super_admin/       list / approve / reject / suspend institutions
  migrations/            database versions (Alembic)
  seed.py                creates the Super Admin
  tests/                 pytest suite
  docs/API.md            the API contract
```

## Rules for the team
- `.env` is never committed. `.env.example` is.
- Responses always go through `ok()` / `fail()` / `raise ApiError(...)`.
- New module = new folder in `app/modules/` with `routes.py` (HTTP only) and `service.py` (rules), then one `register_blueprint` line in `app/__init__.py`.
- Tables are changed only through migrations (`flask db migrate`, `flask db upgrade`) — never by hand in SSMS.
