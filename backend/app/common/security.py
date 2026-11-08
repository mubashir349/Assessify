"""Phase 8: security headers, a request id on every response, and the production settings check.

Headers (every response):
    X-Content-Type-Options: nosniff        the browser never guesses a file type (a CSV is never run as a page)
    X-Frame-Options: DENY + CSP frame-ancestors 'none'   no other site can put our pages in a frame (clickjacking)
    Referrer-Policy: same-origin           links to other sites don't carry our URLs
    Permissions-Policy                     no camera, microphone or location for any page
    Content-Security-Policy (pages)        scripts / styles / data only from our own site (+ Google Fonts)
    Strict-Transport-Security             only when the site runs on https (JWT_COOKIE_SECURE=true)
    Cache-Control: no-store (API)          answers with personal data are never kept in a browser or proxy cache
"""
import logging
import uuid

from flask import Flask, g, request

from app.config import DEFAULT_SECRET

log = logging.getLogger(__name__)

# the key printed in .env.example: everyone who copied the file has it, so it is as public as the default
EXAMPLE_SECRET = "4c15c34134bb502754680ef5ad60997c58af3966006bb199c8e9087c8e69d01a"  # NOSONAR - a known-bad value

_PAGE_CSP = ("default-src 'self'; "
             "script-src 'self' 'unsafe-inline'; "            # the pages still have small inline scripts
             "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
             "font-src 'self' https://fonts.gstatic.com data:; "
             "img-src 'self' data:; "
             "connect-src 'self'{api}; "
             "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def _api_origin(app: Flask) -> str:
    """A separate API host (ASSESSIFY_API_URL / FRONTEND_URL setups) must be allowed for fetch()."""
    return app.config.get("API_ORIGIN", "")


def install(app: Flask) -> None:
    api = _api_origin(app)
    csp = _PAGE_CSP.format(api=" " + api if api else "")
    hsts = bool(app.config.get("JWT_COOKIE_SECURE"))

    @app.before_request
    def _request_id():
        incoming = request.headers.get("X-Request-ID", "")
        g.request_id = incoming[:64] if incoming.replace("-", "").isalnum() else uuid.uuid4().hex[:16]

    @app.after_request
    def _headers(response):
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h["X-Request-ID"] = g.get("request_id", "")
        if request.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        else:
            h.setdefault("Content-Security-Policy", csp)
        if hsts:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def production_problems(config) -> tuple[list[str], list[str]]:
    """(errors that stop the server, warnings) for FLASK_ENV=production."""
    errors, warnings = [], []
    secret = config.get("SECRET_KEY") or ""
    if secret in (DEFAULT_SECRET, EXAMPLE_SECRET) or len(secret) < 32:
        errors.append("Set SECRET_KEY in .env to a long random value (at least 32 characters). "
                      "Make one with:  python -c \"import secrets; print(secrets.token_hex(32))\"")
    if config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        warnings.append("DATABASE_URL points at SQLite: fine for a demo, use SQL Server for real exams.")
    if not config.get("JWT_COOKIE_SECURE"):
        warnings.append("JWT_COOKIE_SECURE is off: set it to true when the site runs on https.")
    if not config.get("JWT_COOKIE_CSRF_PROTECT"):
        warnings.append("JWT_COOKIE_CSRF is off: set it to true in production (the pages already send the token).")
    if config.get("MAIL_BACKEND") == "console":
        warnings.append("MAIL_BACKEND=console: result emails are only written to the log, not sent.")
    return errors, warnings


def check_production(app: Flask) -> None:
    if app.config["ENV"] != "production":
        return
    errors, warnings = production_problems(app.config)
    for w in warnings:
        log.warning("PRODUCTION CHECK: %s", w)
    if errors:
        raise RuntimeError("Not safe to run in production:\n- " + "\n- ".join(errors))
