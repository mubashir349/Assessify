"""Tests run against an in-memory SQLite database, so no SQL Server is needed to run them.

Phase 8: TEST_DATABASE_URL runs the same tests on a real (EMPTY, throw-away) database, e.g. SQL Server:
    TEST_DATABASE_URL="mssql+pyodbc://sa:<password>@localhost/AssessifyTest?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
Every test creates and drops all tables, so never point it at a database with real data."""
import os

os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or "sqlite://"   # must be set BEFORE app.config is imported

import pytest

from app import create_app
from app.extensions import db
from app.models.user import ROLE_SUPER_ADMIN, User


@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        sa = User(full_name="Root", email="root@assessify.com", role=ROLE_SUPER_ADMIN)
        sa.set_password("SuperSecret123")
        db.session.add(sa)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


SIGNUP = {
    "institution_name": "NED University", "institution_type": "University", "city": "Karachi, Pakistan",
    "website": "https://www.neduet.edu.pk", "admin_name": "Dr. Ayesha Khan", "admin_email": "Admissions@NED.edu.pk",
    "password": "Strong#Pass1",
}

SENT_MAIL: list[dict] = []      # every email the app "sent" during the current test (see the autouse fixture)
_TOKENS: dict[str, str] = {}    # email -> its verified token in this test (the page also keeps it after a failed submit)


@pytest.fixture(autouse=True)
def _capture_mail_and_dns(monkeypatch):
    """Phase 10: emails (signup codes) are captured instead of logged, and the DNS mail-server lookup says yes,
    so tests need no network. Tests that check the lookup patch email_rules.accepts_mail themselves."""
    from app.common import email_rules
    from app.modules.email_otp import service as otp_service

    SENT_MAIL.clear()
    _TOKENS.clear()

    def fake_send(to, subject, body):
        SENT_MAIL.append({"to": to, "subject": subject, "body": body})
        return "logged"

    monkeypatch.setattr(otp_service, "send_mail", fake_send)
    monkeypatch.setattr(email_rules, "accepts_mail", lambda domain: True)   # monkeypatch undoes both after the test


def last_code(email: str) -> str:
    import re
    mail = next(m for m in reversed(SENT_MAIL) if m["to"] == email.lower())
    return re.search(r"code is (\d{6})", mail["body"]).group(1)


def email_token(client, email: str) -> str | None:
    """Send + verify a signup code for this email. None when the email can't get one (invalid / taken)."""
    if email.lower() in _TOKENS:
        return _TOKENS[email.lower()]
    if client.post("/api/v1/auth/otp/send", json={"email": email}).status_code != 200:
        return None
    r = client.post("/api/v1/auth/otp/verify", json={"email": email, "code": last_code(email)})
    if r.status_code != 200:
        return None
    _TOKENS[email.lower()] = r.get_json()["data"]["email_token"]
    return _TOKENS[email.lower()]


def do_signup(client, **over):
    """Institution signup the way the page does it: verify the email first, then submit."""
    body = {**SIGNUP, **over}
    if "email_token" not in over:
        body["email_token"] = email_token(client, body.get("admin_email") or "")
    return client.post("/api/v1/institutions/signup", json=body)


def login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})
