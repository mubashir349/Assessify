"""Phase 4 - creating tests: the 1.5x pool rule, schedules (flexible / fixed) and publish."""
from datetime import datetime

import pytest

from app.extensions import db
from app.models.aptitude_test import Schedule
from app.models.department import Department
from app.models.question import GenerationAttempt, Question
from app.models.user import User
from tests.test_phase2 import DEPT, make_admin

# 2:00-4:00 pm in Karachi (UTC+5) = 09:00-11:00 UTC
FIXED = {"timing_mode": "fixed", "starts_at": "2030-11-05T09:00:00Z", "ends_at": "2030-11-05T11:00:00Z",
         "result_release": "scheduled", "release_on": "2030-11-12"}
FLEX = {"timing_mode": "flexible", "starts_at": "2030-11-05T04:00:00Z", "ends_at": "2030-11-05T06:30:00Z",
        "duration_minutes": 120, "result_release": "immediate"}


def add_questions(app, dept_id, subject, n, *, qtype="mcq", difficulty="easy", status="approved"):
    """Puts n questions straight into the bank (what Phase 3 Draft Review does after approval)."""
    with app.app_context():
        dept = db.session.get(Department, dept_id)
        admin = User.query.filter_by(institution_id=dept.institution_id).first()
        common = dict(institution_id=dept.institution_id, department_id=dept.id, department_name=dept.name,
                      level=dept.level, subject_name=subject, question_type=qtype, difficulty=difficulty)
        att = GenerationAttempt(created_by_id=admin.id, requested_count=n, source_filename="seed.pdf",
                                source_sha256="0" * 64, source_text="seed", status="completed", **common)
        db.session.add(att)
        db.session.flush()
        for i in range(n):
            options = ["True", "False"] if qtype == "true_false" else ["A", "B", "C", "D"]
            db.session.add(Question(attempt_id=att.id, text=f"{subject} question {i}", options=options,
                                    correct_index=0, status=status, **common))
        db.session.commit()


@pytest.fixture
def admin(app):
    c = make_admin(app)
    dept = c.post("/api/v1/departments", json=DEPT).get_json()["data"]["department"]
    return c, dept["id"]


def body(dept_id, rows, schedule=FIXED, **extra):
    return {"name": "Undergraduate Admission Test", "level": "Undergraduate",
            "compositions": [{"department_id": dept_id, "rows": rows}], "schedule": schedule, **extra}


def row(subject="Mathematics", count=10, difficulty="any", qtype="mcq"):
    return {"subject": subject, "question_type": qtype, "difficulty": difficulty, "count": count}


def avail(c, dept_id, rows):
    r = c.post("/api/v1/tests/availability", json={"level": "Undergraduate",
                                                   "compositions": [{"department_id": dept_id, "rows": rows}]})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["availability"]


def test_tests_require_institution_admin(client, app):
    assert client.get("/api/v1/tests").status_code == 401
    client.post("/api/v1/auth/login", json={"email": "root@assessify.com", "password": "SuperSecret123"})
    assert client.get("/api/v1/tests").status_code == 403


def test_meta_has_phase4_lists(client):
    d = client.get("/api/v1/meta").get_json()["data"]
    assert d["pool_factor"] == 1.5
    assert [x["value"] for x in d["row_difficulties"]] == ["any", "easy", "medium", "hard"]
    assert {x["value"] for x in d["timing_modes"]} == {"flexible", "fixed"}


def test_pool_rule_is_ceil_of_one_and_a_half(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 15)
    a = avail(c, dept, [row(count=10)])
    r = a["rows"][0]
    assert (r["needed"], r["pool"], r["short"], r["sufficient"]) == (15, 15, 0, True)
    assert a["all_sufficient"] is True
    a = avail(c, dept, [row(count=11)])            # ceil(16.5) = 17
    assert (a["rows"][0]["needed"], a["rows"][0]["short"], a["all_sufficient"]) == (17, 2, False)
    assert a["shortfalls"][0]["label"].startswith("Pre-Engineering → Mathematics")


def test_difficulty_type_and_subject_filters(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 6, difficulty="easy")
    add_questions(app, dept, "Mathematics", 6, difficulty="hard")
    add_questions(app, dept, "Mathematics", 9, qtype="true_false")
    add_questions(app, dept, "Physics", 30)
    pools = [r["pool"] for r in avail(c, dept, [row(count=4, difficulty="easy"), row(count=4, difficulty="hard"),
                                                row(subject="mathematics", count=4, difficulty="medium")])["rows"]]
    assert pools == [6, 6, 0]
    assert avail(c, dept, [row(count=4)])["rows"][0]["pool"] == 12             # any = easy + medium + hard, MCQ only
    assert avail(c, dept, [row(count=4, qtype="true_false")])["rows"][0]["pool"] == 9


def test_only_approved_questions_count(app, admin):
    c, dept = admin
    for status in ("draft", "rejected", "replaced"):
        add_questions(app, dept, "Mathematics", 20, status=status)
    add_questions(app, dept, "Mathematics", 3)
    assert avail(c, dept, [row(count=2)])["rows"][0]["pool"] == 3


