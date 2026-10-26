"""Run this FIRST on every teammate's PC:  python check_setup.py
It tells you exactly which part of the setup is missing."""
import os
import sys

print(f"Python:      {sys.version.split()[0]}", "OK" if sys.version_info >= (3, 10) else "-> need 3.10 or newer")

try:
    import pyodbc
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    print("ODBC drivers:", drivers or "NONE FOUND -> install 'ODBC Driver 18 for SQL Server'")
except ImportError:
    print("pyodbc:      NOT INSTALLED -> run: pip install -r requirements.txt")
    sys.exit(1)

if not os.path.exists(".env"):
    print(".env:        MISSING -> copy .env.example to .env and edit it")
    sys.exit(1)
print(".env:        found")

from sqlalchemy import create_engine, text
from app.config import build_database_uri

try:
    with create_engine(build_database_uri()).connect() as conn:
        print("SQL Server:  CONNECTED to", conn.execute(text("SELECT DB_NAME()")).scalar())
        # Are all migrations applied? (new code + old tables = "Something went wrong" on every page)
        from alembic.script import ScriptDirectory
        head = ScriptDirectory("migrations").get_current_head()
        try:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001
            current = None
        if current == head:
            print("Migrations:  up to date (" + head + ")")
        else:
            print(f"Migrations:  OUT OF DATE (database: {current or 'none'}, code: {head})"
                  " -> run: flask --app run db upgrade")
except Exception as exc:
    print("SQL Server:  FAILED ->", str(exc).splitlines()[0][:200])
    print("  Common fixes: create the database in SSMS first, check DB_SERVER name, start the SQL Server service.")
    sys.exit(1)

# ---- Phase 3: is AI question generation configured? (no network call, the key is never printed) ----
try:
    import pypdf  # noqa: F401
    print("pypdf:       installed")
except ImportError:
    print("pypdf:       NOT INSTALLED -> run: pip install -r requirements.txt")
try:
    import PIL  # noqa: F401
    print("Pillow:      installed (photo / scanned PDF pages can be read)")
except ImportError:
    print("Pillow:      NOT INSTALLED -> run: pip install -r requirements.txt   (needed for photo / scanned PDFs)")
from app.ai import provider_status
from app.config import Config
ai = provider_status({k: getattr(Config, k) for k in dir(Config) if k.isupper()})
if ai["configured"]:
    print(f"AI:          {ai['provider']} / {ai['model']}  (test it with: python check_ai.py)")
else:
    print("AI:          NOT CONFIGURED ->", ai["message"], "(the rest of the app still works)")

print("\nAll good. Now run:  python run.py   and open http://127.0.0.1:5000/api/v1/health/db")
