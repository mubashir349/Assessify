"""Phase 7 - live monitor (statuses, unlock, end), reports (numbers, filters, CSV), result emails and AI insights."""
import secrets
import smtplib
from datetime import timedelta

import pytest

from app.ai import AIError
from app.common.utils import utcnow
from app.extensions import db
from app.models.exam import ExamAttempt
from app.models.report import ResultEmail
from app.modules.reports import ai_summary
from tests.test_phase2 import make_admin
from tests.test_phase3 import FakeProvider
from tests.test_phase4 import row
from tests.test_phase6 import candidate, correct_choice, err, keys_in, make_test, set_window, time_passes

SECRET_KEYS = {"access_code", "date_of_birth", "correct_index", "explanation"}


# ---------------------------------------------------------------- helpers
@pytest.fixture
def live(app):
    """Fixed-time test, started 30 minutes ago, ends in 60 minutes, 4 candidates on the roster."""
    admin = make_admin(app)
    test_id, dept = make_test(app, admin, [row(count=6)], roster=4)
    set_window(app, test_id, -30, 60)
    return admin, test_id, dept


def start(app, n):
    c = candidate(app, n)
    data = c.post("/api/v1/exam/start").get_json()["data"]
    return c, data


def answer_right(c, questions, how_many):
    for q in questions[:how_many]:
        assert c.put(f"/api/v1/exam/answers/{q['number']}", json={"choice": correct_choice(q)}).status_code == 200


def monitor(admin, test_id, **filters):
    r = admin.get("/api/v1/monitor", query_string={"test_id": test_id, **filters})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def status_of(data, roll):
    return next(i["status"] for i in data["items"] if i["roll_number"] == roll)


def report(admin, test_id, **filters):
    r = admin.get(f"/api/v1/reports/tests/{test_id}", query_string=filters)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


@pytest.fixture
def finished(app, live):
    """Candidate 1: 6/6, candidate 2: 3/6, candidate 3: locked then auto-submitted with 0, candidate 4 absent."""
    admin, test_id, dept = live
    c1, d1 = start(app, 1)
    answer_right(c1, d1["questions"], 6)
    assert c1.post("/api/v1/exam/submit").status_code == 200
    c2, d2 = start(app, 2)
    answer_right(c2, d2["questions"], 3)
    assert c2.post("/api/v1/exam/submit").status_code == 200
    c3, _ = start(app, 3)
    assert c3.post("/api/v1/exam/lock", json={"reason": "tab_hidden"}).status_code == 200
    time_passes(app, test_id, 61)
    return admin, test_id, dept


# ---------------------------------------------------------------- access
def test_monitor_and_reports_need_an_institution_admin(client, app, live):
    _, test_id, _ = live
    assert client.get("/api/v1/monitor/tests").status_code == 401
    assert client.get("/api/v1/monitor", query_string={"test_id": test_id}).status_code == 401
    assert client.get(f"/api/v1/reports/tests/{test_id}").status_code == 401
    cand = candidate(app, 1)                                  # a candidate session is not an admin login
    assert cand.get("/api/v1/monitor", query_string={"test_id": test_id}).status_code == 401


def test_another_institution_sees_nothing(app, live):
    _, test_id, _ = live
    _, data = start(app, 1)
    other = make_admin(app, "admin@other.edu.pk", "Other College")
    assert other.get("/api/v1/monitor/tests").get_json()["data"]["tests"] == []
    assert other.get("/api/v1/monitor", query_string={"test_id": test_id}).status_code == 404
    assert other.get(f"/api/v1/reports/tests/{test_id}").status_code == 404
    assert other.get(f"/api/v1/reports/tests/{test_id}/export.csv").status_code == 404
    assert other.post(f"/api/v1/attempts/{data['attempt']['id']}/end").status_code == 404
    assert other.post(f"/api/v1/reports/tests/{test_id}/send-results", json={}).status_code == 404


# ---------------------------------------------------------------- monitor
def test_monitor_lists_tests_with_their_state(app, live):
    admin, test_id, _ = live
    tests = admin.get("/api/v1/monitor/tests").get_json()["data"]["tests"]
    assert [t["id"] for t in tests] == [test_id]
    assert tests[0]["state"] == "live"
    assert tests[0]["candidates"] == 4


def test_inactive_and_pending_candidates_are_not_test_monitor_participants(app, live):
    admin, test_id, _ = live
    from app.models.candidate import Candidate

    Candidate.query.filter_by(test_id=test_id, roll_number="R-2").update({"status": "Inactive"})
    Candidate.query.filter_by(test_id=test_id, roll_number="R-3").update({"status": "Pending"})
    db.session.commit()

    data = monitor(admin, test_id)
    assert data["counts"]["all"] == 2
    assert {item["roll_number"] for item in data["items"]} == {"R-1", "R-4"}
    tests = admin.get("/api/v1/monitor/tests").get_json()["data"]["tests"]
    assert tests[0]["candidates"] == 2


