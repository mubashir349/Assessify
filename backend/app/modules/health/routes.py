"""GET /api/v1/health          -> is the API alive?
GET /api/v1/health/db       -> can the API reach SQL Server?
"""
from flask import Blueprint
from sqlalchemy import text

from app.common.responses import fail, ok
from app.extensions import db

bp = Blueprint("health", __name__)


@bp.get("")
def health():
    return ok({"status": "ok", "service": "assessify-api"})


@bp.get("/db")
def health_db():
    try:
        version = db.session.execute(text("SELECT @@VERSION")).scalar()
        name = db.session.execute(text("SELECT DB_NAME()")).scalar()
    except Exception as exc:  # connection problems end up here
        return fail("DB_UNREACHABLE", f"Cannot reach SQL Server: {exc.__class__.__name__}", 503)
    return ok({"status": "ok", "database": name, "server": str(version).splitlines()[0]})
