"""Global error handlers so every failure comes back in the same JSON shape."""
from flask import Flask
from werkzeug.exceptions import HTTPException

from app.common.responses import fail


class ApiError(Exception):
    """Raise anywhere in a service: raise ApiError("POOL_TOO_SMALL", "Not enough questions", 409)"""

    def __init__(self, code: str, message: str, status: int = 400, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return fail(e.code, e.message, e.status, e.details)

    @app.errorhandler(413)
    def handle_too_large(e):
        mb = app.config.get("MAX_UPLOAD_MB", 10)
        return fail("FILE_TOO_LARGE", f"The file is too large. The maximum upload size is {mb} MB.", 413,
                    {"file": f"Maximum size is {mb} MB."})

    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException):
        return fail(e.name.upper().replace(" ", "_"), e.description or e.name, e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        if _schema_out_of_date(e):
            app.logger.error("DATABASE IS OUT OF DATE (%s). Stop the server and run:  flask --app run db upgrade",
                             str(getattr(e, "orig", e)).splitlines()[0][:200])
            _rollback()
            return fail("DB_NOT_UPGRADED", "The database is out of date for this version of the app. Stop the server, run "
                        "'flask --app run db upgrade' in backend/, then start it again.", 500)
        app.logger.exception("Unhandled error")
        _rollback()
        return fail("SERVER_ERROR", "Something went wrong on the server.", 500)


# Messages SQL Server / SQLite give when the code expects a table or column the database does not have yet
_MISSING_SCHEMA = ("invalid column name", "invalid object name", "no such column", "no such table")


def _schema_out_of_date(e: Exception) -> bool:
    from sqlalchemy.exc import DBAPIError
    return isinstance(e, DBAPIError) and any(m in str(e.orig).lower() for m in _MISSING_SCHEMA)


def _rollback() -> None:
    try:
        from app.extensions import db
        db.session.rollback()
    except Exception:  # noqa: BLE001
        pass
