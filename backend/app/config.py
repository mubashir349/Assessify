"""Reads settings from the .env file. Every other module imports Config from here."""
import os
from datetime import timedelta
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


def build_database_uri() -> str:
    """SQL Server connection string from .env. DATABASE_URL (if set) wins - used by tests."""
    override = os.getenv("DATABASE_URL")
    if override:
        return override

    driver = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    server = os.getenv("DB_SERVER", "localhost")
    name = os.getenv("DB_NAME", "AssessifyDB")
    trusted = os.getenv("DB_TRUSTED", "yes").lower() == "yes"

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={name}",
        "TrustServerCertificate=yes",  # fine for local/dev servers
    ]
    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={os.getenv('DB_USER', '')}")
        parts.append(f"PWD={os.getenv('DB_PASSWORD', '')}")

    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(";".join(parts))


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


DEFAULT_SECRET = "dev-only-secret-change-me-in-your-env-file-0000"


class Config:
    ENV = os.getenv("FLASK_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET)
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5500")
    SQLALCHEMY_DATABASE_URI = build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False

    # ---- Login token: stored in an httpOnly cookie (JavaScript can never read it) ----
    JWT_SECRET_KEY = SECRET_KEY
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_HOURS", "8")))
    JWT_COOKIE_SECURE = _flag("JWT_COOKIE_SECURE")        # set true when the site is on https
    JWT_COOKIE_SAMESITE = "Lax"
    # CSRF double-submit is off for local dev (frontend + API share a host). Turn ON in production.
    JWT_COOKIE_CSRF_PROTECT = _flag("JWT_COOKIE_CSRF")