def test_monitor_shows_each_status_and_counts(app, live):
    admin, test_id, _ = live
    start(app, 1)                                             # in progress
    c2, _ = start(app, 2)
    c2.post("/api/v1/exam/lock", json={"reason": "fullscreen_exit"})
    c3, _ = start(app, 3)
    c3.post("/api/v1/exam/submit")                            # completed
    data = monitor(admin, test_id)
    assert data["counts"] == {"all": 4, "not_started": 1, "in_progress": 1, "disconnected": 0, "locked": 1,
                              "auto_submitted": 0, "completed": 1}
    assert status_of(data, "R-1") == "in_progress"
    assert status_of(data, "R-2") == "locked"
    assert status_of(data, "R-3") == "completed"
    assert status_of(data, "R-4") == "not_started"
    locked = next(i for i in data["items"] if i["roll_number"] == "R-2")["attempt"]
    assert locked["lock_reason"] == "Left fullscreen"
    assert locked["lock_count"] == 1
    assert data["test"]["state"] == "live"


def test_monitor_never_sends_access_codes_or_answers(app, live):
    admin, test_id, _ = live
    start(app, 1)
    data = monitor(admin, test_id)
    assert not keys_in(data) & SECRET_KEYS
    assert "CAND0001" not in str(data)


def test_candidate_who_stops_talking_shows_as_disconnected(app, live):
    admin, test_id, _ = live
    c, _ = start(app, 1)
    assert status_of(monitor(admin, test_id), "R-1") == "in_progress"
    a = ExamAttempt.query.first()
    a.last_seen_at = utcnow() - timedelta(seconds=120)
    db.session.commit()
    data = monitor(admin, test_id)
    assert status_of(data, "R-1") == "disconnected"
    assert data["counts"]["disconnected"] == 1
    assert c.get("/api/v1/exam/paper").status_code == 200     # any request from the page = back online
    assert status_of(monitor(admin, test_id), "R-1") == "in_progress"


def test_monitor_filters_by_status_department_and_search(app, live):
    admin, test_id, dept = live
    start(app, 1)
    assert [i["roll_number"] for i in monitor(admin, test_id, status="in_progress")["items"]] == ["R-1"]
    assert len(monitor(admin, test_id, status="not_started")["items"]) == 3
    assert len(monitor(admin, test_id, department_id=dept)["items"]) == 4
    assert [i["roll_number"] for i in monitor(admin, test_id, q="candidate 3")["items"]] == ["R-3"]
    assert monitor(admin, test_id, q="c4@mail")["items"][0]["roll_number"] == "R-4"
    data = monitor(admin, test_id, status="locked")
    assert data["items"] == []
    assert data["counts"]["all"] == 4                         # counts are always for the whole test
    r = admin.get("/api/v1/monitor", query_string={"test_id": test_id, "status": "sleeping"})
    assert r.status_code == 400


def test_admin_unlocks_from_the_monitor_and_candidate_continues(app, live):
    admin, test_id, _ = live
    c, data = start(app, 1)
    c.post("/api/v1/exam/lock", json={"reason": "tab_hidden"})
    q = data["questions"][0]
    assert err(c.put(f"/api/v1/exam/answers/{q['number']}", json={"choice": 0})) == "ATTEMPT_LOCKED"
    attempt_id = monitor(admin, test_id, status="locked")["items"][0]["attempt"]["id"]
    r = admin.post(f"/api/v1/attempts/{attempt_id}/unlock")
    assert r.status_code == 200
    assert status_of(monitor(admin, test_id), "R-1") == "in_progress"
    assert c.put(f"/api/v1/exam/answers/{q['number']}", json={"choice": 0}).status_code == 200


def test_admin_ends_a_test_and_it_is_scored(app, live):
    admin, test_id, _ = live
    c, data = start(app, 1)
    answer_right(c, data["questions"], 2)
    attempt_id = data["attempt"]["id"]
    r = admin.post(f"/api/v1/attempts/{attempt_id}/end")
    assert r.status_code == 200
    a = r.get_json()["data"]["attempt"]
    assert a["status"] == "submitted"
    assert a["submit_reason"] == "admin"
    assert a["score"] == 2
    assert status_of(monitor(admin, test_id), "R-1") == "completed"
    assert err(c.put("/api/v1/exam/answers/3", json={"choice": 0})) == "ALREADY_SUBMITTED"
    assert err(admin.post(f"/api/v1/attempts/{attempt_id}/end")) == "ALREADY_SUBMITTED"


