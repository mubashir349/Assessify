"""Phase 8 - hardening: login limits, security headers, every route checked for sign-in and institution isolation,
production settings check, request ids and clean errors when the database is down."""
import os
import re

import pytest
from sqlalchemy.exc import OperationalError

from app.common.security import production_problems
from app.config import DEFAULT_SECRET
from tests.conftest import SIGNUP, login
from tests.test_phase2 import make_admin
from tests.test_phase4 import row
from tests.test_phase6 import candidate, make_test, set_window

PUBLIC = {
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/candidate/login"),
    ("POST", "/api/v1/candidate/logout"), ("GET", "/api/v1/health"), ("GET", "/api/v1/health/db"),
    ("POST", "/api/v1/institutions/signup"), ("GET", "/api/v1/meta"),
    # Phase 10: signup email code + directory search
    ("POST", "/api/v1/auth/otp/send"), ("POST", "/api/v1/auth/otp/verify"), ("GET", "/api/v1/directory/search"),
    # Phase 11: payment page. The institution cannot sign in before paying, so these take a signed "pay now" token
    # instead of a login (tested in test_phase11.py); the webhook is called by Safepay.
    ("GET", "/api/v1/payments/plans"), ("GET", "/api/v1/payments/session"), ("POST", "/api/v1/payments/checkout"),
    ("POST", "/api/v1/payments/confirm"), ("POST", "/api/v1/payments/cancel"), ("POST", "/api/v1/payments/webhook"),
}


def api_routes(app):
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/"):
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                yield method, rule.rule


def with_ids(rule: str) -> str:
    return re.sub(r"<[^>]+>", "1", rule)


# ---------------------------------------------------------------- every route needs a sign-in
def test_every_private_route_refuses_visitors_without_a_login(client, app):
    private = [(m, r) for m, r in api_routes(app) if (m, r) not in PUBLIC]
    assert len(private) > 50
    for method, rule in private:
        r = client.open(with_ids(rule), method=method, json={})
        assert r.status_code == 401, f"{method} {rule} answered {r.status_code} without a login"


def test_a_candidate_session_opens_no_admin_route(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=6)])
    set_window(app, test_id, -10, 60)
    cand = candidate(app)
    for method, rule in api_routes(app):
        if (method, rule) in PUBLIC or rule.startswith(("/api/v1/exam", "/api/v1/candidate")):
            continue
        r = cand.open(with_ids(rule), method=method, json={})
        assert r.status_code == 401, f"{method} {rule} answered {r.status_code} to a candidate"


def test_another_institution_can_touch_nothing_of_ours(app):
    """Institution A owns object id 1 of every kind (field, question, test, candidate, attempt...).
    Institution B's admin calls every admin route with id 1: nothing may succeed."""
    a = make_admin(app)
    test_id, _ = make_test(app, a, [row(count=6)])
    set_window(app, test_id, -10, 60)
    assert candidate(app).post("/api/v1/exam/start").status_code == 200
    b = make_admin(app, "admin@other.edu.pk", "Other College")
    checked = 0
    for method, rule in api_routes(app):
        if "<" not in rule or rule.startswith(("/api/v1/exam", "/api/v1/candidate")):
            continue
        r = b.open(with_ids(rule), method=method, json={})
        assert r.status_code >= 400, f"{method} {rule} let another institution in ({r.status_code})"
        checked += 1
    assert checked > 20
    # and A still has everything
    assert a.get(f"/api/v1/tests/{test_id}").status_code == 200


# ---------------------------------------------------------------- admin login limits
def test_admin_login_is_locked_after_five_wrong_passwords(client, app):
    make_admin(app)
    for _ in range(5):
        assert login(client, "admissions@ned.edu.pk", "wrong-password-1").status_code == 401
    r = login(client, "admissions@ned.edu.pk", SIGNUP["password"])          # even the right one waits now
    assert r.status_code == 429
    assert r.get_json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert r.get_json()["error"]["details"]["retry_after"] > 0


def test_unknown_emails_count_too_and_a_good_login_clears_the_count(client, app):
    make_admin(app)
    for _ in range(5):
        assert login(client, "nobody@ned.edu.pk", "whatever-123").status_code == 401
    assert login(client, "nobody@ned.edu.pk", "whatever-123").status_code == 429
    for _ in range(4):
        login(client, "admissions@ned.edu.pk", "wrong-password-1")
    assert login(client, "admissions@ned.edu.pk", SIGNUP["password"]).status_code == 200
    for _ in range(4):                                                         # counting starts again
        assert login(client, "admissions@ned.edu.pk", "wrong-password-1").status_code == 401


