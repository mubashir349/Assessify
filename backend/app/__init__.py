"""Application factory: builds the Flask app and plugs in every module."""
from flask import Flask

from app.common import security
from app.common.errors import register_error_handlers
from app.common.responses import fail
from app.config import Config
from app.extensions import cors, db, jwt, migrate


def create_app(config_class=Config) -> Flask:
    # CSRF reviewed: the login cookies are SameSite=Lax (not sent on cross-site POST/PUT/DELETE), the API only reads
    # JSON bodies (a cross-site form can't send application/json without a CORS preflight) and CORS allows only our
    # own frontend origins. For production, also set JWT_COOKIE_CSRF=true: api.js then sends the X-CSRF-TOKEN header.
    app = Flask(__name__)  # NOSONAR
    app.config.from_object(config_class)

    security.check_production(app)          # Phase 8: refuses a default SECRET_KEY, warns about weak settings
    if app.config.get("TRUST_PROXY_HOPS"):
        # behind Azure / nginx / a tunnel: take the visitor's address from X-Forwarded-For (login limits per IP)
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = app.config["TRUST_PROXY_HOPS"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": [app.config["FRONTEND_URL"], "http://localhost:5500", "http://127.0.0.1:5500"]}},
        supports_credentials=True,
    )

    from app import models  # noqa: F401  (registers tables with Flask-Migrate)

    register_error_handlers(app)
    security.install(app)
    _register_jwt_errors()

    # ---- One line per module. Later phases add more here ----
    from app.modules.admit_cards.routes import bp as admit_cards_bp
    from app.modules.aptitude_tests.routes import bp as tests_bp
    from app.modules.auth.routes import bp as auth_bp
    from app.modules.candidate_auth.routes import bp as candidate_bp
    from app.modules.dashboard.routes import bp as dashboard_bp
    from app.modules.departments.routes import bp as departments_bp
    from app.modules.directory.routes import bp as directory_bp
    from app.modules.email_otp.routes import bp as otp_bp
    from app.modules.exam.routes import admin_bp as exam_admin_bp
    from app.modules.exam.routes import bp as exam_bp
    from app.modules.health.routes import bp as health_bp
    from app.modules.institutions.routes import bp as institutions_bp
    from app.modules.meta.routes import bp as meta_bp
    from app.modules.monitor.routes import bp as monitor_bp
    from app.modules.payments.routes import bp as payments_bp
    from app.modules.questions.routes import bp as questions_bp
    from app.modules.reports.routes import bp as reports_bp
    from app.modules.roster.routes import bp as roster_bp
    from app.modules.super_admin.routes import bp as super_bp

    app.register_blueprint(health_bp, url_prefix="/api/v1/health")
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(otp_bp, url_prefix="/api/v1/auth/otp")
    app.register_blueprint(directory_bp, url_prefix="/api/v1/directory")
    app.register_blueprint(institutions_bp, url_prefix="/api/v1/institutions")
    app.register_blueprint(super_bp, url_prefix="/api/v1/super")
    app.register_blueprint(departments_bp, url_prefix="/api/v1/departments")
    app.register_blueprint(dashboard_bp, url_prefix="/api/v1/dashboard")
    app.register_blueprint(meta_bp, url_prefix="/api/v1/meta")
    app.register_blueprint(questions_bp, url_prefix="/api/v1/questions")
    app.register_blueprint(tests_bp, url_prefix="/api/v1/tests")
    app.register_blueprint(roster_bp, url_prefix="/api/v1/roster")
    app.register_blueprint(candidate_bp, url_prefix="/api/v1/candidate")
    app.register_blueprint(exam_bp, url_prefix="/api/v1/exam")
    app.register_blueprint(exam_admin_bp, url_prefix="/api/v1/attempts")
    app.register_blueprint(monitor_bp, url_prefix="/api/v1/monitor")
    app.register_blueprint(reports_bp, url_prefix="/api/v1/reports")
    app.register_blueprint(admit_cards_bp, url_prefix="/api/v1/admit-cards")     # Phase 11
    app.register_blueprint(payments_bp, url_prefix="/api/v1/payments")           # Phase 11

    from app.modules.candidate_auth.service import reset_limits
    reset_limits()          # wrong-attempt counters start empty for every new app (and every test)

    _serve_frontend(app)

    return app

def _serve_frontend(app: Flask) -> None:
    """Serve the ../frontend folder so one command (python run.py) runs the whole project."""
    import os

    from flask import abort, send_from_directory

    # repo layout: backend/app + frontend/. Azure zip layout (deploy/make_azure_zip.py): app/ + frontend/ side by side.
    candidates = [os.environ.get("FRONTEND_DIR", ""), os.path.join(app.root_path, "..", "..", "frontend"),
                  os.path.join(app.root_path, "..", "frontend")]
    frontend_dir = next((os.path.abspath(d) for d in candidates if d and os.path.isdir(d)), None)
    if frontend_dir is None:
        return

    @app.get("/")
    def _site_index():
        return send_from_directory(frontend_dir, "index.html")

    @app.get("/<path:path>")
    def _site_file(path):
        if path.startswith("api/"):
            abort(404)
        return send_from_directory(frontend_dir, path)


def _register_jwt_errors() -> None:
    """Missing / bad / expired login cookie -> our normal JSON error with HTTP 401."""

    @jwt.unauthorized_loader
    def _missing(reason):
        return fail("UNAUTHORIZED", "Please sign in.", 401)

    @jwt.invalid_token_loader
    def _invalid(reason):
        return fail("UNAUTHORIZED", "Please sign in again.", 401)

    @jwt.expired_token_loader
    def _expired(header, payload):
        return fail("SESSION_EXPIRED", "Your session expired. Please sign in again.", 401)
