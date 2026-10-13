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

    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException):
        return fail(e.name.upper().replace(" ", "_"), e.description or e.name, e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        app.logger.exception("Unhandled error")
        return fail("SERVER_ERROR", "Something went wrong on the server.", 500)