def test_overlapping_rows_are_checked_together(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 6, difficulty="easy")
    add_questions(app, dept, "Mathematics", 6, difficulty="hard")
    # easy x4 needs 6 (6 easy ok) and any x6 needs 9 (12 ok), but together they need 15 of the same 12 questions
    a = avail(c, dept, [row(count=4, difficulty="easy"), row(count=6, difficulty="any")])
    assert all(r["sufficient"] for r in a["rows"])
    assert a["all_sufficient"] is False
    assert a["shortfalls"][0]["difficulty"] == "combined"
    assert a["shortfalls"][0]["short"] == 3


def test_publish_is_blocked_while_a_pool_is_short(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 15)
    add_questions(app, dept, "Physics", 4)
    r = c.post("/api/v1/tests", json=body(dept, [row(count=10), row("Physics", count=5)]))
    assert r.status_code == 201
    test = r.get_json()["data"]["test"]
    assert test["status"] == "draft"
    assert test["availability"]["all_sufficient"] is False

    r = c.post(f"/api/v1/tests/{test['id']}/publish")
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "POOL_TOO_SMALL"
    short = r.get_json()["error"]["details"]["shortfalls"]
    assert [(s["subject"], s["needed"], s["pool"], s["short"]) for s in short] == [("Physics", 8, 4, 4)]
    assert c.get(f"/api/v1/tests/{test['id']}").get_json()["data"]["test"]["status"] == "draft"

    # lower Physics to 2 per candidate (needs 3, bank has 4) -> publish works
    assert c.put(f"/api/v1/tests/{test['id']}", json=body(dept, [row(count=10), row("Physics", count=2)])).status_code == 200
    r = c.post(f"/api/v1/tests/{test['id']}/publish")
    assert r.status_code == 200
    pub = r.get_json()["data"]["test"]
    assert pub["status"] == "published"
    assert pub["published_at"]
    assert pub["questions_per_candidate"] == {str(dept): 12}
    r = c.post(f"/api/v1/tests/{test['id']}/publish")
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "INVALID_TRANSITION"


def test_published_fixed_test_stores_correct_start_and_end(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 15)
    # the browser sends Karachi 2:00-4:00 pm as UTC; an offset form is accepted too
    sched = {**FIXED, "starts_at": "2030-11-05T14:00:00+05:00", "duration_minutes": 999}
    test = c.post("/api/v1/tests", json=body(dept, [row(count=10)], sched)).get_json()["data"]["test"]
    pub = c.post(f"/api/v1/tests/{test['id']}/publish").get_json()["data"]["test"]
    assert pub["schedule"] == {"timing_mode": "fixed", "starts_at": "2030-11-05T09:00:00Z",
                               "ends_at": "2030-11-05T11:00:00Z", "duration_minutes": 120,
                               "result_release": "scheduled", "release_on": "2030-11-12"}
    with app.app_context():
        s = db.session.get(Schedule, test["id"])
        assert (s.starts_at, s.ends_at, s.duration_minutes) == (datetime(2030, 11, 5, 9), datetime(2030, 11, 5, 11), 120)


def test_flexible_schedule_rules(app, admin):
    c, dept = admin
    r = c.post("/api/v1/tests", json=body(dept, [row()], FLEX))
    assert r.status_code == 201
    assert r.get_json()["data"]["test"]["schedule"]["duration_minutes"] == 120
    r = c.post("/api/v1/tests", json=body(dept, [row()], {**FLEX, "duration_minutes": 200}))   # window is 150 min
    assert r.status_code == 422
    assert "schedule.duration_minutes" in r.get_json()["error"]["details"]
    r = c.post("/api/v1/tests", json=body(dept, [row()], {**FLEX, "duration_minutes": None}))
    assert r.status_code == 422


@pytest.mark.parametrize("change, key", [
    ({"ends_at": "2030-11-05T08:00:00Z"}, "schedule.ends_at"),                 # end before start
    ({"starts_at": "2030-11-05T09:00:00"}, "schedule.starts_at"),              # no timezone
    ({"starts_at": "tomorrow"}, "schedule.starts_at"),
    ({"timing_mode": "sometimes"}, "schedule.timing_mode"),
    ({"release_on": None}, "schedule.release_on"),
    ({"release_on": "2030-11-01"}, "schedule.release_on"),                     # before the test
    ({"result_release": "never"}, "schedule.result_release"),
])
def test_schedule_validation(app, admin, change, key):
    c, dept = admin
    r = c.post("/api/v1/tests", json=body(dept, [row()], {**FIXED, **change}))
    assert r.status_code == 422
    assert key in r.get_json()["error"]["details"]


@pytest.mark.parametrize("rows", [
    [],                                                       # no subject rows
    [row(count=0)], [row(count=201)], [row(count="ten")], [row(count=True)], [row(count=2.5)],
    [row(subject="Biology")],                                 # not a subject of this department
    [row(qtype="essay")], [row(difficulty="extreme")],
    [row(), row(count=3)],                                    # duplicate row
])
def test_composition_validation(app, admin, rows):
    c, dept = admin
    r = c.post("/api/v1/tests", json=body(dept, rows))
    assert r.status_code == 422
    assert "compositions" in r.get_json()["error"]["details"]