def test_admin_login_limit_per_network_address(client, app):
    make_admin(app)
    app.config["ADMIN_LOGIN_MAX_FAILS_PER_IP"] = 3
    for i in range(3):
        login(client, f"guess{i}@ned.edu.pk", "whatever-123")
    assert login(client, "admissions@ned.edu.pk", SIGNUP["password"]).status_code == 429


# ---------------------------------------------------------------- headers
def test_api_answers_carry_security_headers_and_are_not_cached(client):
    r = client.get("/api/v1/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Referrer-Policy"] == "same-origin"
    assert "Strict-Transport-Security" not in r.headers                    # only on https


def test_pages_get_a_content_security_policy(client):
    r = client.get("/aptitude/institution-login.html")
    assert r.status_code == 200
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_when_the_site_runs_on_https(monkeypatch):
    from app import create_app
    from app.config import Config

    class Https(Config):
        JWT_COOKIE_SECURE = True
    r = create_app(Https).test_client().get("/api/v1/health")
    assert r.headers["Strict-Transport-Security"].startswith("max-age=")


def test_every_answer_has_a_request_id_and_a_given_one_is_kept(client):
    assert len(client.get("/api/v1/health").headers["X-Request-ID"]) == 16
    r = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    bad = client.get("/api/v1/health", headers={"X-Request-ID": "<script>"})
    assert bad.headers["X-Request-ID"] != "<script>"


# ---------------------------------------------------------------- production settings
def test_production_check_refuses_a_default_or_short_secret():
    errors, _ = production_problems({"SECRET_KEY": DEFAULT_SECRET, "SQLALCHEMY_DATABASE_URI": "mssql+pyodbc://"})
    assert errors
    errors, _ = production_problems({"SECRET_KEY": "short", "SQLALCHEMY_DATABASE_URI": "mssql+pyodbc://"})
    assert errors


def test_production_check_refuses_the_key_from_env_example():
    # security.py keeps only a fingerprint of the published key, so read the key itself from .env.example
    import re
    from app.common.security import is_published_key
    with open(os.path.join(os.path.dirname(__file__), "..", ".env.example"), encoding="utf-8") as f:
        example_secret = re.search(r"^SECRET_KEY=(\S+)", f.read(), re.M).group(1)
    assert is_published_key(example_secret)
    errors, _ = production_problems({"SECRET_KEY": example_secret, "SQLALCHEMY_DATABASE_URI": "mssql+pyodbc://"})
    assert errors


def test_production_check_passes_a_good_setup_and_warns_about_weak_options():
    good = {"SECRET_KEY": "x" * 64, "SQLALCHEMY_DATABASE_URI": "mssql+pyodbc://", "JWT_COOKIE_SECURE": True,
            "JWT_COOKIE_CSRF_PROTECT": True, "MAIL_BACKEND": "smtp"}
    assert production_problems(good) == ([], [])
    _, warnings = production_problems({**good, "JWT_COOKIE_SECURE": False, "MAIL_BACKEND": "console"})
    assert len(warnings) == 2


def test_server_will_not_start_in_production_with_the_default_secret():
    from app import create_app
    from app.config import Config

    class Prod(Config):
        ENV = "production"
        SECRET_KEY = DEFAULT_SECRET
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(Prod)


# ---------------------------------------------------------------- errors
def test_database_down_gives_503_not_a_stack_trace(app, monkeypatch):
    admin = make_admin(app)
    from app.modules.dashboard import routes

    def broken(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
    monkeypatch.setattr(routes, "_phase7_numbers", broken)
    r = admin.get("/api/v1/dashboard/summary")
    assert r.status_code == 503
    body = r.get_json()["error"]
    assert body["code"] == "DB_UNAVAILABLE"
    assert body["details"]["request_id"] == r.headers["X-Request-ID"]
    assert "connection refused" not in r.get_data(as_text=True)


def test_unexpected_error_gives_a_code_to_report(app, monkeypatch):
    admin = make_admin(app)
    from app.modules.dashboard import routes
    monkeypatch.setattr(routes, "_phase7_numbers", lambda *a: 1 / 0)
    r = admin.get("/api/v1/dashboard/summary")
    assert r.status_code == 500
    assert r.headers["X-Request-ID"] in r.get_json()["error"]["message"]
    assert "ZeroDivisionError" not in r.get_data(as_text=True)


def test_unknown_api_path_and_wrong_method_are_json(client):
    r = client.get("/api/v1/nothing-here")
    assert r.status_code == 404
    assert r.get_json()["error"]["code"] == "NOT_FOUND"
    assert client.delete("/api/v1/health").get_json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_health_db_works_on_any_database(client):
    r = client.get("/api/v1/health/db")
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "ok"