def test_overdue_attempt_shows_as_auto_submitted(app, live):
    admin, test_id, _ = live
    start(app, 1)
    time_passes(app, test_id, 61)
    data = monitor(admin, test_id)
    assert status_of(data, "R-1") == "auto_submitted"
    assert data["test"]["state"] == "ended"


# ---------------------------------------------------------------- reports
def test_reports_exclude_disabled_candidates_without_attempt_but_keep_attempt_history(app, live):
    admin, test_id, _ = live
    from app.models.candidate import Candidate

    Candidate.query.filter_by(test_id=test_id, roll_number="R-3").update({"status": "Inactive"})
    Candidate.query.filter_by(test_id=test_id, roll_number="R-4").update({"status": "Pending"})
    db.session.commit()

    # R-1 completed before being disabled: its saved result remains part of the historical report.
    student, data = start(app, 1)
    answer_right(student, data["questions"], 1)
    assert student.post("/api/v1/exam/submit").status_code == 200
    Candidate.query.filter_by(test_id=test_id, roll_number="R-1").update({"status": "Inactive"})
    db.session.commit()

    result = report(admin, test_id)
    assert {row["roll_number"] for row in result["candidates"]} == {"R-1", "R-2"}
    assert result["summary"]["candidates"] == 2


def test_report_numbers(app, finished):
    admin, test_id, dept = finished
    data = report(admin, test_id)
    s = data["summary"]
    assert s["candidates"] == 4
    assert s["submitted"] == 3
    assert s["absent"] == 1
    assert s["auto_submitted"] == 1
    assert s["average_percent"] == 50.0                       # (100 + 50 + 0) / 3
    assert s["highest_percent"] == 100.0
    assert s["lowest_percent"] == 0.0
    assert [b["count"] for b in s["distribution"]] == [1, 0, 1, 0, 1]
    assert data["by_department"][0]["average_percent"] == 50.0
    assert data["by_subject"][0]["subject"] == "Mathematics"
    assert data["by_subject"][0]["correct"] == 9
    assert data["by_subject"][0]["questions"] == 18
    assert [r["rank"] for r in data["candidates"]] == [1, 2, 3, None]
    assert data["insights"][0].startswith("3 of 4 candidates submitted")
    assert not keys_in(data) & SECRET_KEYS


def test_report_filters(app, finished):
    admin, test_id, _ = finished
    assert [r["roll_number"] for r in report(admin, test_id, status="not_attempted")["candidates"]] == ["R-4"]
    assert len(report(admin, test_id, status="submitted")["candidates"]) == 3
    assert [r["roll_number"] for r in report(admin, test_id, q="R-2")["candidates"]] == ["R-2"]
    assert len(report(admin, test_id, email="not_sent")["candidates"]) == 3
    assert admin.get(f"/api/v1/reports/tests/{test_id}", query_string={"status": "x"}).status_code == 400


def test_reports_test_list_search_level_and_year(app, finished):
    admin, _, _ = finished
    def names(**f):
        return [t["name"] for t in admin.get("/api/v1/reports/tests", query_string=f).get_json()["data"]["tests"]]
    assert names() == ["Entry Test"]
    assert names(q="entry") == ["Entry Test"]
    assert names(q="medical") == []
    assert names(level="Masters") == []
    assert names(year=utcnow().year) == ["Entry Test"]
    assert names(year=1999) == []
    card = admin.get("/api/v1/reports/tests").get_json()["data"]["tests"][0]
    assert card["submitted"] == 3
    assert card["average_percent"] == 50.0


def test_csv_export_follows_filters_and_is_spreadsheet_safe(app, finished):
    admin, test_id, _ = finished
    cand = db.session.get(ExamAttempt, 1).candidate
    cand.full_name = "=HYPERLINK(\"x\")"
    db.session.commit()
    r = admin.get(f"/api/v1/reports/tests/{test_id}/export.csv")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    lines = r.get_data(as_text=True).lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("rank,name,roll number")
    assert len(lines) == 5
    assert "'=HYPERLINK" in lines[1]
    assert "CAND000" not in r.get_data(as_text=True)
    only = admin.get(f"/api/v1/reports/tests/{test_id}/export.csv", query_string={"status": "submitted"})
    assert len(only.get_data(as_text=True).strip().splitlines()) == 4


# ---------------------------------------------------------------- result emails
def test_send_results_with_console_backend_logs_each_email(app, finished):
    admin, test_id, _ = finished
    r = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["logged"] == 3                                # absent candidate gets nothing
    assert data["remaining"] == 0
    assert ResultEmail.query.count() == 3
    again = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={}).get_json()["data"]
    assert again["tried"] == 0                                # already sent: not sent twice
    log = report(admin, test_id)
    assert log["email"]["counts"]["logged"] == 3
    assert log["candidates"][0]["result_email"]["status"] == "logged"


