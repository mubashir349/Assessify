"""Application factory: builds the Flask app and plugs in every module."""
from flask import Flask

from app.common.errors import register_error_handlers
from app.common.responses import fail
from app.config import DEFAULT_SECRET, Config
from app.extensions import cors, db, jwt, migrate


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    if app.config["ENV"] == "production" and app.config["SECRET_KEY"] == DEFAULT_SECRET:
        raise RuntimeError("Set a real SECRET_KEY in .env before running in production.")

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
    _register_jwt_errors()

    # ---- One line per module. Later phases add more here ----
    from app.modules.auth.routes import bp as auth_bp
    from app.modules.dashboard.routes import bp as dashboard_bp
    from app.modules.departments.routes import bp as departments_bp
    from app.modules.health.routes import bp as health_bp
    from app.modules.institutions.routes import bp as institutions_bp
    from app.modules.meta.routes import bp as meta_bp
    from app.modules.super_admin.routes import bp as super_bp

    app.register_blueprint(health_bp, url_prefix="/api/v1/health")
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(institutions_bp, url_prefix="/api/v1/institutions")
    app.register_blueprint(super_bp, url_prefix="/api/v1/super")
    app.register_blueprint(departments_bp, url_prefix="/api/v1/departments")
    app.register_blueprint(dashboard_bp, url_prefix="/api/v1/dashboard")
    app.register_blueprint(meta_bp, url_prefix="/api/v1/meta")

    _serve_frontend(app)

    return app

def _serve_frontend(app: Flask) -> None:
    """Serve the ../frontend folder so one command (python run.py) runs the whole project."""
    import os

    from flask import abort, send_from_directory

    frontend_dir = os.path.abspath(os.path.join(app.root_path, "..", "..", "frontend"))
    if not os.path.isdir(frontend_dir):
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
