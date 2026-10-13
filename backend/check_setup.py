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
except Exception as exc:
    print("SQL Server:  FAILED ->", str(exc).splitlines()[0][:200])
    print("  Common fixes: create the database in SSMS first, check DB_SERVER name, start the SQL Server service.")
    sys.exit(1)

print("\nAll good. Now run:  python run.py   and open http://127.0.0.1:5000/api/v1/health/db")