def test_email_body_has_the_score(app, finished):
    from app.modules.reports.emails import compose
    c = db.session.get(ExamAttempt, 1).candidate
    subject, body = compose(c)
    assert subject == "Your result: Entry Test"
    assert "Score: 6 / 6 (100.0%)" in body
    assert "Mathematics: 6 / 6" in body
    assert "CAND0001" not in body


def test_send_results_failure_is_logged_and_can_be_retried(app, finished, monkeypatch):
    admin, test_id, _ = finished
    password = secrets.token_hex(8)                           # a throwaway value, never a real secret
    app.config.update(MAIL_BACKEND="smtp", MAIL_SERVER="smtp.example.com", MAIL_USERNAME="me@example.com",
                      MAIL_PASSWORD=password)

    class Refusing:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    monkeypatch.setattr(smtplib, "SMTP", Refusing)
    data = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={"candidate_ids": [1]}).get_json()["data"]
    assert data["failed"] == 1
    row_ = ResultEmail.query.one()
    assert row_.status == "failed"
    assert "username / password" in row_.error
    assert password not in row_.error                         # the password itself is never stored

    class Accepting(Refusing):
        sent = []

        def login(self, *a):
            pass

        def send_message(self, msg):
            Accepting.sent.append(msg["To"])

    monkeypatch.setattr(smtplib, "SMTP", Accepting)
    data = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={"candidate_ids": [1]}).get_json()["data"]
    assert data["sent"] == 1
    assert Accepting.sent == ["c1@mail.com"]
    db.session.expire_all()
    assert ResultEmail.query.one().attempts == 2
    assert report(admin, test_id, email="sent")["candidates"][0]["roll_number"] == "R-1"


def test_send_results_refuses_when_mail_is_not_set_up(app, finished):
    admin, test_id, _ = finished
    app.config.update(MAIL_BACKEND="smtp", MAIL_SERVER="")
    r = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={})
    assert r.status_code == 503
    assert err(r) == "MAIL_NOT_CONFIGURED"
    bad = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={"candidate_ids": "all"})
    assert bad.status_code == 503                             # mail check comes first


# ---------------------------------------------------------------- AI insights
def test_ai_summary_for_a_test_sends_numbers_only(app, finished, monkeypatch):
    admin, test_id, _ = finished
    seen = {}

    def reply(prompt):
        seen["prompt"] = prompt
        return '{"insights": ["Average is 50%.", "Mathematics needs work."]}'

    monkeypatch.setattr(ai_summary, "get_provider", lambda cfg: FakeProvider(reply))
    r = admin.post("/api/v1/reports/ai-summary", json={"scope": "test", "test_id": test_id})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["data"]["insights"] == ["Average is 50%.", "Mathematics needs work."]
    assert "Candidate 1" not in seen["prompt"]
    assert "c1@mail.com" not in seen["prompt"]
    assert "R-1" not in seen["prompt"]
    assert '"average_percent": 50.0' in seen["prompt"]


def test_ai_summary_for_the_bank_and_plain_text_replies(app, live, monkeypatch):
    admin, _, _ = live
    monkeypatch.setattr(ai_summary, "get_provider", lambda cfg: FakeProvider("- First point\n- Second point"))
    r = admin.post("/api/v1/reports/ai-summary", json={"scope": "bank"})
    assert r.status_code == 200
    assert r.get_json()["data"]["insights"] == ["First point", "Second point"]
    assert admin.post("/api/v1/reports/ai-summary", json={"scope": "moon"}).status_code == 422


def test_ai_errors_come_back_as_safe_messages(app, live, monkeypatch):
    admin, test_id, _ = live
    boom = AIError("AI_RATE_LIMITED", "The free AI quota or rate limit was reached.", status=429)
    monkeypatch.setattr(ai_summary, "get_provider", lambda cfg: FakeProvider(boom))
    r = admin.post("/api/v1/reports/ai-summary", json={"scope": "test", "test_id": test_id})
    assert r.status_code == 429
    assert err(r) == "AI_RATE_LIMITED"


def test_bank_insights_tips(app, live):
    admin, _, _ = live
    data = admin.get("/api/v1/reports/bank-insights").get_json()["data"]
    assert data["subjects"][0]["subject"] == "Mathematics"
    assert data["subjects"][0]["approved"] == 15
    assert data["tips"]


# ---------------------------------------------------------------- dashboard
def test_dashboard_has_phase7_numbers(app, finished):
    admin, _, _ = finished
    d = admin.get("/api/v1/dashboard/summary").get_json()["data"]
    assert d["tests"]["published"] == 1
    assert d["tests"]["ended"] == 1
    assert d["candidates"]["total"] == 4
    assert d["candidates"]["submitted"] == 3
    assert d["average_percent"] == 50.0
    assert d["questions"]["approved"] == 15
