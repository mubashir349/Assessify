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
        sa = User(full_name="Root", email="root@assessai.com", role=ROLE_SUPER_ADMIN)
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
    "admin_phone": "0300 1234567", "admin_designation": "Registrar", "password": "Strong#Pass1",
}


def login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})