def test_name_level_and_department_checks(app, admin):
    c, dept = admin
    r = c.post("/api/v1/tests", json={**body(dept, [row()]), "name": "", "level": "School"})
    assert r.status_code == 422
    assert {"name", "level"} <= set(r.get_json()["error"]["details"])
    r = c.post("/api/v1/tests", json={**body(dept, [row()]), "level": "Masters"})       # Undergraduate field
    assert r.status_code == 422
    r = c.post("/api/v1/tests", json={**body(dept, [row()]), "compositions": []})
    assert r.status_code == 422
    assert c.post("/api/v1/tests", json=body(9999, [row()])).status_code == 404


def test_cannot_publish_a_test_in_the_past(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 15)
    past = {**FIXED, "starts_at": "2020-01-01T09:00:00Z", "ends_at": "2020-01-01T11:00:00Z", "release_on": "2020-01-02"}
    test = c.post("/api/v1/tests", json=body(dept, [row()], past)).get_json()["data"]["test"]
    r = c.post(f"/api/v1/tests/{test['id']}/publish")
    assert r.status_code == 422
    assert r.get_json()["error"]["code"] == "SCHEDULE_IN_PAST"


def test_published_test_is_locked(app, admin):
    c, dept = admin
    add_questions(app, dept, "Mathematics", 15)
    tid = c.post("/api/v1/tests", json=body(dept, [row()])).get_json()["data"]["test"]["id"]
    assert c.post(f"/api/v1/tests/{tid}/publish").status_code == 200
    assert c.put(f"/api/v1/tests/{tid}", json=body(dept, [row(count=2)])).get_json()["error"]["code"] == "TEST_LOCKED"
    assert c.delete(f"/api/v1/tests/{tid}").status_code == 409


def test_list_update_delete_draft(app, admin):
    c, dept = admin
    tid = c.post("/api/v1/tests", json=body(dept, [row()])).get_json()["data"]["test"]["id"]
    r = c.put(f"/api/v1/tests/{tid}", json=body(dept, [row(count=3), row("Physics", count=2, difficulty="hard")],
                                                 FLEX, name="Renamed test"))
    t = r.get_json()["data"]["test"]
    assert t["name"] == "Renamed test"
    assert [x["subject"] for x in t["compositions"][0]["rows"]] == ["Mathematics", "Physics"]
    assert t["schedule"]["timing_mode"] == "flexible"
    items = c.get("/api/v1/tests?status=draft&q=renamed").get_json()["data"]["items"]
    assert [i["id"] for i in items] == [tid]
    assert "compositions" not in items[0]
    assert c.get("/api/v1/tests?status=published").get_json()["data"]["items"] == []
    assert c.get("/api/v1/tests?status=bogus").status_code == 400
    assert c.delete(f"/api/v1/tests/{tid}").status_code == 200
    assert c.get(f"/api/v1/tests/{tid}").status_code == 404


def test_institutions_cannot_see_each_others_tests(app, admin):
    c, dept = admin
    tid = c.post("/api/v1/tests", json=body(dept, [row()])).get_json()["data"]["test"]["id"]
    other = make_admin(app, email="admin@other.edu.pk", name="Other College")
    assert other.get(f"/api/v1/tests/{tid}").status_code == 404
    assert other.put(f"/api/v1/tests/{tid}", json=body(dept, [row()])).status_code == 404
    assert other.post(f"/api/v1/tests/{tid}/publish").status_code == 404
    assert other.delete(f"/api/v1/tests/{tid}").status_code == 404
    assert other.get("/api/v1/tests").get_json()["data"]["items"] == []
    assert other.post("/api/v1/tests", json=body(dept, [row()])).status_code == 404        # A's department


def test_other_institutions_questions_never_count(app, admin):
    c, dept = admin
    other = make_admin(app, email="admin@other.edu.pk", name="Other College")
    other_dept = other.post("/api/v1/departments", json=DEPT).get_json()["data"]["department"]["id"]
    add_questions(app, other_dept, "Mathematics", 50)
    assert avail(c, dept, [row(count=2)])["rows"][0]["pool"] == 0


def test_department_used_by_a_test_is_protected(app, admin):
    c, dept = admin
    c.post("/api/v1/tests", json=body(dept, [row("Physics", count=2)]))
    r = c.delete(f"/api/v1/departments/{dept}")
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "DEPARTMENT_IN_USE"
    r = c.put(f"/api/v1/departments/{dept}", json={**DEPT, "subjects": ["Mathematics", "Chemistry"]})   # drops Physics
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "SUBJECT_IN_USE"
    r = c.put(f"/api/v1/departments/{dept}", json={**DEPT, "level": "Masters"})
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "DEPARTMENT_IN_USE"
    # unrelated edits still work
    assert c.put(f"/api/v1/departments/{dept}", json={**DEPT, "subjects": DEPT["subjects"] + ["Biology"]}).status_code == 200
