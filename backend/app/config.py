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

    # ---- Phase 3: PDF upload + AI question generation ----
    # Flask rejects any request body bigger than this with HTTP 413 (we turn that into FILE_TOO_LARGE).
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))          # total for all PDFs in one request
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    PDF_MAX_PAGES = int(os.getenv("PDF_MAX_PAGES", "300"))          # pages read from one PDF
    PDF_MIN_TEXT_CHARS = int(os.getenv("PDF_MIN_TEXT_CHARS", "300"))  # less text than this -> "no usable text"
    MAX_PDFS_PER_GENERATION = int(os.getenv("MAX_PDFS_PER_GENERATION", "10"))
    SOURCE_MAX_CHARS = int(os.getenv("SOURCE_MAX_CHARS", "300000"))   # text kept from all PDFs together (~120 typed pages)
    AI_MAX_SOURCE_CHARS = int(os.getenv("AI_MAX_SOURCE_CHARS", "12000"))  # one part of it, sent per AI request
    AI_MAX_REQUESTS_PER_GENERATION = int(os.getenv("AI_MAX_REQUESTS_PER_GENERATION", "10"))  # parts used per attempt
    DESCRIPTION_MIN_WORDS = int(os.getenv("DESCRIPTION_MIN_WORDS", "8"))  # no PDF -> description must say this much

    # Which AI service writes the drafts. One of: gemini | groq | ollama | none   (see README "Phase 3")
    AI_PROVIDER = os.getenv("AI_PROVIDER", "none").strip().lower()
    AI_MODEL = os.getenv("AI_MODEL", "").strip()          # empty -> the provider's default model
    AI_BASE_URL = os.getenv("AI_BASE_URL", "").strip()    # empty -> the provider's default URL
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "90"))
    AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "2"))      # extra tries after the first one (bounded)

    # ---- Phase 7: result emails ----
    # console = nothing is sent, each email is written to the server log (local testing). smtp = really send.
    MAIL_BACKEND = os.getenv("MAIL_BACKEND", "console").strip().lower()
    MAIL_SERVER = os.getenv("MAIL_SERVER", "").strip()          # e.g. smtp.gmail.com
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = _flag("MAIL_USE_TLS", "true")                # STARTTLS on port 587
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "").strip()              # empty -> MAIL_USERNAME
    MAIL_TIMEOUT_SECONDS = int(os.getenv("MAIL_TIMEOUT_SECONDS", "20"))
    # Phase 7: an in-progress candidate whose page has not called the server for this long shows as "Disconnected"
    MONITOR_DISCONNECTED_SECONDS = int(os.getenv("MONITOR_DISCONNECTED_SECONDS", "75"))
    AI_BATCH_SIZE = int(os.getenv("AI_BATCH_SIZE", "10"))       # questions asked for in one AI request
    AI_MAX_OUTPUT_TOKENS = os.getenv("AI_MAX_OUTPUT_TOKENS", "").strip()  # empty -> provider default
    MAX_QUESTIONS_PER_ATTEMPT = int(os.getenv("MAX_QUESTIONS_PER_ATTEMPT", "100"))
    # PDFs made of photos / scans: the AI (Gemini) reads the page pictures. Limits keep free-quota use small.
    OCR_MAX_PAGES = int(os.getenv("OCR_MAX_PAGES", "60"))                  # pictures read from one PDF
    OCR_PAGES_PER_REQUEST = int(os.getenv("OCR_PAGES_PER_REQUEST", "4"))   # pictures sent in one AI request
    OCR_IMAGE_MAX_SIDE = int(os.getenv("OCR_IMAGE_MAX_SIDE", "1600"))      # pixels; bigger photos are shrunk

    # ---- Phase 5: candidate sign-in (access code + date of birth) ----
    CANDIDATE_SESSION_HOURS = int(os.getenv("CANDIDATE_SESSION_HOURS", "12"))       # never longer than test end + 1 h
    CANDIDATE_LOGIN_MAX_FAILS = int(os.getenv("CANDIDATE_LOGIN_MAX_FAILS", "5"))      # wrong tries per access code
    CANDIDATE_LOGIN_MAX_FAILS_PER_IP = int(os.getenv("CANDIDATE_LOGIN_MAX_FAILS_PER_IP", "50"))  # exam halls share an IP
    CANDIDATE_LOGIN_WINDOW_SECONDS = int(os.getenv("CANDIDATE_LOGIN_WINDOW_SECONDS", "900"))  # ...within 15 minutes
