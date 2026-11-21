"""Regression tests for the roster, manual-bank and downloadable-PDF enhancements."""

import pytest

from app.models.question import GenerationAttempt, Question
from app.modules.questions import service as question_service
from app.modules.reports import emails as report_emails
from tests.test_phase2 import make_admin
from tests.test_phase4 import row
from tests.test_phase6 import candidate, make_test, set_window
from tests.test_phase7 import finished, live
from tests.test_phase11 import cards


def test_manual_bank_saves_approved_questions_without_ai(app, monkeypatch):
    admin = make_admin(app)
    _, department_id = make_test(app, admin, [row(count=2)], roster=0)

    def no_ai(*_args, **_kwargs):
        pytest.fail("The manual question bank must never ask an AI provider for questions.")

    monkeypatch.setattr(question_service, "get_provider", no_ai)
    response = admin.post("/api/v1/questions/manual", json={
        "title": "Manual Mathematics Bank",
        "department_id": department_id,
        "subject": "Mathematics",
        "questions": [{
            "text": "What is the value of two plus two?",
            "question_type": "mcq",
            "options": ["Three", "Four", "Five", "Six"],
            "correct_index": 1,
            "difficulty": "easy",
            "marks": 2,
            "topic": "Arithmetic",
            "explanation": "Adding two and two gives four.",
        }],
    })

    assert response.status_code == 201, response.get_json()
    attempt_id = response.get_json()["data"]["attempt"]["id"]
    bank = GenerationAttempt.query.get(attempt_id)
    questions = Question.query.filter_by(attempt_id=attempt_id).all()
    assert bank.status == "completed"
    assert bank.source_kind == "manual" and bank.source_files == 0
    assert bank.provider is None and bank.model is None
    assert bank.bank_title == "Manual Mathematics Bank"
    assert len(questions) == 1 and questions[0].status == "approved"
    assert questions[0].correct_index == 1 and questions[0].marks == 2
    visible = admin.get(f"/api/v1/questions/bank?department_id={department_id}").get_json()["data"]["items"]
    assert any(item["id"] == questions[0].id and item["bank_title"] == "Manual Mathematics Bank" for item in visible)


def test_result_emails_attach_the_saved_student_pdf(app, finished, monkeypatch):
    admin, test_id, _ = finished
    delivered = []

    def capture(to, subject, body, attachments=None):
        delivered.append({"to": to, "subject": subject, "attachments": attachments or []})
        return "logged"

    monkeypatch.setattr(report_emails, "send_mail", capture)
    response = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["logged"] == 3
    assert len(delivered) == 3
    for message in delivered:
        assert len(message["attachments"]) == 1
        filename, payload, mimetype = message["attachments"][0]
        assert filename.endswith(".pdf") and mimetype == "application/pdf"
        assert payload.startswith(b"%PDF-")


def test_report_and_individual_result_pdfs_use_saved_results(app, finished):
    admin, test_id, _ = finished
    report = admin.get(f"/api/v1/reports/tests/{test_id}.pdf")
    assert report.status_code == 200 and report.mimetype == "application/pdf"
    assert report.data.startswith(b"%PDF-")
    assert report.headers["Cache-Control"] == "no-store"

    roster = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"]
    candidate_one = next(item for item in roster if item["roll_number"] == "R-1")
    result = admin.get(f"/api/v1/reports/tests/{test_id}/candidates/{candidate_one['id']}.pdf")
    assert result.status_code == 200 and result.mimetype == "application/pdf"
    assert result.data.startswith(b"%PDF-")

    own_session = candidate(app, 1)
    own_result = own_session.get("/api/v1/exam/result.pdf")
    assert own_result.status_code == 200 and own_result.mimetype == "application/pdf"
    assert own_result.data.startswith(b"%PDF-")

    another_admin = make_admin(app, "admin@another.edu.pk", "Another University")
    assert another_admin.get(f"/api/v1/reports/tests/{test_id}.pdf").status_code == 404
    assert another_admin.get(
        f"/api/v1/reports/tests/{test_id}/candidates/{candidate_one['id']}.pdf"
    ).status_code == 404


def test_candidate_result_pdf_obeys_scheduled_release(app, finished):
    from app.extensions import db
    from app.models.aptitude_test import AptitudeTest

    admin, test_id, _ = finished
    test = db.session.get(AptitudeTest, test_id)
    test.schedule.result_release = "scheduled"
    test.schedule.release_on = test.schedule.starts_at.date()
    db.session.commit()

    student = candidate(app, 1)
    response = student.get("/api/v1/exam/result.pdf")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "RESULT_NOT_RELEASED"


def test_inactive_and_pending_students_cannot_download_admit_cards(app, cards):
    admin, test_id, department_id, _ = cards
    roster = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"]

    def update_status(person, status):
        payload = {
            "full_name": person["full_name"],
            "email": person["email"],
            "phone": person.get("phone"),
            "roll_number": person["roll_number"],
            "date_of_birth": person["date_of_birth"],
            "department_id": department_id,
            "status": status,
        }
        return admin.put(f"/api/v1/roster/{person['id']}", json=payload)

    inactive = roster[0]
    pending = roster[1]
    assert update_status(inactive, "Inactive").status_code == 200
    assert update_status(pending, "Pending").status_code == 200
    for person in (inactive, pending):
        response = admin.get(f"/api/v1/admit-cards/{person['id']}.pdf")
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "ADMIT_CARD_NOT_ELIGIBLE"

    # Eligibility is checked against the current saved status, so reactivation restores access.
    assert update_status(inactive, "Active").status_code == 200
    restored = admin.get(f"/api/v1/admit-cards/{inactive['id']}.pdf")
    assert restored.status_code == 200 and restored.data.startswith(b"%PDF-")


def _set_status(admin, person, status, department_id=None):
    return admin.put(f"/api/v1/roster/{person['id']}", json={
        "full_name": person["full_name"], "email": person["email"], "phone": person.get("phone"),
        "roll_number": person["roll_number"], "date_of_birth": person["date_of_birth"],
        "department_id": department_id or person["department"]["id"], "status": status})


def test_no_admit_card_email_goes_to_inactive_or_pending_students(app, cards):
    admin, test_id, department_id, batch = cards
    people = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"]
    assert _set_status(admin, people[0], "Inactive", department_id).status_code == 200
    assert _set_status(admin, people[1], "Pending", department_id).status_code == 200

    sent = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id}).get_json()["data"]
    assert len(sent["sent"]) == 2 and len(batch.sent) == 2
    assert {m["to"] for m in batch.sent}.isdisjoint({people[0]["email"], people[1]["email"]})
    # asking for them by name is refused as well
    refused = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id, "candidate_ids": [people[0]["id"]],
                                                          "resend": True})
    assert refused.status_code == 403 and len(batch.sent) == 2


def test_result_emails_skip_inactive_students(app, finished, monkeypatch):
    admin, test_id, _ = finished
    delivered = []
    monkeypatch.setattr(report_emails, "send_mail",
                        lambda to, subject, body, attachments=None: delivered.append(to) or "logged")
    items = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"]
    person = next(i for i in items if i["attempt"] and i["attempt"]["status"] == "submitted")
    assert _set_status(admin, person, "Inactive").status_code == 200

    response = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={})
    assert response.status_code == 200, response.get_json()
    assert person["email"] not in delivered and len(delivered) == 2
