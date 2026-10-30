"""Phase 6 - taking the test: time gate, random paper, saving answers, lock events, auto-submit, server-side scoring."""
import json
from datetime import timedelta

import pytest

from app.common.utils import utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.exam import ExamAttempt
from app.models.question import Question
from tests.test_phase2 import DEPT, make_admin
from tests.test_phase4 import FIXED, FLEX, add_questions, row

FORBIDDEN_KEYS = {"correct_index", "explanation", "is_correct", "difficulty", "question_id", "answer_index"}


# ---------------------------------------------------------------- helpers
def make_test(app, c, rows, *, schedule=FIXED, questions=(("Mathematics", 15, "easy"),), roster=2):
    """Published Pre-Engineering test + `roster` candidates (codes CAND0001...). Returns (test_id, dept_id)."""
    dept = c.post("/api/v1/departments", json=DEPT).get_json()["data"]["department"]["id"]
    for subject, n, diff, *qtype in questions:
        add_questions(app, dept, subject, n, difficulty=diff, qtype=(qtype or ["mcq"])[0])
    body = {"name": "Entry Test", "level": "Undergraduate", "schedule": schedule,
            "compositions": [{"department_id": dept, "rows": rows}]}
    test_id = c.post("/api/v1/tests", json=body).get_json()["data"]["test"]["id"]
    assert c.post(f"/api/v1/tests/{test_id}/publish").status_code == 200
    for i in range(1, roster + 1):
        r = c.post("/api/v1/roster", json={"test_id": test_id, "full_name": f"Candidate {i}", "email": f"c{i}@mail.com",
                                           "roll_number": f"R-{i}", "date_of_birth": "2008-01-0" + str(i),
                                           "department_id": dept, "access_code": f"CAND000{i}"})
        assert r.status_code == 201, r.get_json()
    return test_id, dept


def set_window(app, test_id, start_min, end_min):
    """Moves a published test's window relative to NOW (the API never allows this; tests need it).
    Uses the fixture's own session (no new app context), so the next request sees the change."""
    sc = db.session.get(AptitudeTest, test_id).schedule
    now = utcnow()
    sc.starts_at, sc.ends_at = now + timedelta(minutes=start_min), now + timedelta(minutes=end_min)
    if sc.timing_mode == "fixed":
        sc.duration_minutes = end_min - start_min
    db.session.commit()


def time_passes(app, test_id, minutes):
    """Moves the window AND every attempt's times back by `minutes`: the same as waiting that long."""
    d = timedelta(minutes=minutes)
    sc = db.session.get(AptitudeTest, test_id).schedule
    sc.starts_at, sc.ends_at = sc.starts_at - d, sc.ends_at - d
    for a in ExamAttempt.query.filter_by(test_id=test_id).all():
        a.started_at, a.deadline_at = a.started_at - d, a.deadline_at - d
        if a.locked_at:
            a.locked_at -= d
    db.session.commit()


def candidate(app, n=1):
    c = app.test_client()
    r = c.post("/api/v1/candidate/login", json={"access_code": f"CAND000{n}", "date_of_birth": f"2008-01-0{n}"})
    assert r.status_code == 200, r.get_json()
    return c


def keys_in(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | set().union(*(keys_in(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(keys_in(v) for v in obj)) if obj else set()
    return set()


def correct_choice(q: dict) -> int:
    """add_questions() makes options A-D with A correct (True for true/false)."""
    return q["options"].index("True" if q["question_type"] == "true_false" else "A")


def err(r) -> str:
    return r.get_json()["error"]["code"]


@pytest.fixture()
def live(app):
    """A fixed-time test that started 30 minutes ago and ends in 60 minutes."""
    admin = make_admin(app)
    test_id, dept = make_test(app, admin, [row(count=6)])
    set_window(app, test_id, -30, 60)
    return admin, test_id, dept


# ---------------------------------------------------------------- the time gate
def test_exam_routes_need_a_candidate_session(client, app):
    assert client.get("/api/v1/exam").status_code == 401
    assert client.post("/api/v1/exam/start").status_code == 401
    admin = make_admin(app)                     # an admin login is not a candidate session
    assert admin.post("/api/v1/exam/start").status_code == 401


def test_fixed_time_candidate_cannot_start_early(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=6)])
    set_window(app, test_id, 10, 70)
    c = candidate(app)                          # signing in early is fine (Phase 5) ...
    gate = c.get("/api/v1/exam").get_json()["data"]["gate"]
    assert gate["state"] == "not_started" and not gate["can_start"] and 590 <= gate["seconds_until_start"] <= 600
    r = c.post("/api/v1/exam/start")            # ... starting is not
    assert r.status_code == 403 and err(r) == "TEST_NOT_STARTED"
    assert 590 <= r.get_json()["error"]["details"]["seconds_left"] <= 600
    with app.app_context():
        assert ExamAttempt.query.count() == 0   # nothing was created
    time_passes(app, test_id, 11)
    assert c.post("/api/v1/exam/start").status_code == 200


def test_late_starter_in_fixed_test_ends_at_the_fixed_end_time(app, live):
    _, test_id, _ = live
    c = candidate(app)
    gate = c.get("/api/v1/exam").get_json()["data"]["gate"]
    assert gate["state"] == "open" and 59 <= gate["minutes_if_started_now"] <= 60
    a = c.post("/api/v1/exam/start").get_json()["data"]["attempt"]
    assert a["deadline_at"] == gate["ends_at"]                  # not start + 90 minutes
    assert 3590 <= a["remaining_seconds"] <= 3600
    assert a["timing_mode"] == "fixed" and a["status"] == "in_progress"


def test_flexible_timer_is_own_duration_but_never_past_the_window(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=6)], schedule=FLEX)        # duration 120 min
    set_window(app, test_id, -10, 300)
    a = candidate(app, 1).post("/api/v1/exam/start").get_json()["data"]["attempt"]
    assert 7190 <= a["remaining_seconds"] <= 7200                              # own 120 minutes
    set_window(app, test_id, -200, 30)                                          # window closes in 30 min
    b = candidate(app, 2).post("/api/v1/exam/start").get_json()["data"]["attempt"]
    assert 1790 <= b["remaining_seconds"] <= 1800


def test_cannot_start_after_the_end(app, live):
    _, test_id, _ = live
    c = candidate(app)                          # signed in while the test was open
    time_passes(app, test_id, 61)
    assert c.get("/api/v1/exam").get_json()["data"]["gate"]["state"] == "closed"
    r = c.post("/api/v1/exam/start")
    assert r.status_code == 403 and err(r) == "TEST_CLOSED"


# ---------------------------------------------------------------- the random paper
def test_two_candidates_get_different_papers(app, live):
    papers = []
    for n in (1, 2):
        d = candidate(app, n).post("/api/v1/exam/start").get_json()["data"]
        qs = d["questions"]
        assert len(qs) == 6 == d["attempt"]["question_count"]
        assert [q["number"] for q in qs] == [1, 2, 3, 4, 5, 6]
        assert len({q["text"] for q in qs}) == 6                                # no repeats on one paper
        papers.append([(q["text"], tuple(q["options"])) for q in qs])
    assert papers[0] != papers[1]
    with app.app_context():
        ids = [{i.question_id for i in a.items} for a in ExamAttempt.query.all()]
        approved = {q.id for q in Question.query.filter_by(status="approved").all()}
        assert all(s <= approved for s in ids)


def test_paper_follows_the_composition_and_never_repeats_a_question(app):
    admin = make_admin(app)
    # Maths: 2 easy-only + 3 any. 3 easy + 6 medium in the bank -> 5 distinct questions, the 2 easy ones from the easy pool.
    test_id, _ = make_test(app, admin, [row(count=3, difficulty="any"), row(count=2, difficulty="easy"),
                                        row(subject="Physics", count=2, qtype="true_false")],
                           questions=(("Mathematics", 3, "easy"), ("Mathematics", 6, "medium"),
                                      ("Physics", 3, "easy", "true_false")))
    set_window(app, test_id, -5, 60)
    for n in (1, 2):
        qs = candidate(app, n).post("/api/v1/exam/start").get_json()["data"]["questions"]
        assert [q["subject"] for q in qs] == ["Mathematics"] * 5 + ["Physics"] * 2      # grouped by subject
        assert all(q["options"] == ["True", "False"] for q in qs[5:])                   # T/F keeps its order
    for a in ExamAttempt.query.all():
        assert len({i.question_id for i in a.items}) == 7                       # no question twice
        maths = [i.question for i in a.items if i.subject_name == "Mathematics"]
        assert sum(q.difficulty == "easy" for q in maths) >= 2                   # the easy row got its easy ones


def test_start_again_resumes_the_same_paper(app, live):
    c = candidate(app)
    first = c.post("/api/v1/exam/start").get_json()["data"]
    c.put("/api/v1/exam/answers/2", json={"choice": 1, "flagged": True})
    again = c.post("/api/v1/exam/start").get_json()["data"]
    assert again["attempt"]["id"] == first["attempt"]["id"]
    assert [q["text"] for q in again["questions"]] == [q["text"] for q in first["questions"]]
    assert again["questions"][1]["choice"] == 1 and again["questions"][1]["flagged"] is True
    paper = c.get("/api/v1/exam/paper").get_json()["data"]
    assert paper["questions"] == again["questions"] and paper["attempt"]["answered_count"] == 1
    with app.app_context():
        assert ExamAttempt.query.count() == 1


def test_short_pool_at_start_is_refused_cleanly(app, live):
    with app.app_context():
        for q in Question.query.limit(12).all():
            q.status = "rejected"               # (not possible through the API; approved questions stay approved)
        db.session.commit()
    r = candidate(app).post("/api/v1/exam/start")
    assert r.status_code == 409 and err(r) == "PAPER_UNAVAILABLE"
    with app.app_context():
        assert ExamAttempt.query.count() == 0


# ---------------------------------------------------------------- answers + the end time
def test_answers_are_saved_cleared_and_validated(app, live):
    c = candidate(app)
    c.post("/api/v1/exam/start")
    r = c.put("/api/v1/exam/answers/1", json={"choice": 3})
    assert r.status_code == 200 and r.get_json()["data"]["question"]["choice"] == 3
    assert r.get_json()["data"]["attempt"]["answered_count"] == 1
    assert c.put("/api/v1/exam/answers/1", json={"choice": None}).get_json()["data"]["question"]["choice"] is None
    assert c.put("/api/v1/exam/answers/1", json={"flagged": True}).get_json()["data"]["question"]["flagged"] is True
    for bad in ({"choice": 4}, {"choice": -1}, {"choice": "A"}, {"choice": True}, {"flagged": "yes"}, {}):
        r = c.put("/api/v1/exam/answers/1", json=bad)
        assert r.status_code == 422 and err(r) == "VALIDATION_ERROR", bad
    assert c.put("/api/v1/exam/answers/99", json={"choice": 0}).status_code == 404
    assert c.put("/api/v1/exam/answers/1", data="x").status_code == 400


def test_answer_before_starting_is_refused(app, live):
    r = candidate(app).put("/api/v1/exam/answers/1", json={"choice": 0})
    assert r.status_code == 409 and err(r) == "ATTEMPT_NOT_STARTED"


def test_answers_after_the_end_time_are_rejected_and_the_test_is_auto_submitted(app, live):
    _, test_id, _ = live
    c = candidate(app)
    qs = c.post("/api/v1/exam/start").get_json()["data"]["questions"]
    c.put("/api/v1/exam/answers/1", json={"choice": correct_choice(qs[0])})
    time_passes(app, test_id, 61)                                    # the fixed end time has passed
    r = c.put("/api/v1/exam/answers/2", json={"choice": correct_choice(qs[1])})
    assert r.status_code == 409 and err(r) == "TIME_UP"
    r = c.put("/api/v1/exam/answers/1", json={"choice": None})       # can't undo a saved answer either
    assert r.status_code == 409 and err(r) == "ALREADY_SUBMITTED"
    with app.app_context():
        a = ExamAttempt.query.one()
        assert a.status == "submitted" and a.submit_reason == "time_up"
        assert a.answered_count == 1 and a.score == 1                # only the answer saved in time counts
        assert [i.answer_index for i in a.items][1] is None


def test_overdue_attempt_is_submitted_when_any_route_touches_it(app, live):
    _, test_id, _ = live
    c = candidate(app)
    c.post("/api/v1/exam/start")
    time_passes(app, test_id, 61)
    gate = c.get("/api/v1/exam").get_json()["data"]["gate"]
    assert gate["state"] == "submitted" and gate["attempt"]["submit_reason"] == "time_up"
    assert c.get("/api/v1/exam/paper").get_json()["data"]["questions"] == []
    r = c.post("/api/v1/exam/start")
    assert r.status_code == 409 and err(r) == "ALREADY_SUBMITTED"


# ---------------------------------------------------------------- submit + scoring
def test_submit_is_scored_on_the_server(app, live):
    c = candidate(app)
    qs = c.post("/api/v1/exam/start").get_json()["data"]["questions"]
    for q in qs[:4]:                                                 # 4 right
        c.put(f"/api/v1/exam/answers/{q['number']}", json={"choice": correct_choice(q)})
    c.put("/api/v1/exam/answers/5", json={"choice": (correct_choice(qs[4]) + 1) % 4})   # 1 wrong, 1 blank
    r = c.post("/api/v1/exam/submit")
    a = r.get_json()["data"]["attempt"]
    assert r.status_code == 200 and a["status"] == "submitted" and a["submit_reason"] == "candidate"
    assert c.post("/api/v1/exam/submit").status_code == 200                           # twice is harmless
    res = c.get("/api/v1/exam/result").get_json()["data"]
    assert res["release"] == "scheduled" and res["score"] is None                       # FIXED releases later
    assert res["release_on"] == "2030-11-12" and res["email"] == "c1@mail.com"
    with app.app_context():
        a = ExamAttempt.query.one()
        assert (a.score, a.max_score, a.correct_count, a.answered_count) == (4, 6, 4, 5)
    r = c.put("/api/v1/exam/answers/6", json={"choice": 0})
    assert r.status_code == 409 and err(r) == "ALREADY_SUBMITTED"


def test_immediate_release_shows_the_score_by_subject(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=4), row(subject="Physics", count=2)], schedule=FLEX,
                           questions=(("Mathematics", 6, "easy"), ("Physics", 3, "easy")))
    set_window(app, test_id, -5, 200)
    c = candidate(app)
    assert c.get("/api/v1/exam/result").status_code == 409                         # not started
    qs = c.post("/api/v1/exam/start").get_json()["data"]["questions"]
    assert c.get("/api/v1/exam/result").get_json()["error"]["code"] == "NOT_SUBMITTED"
    for q in qs:
        if q["subject"] == "Mathematics":
            c.put(f"/api/v1/exam/answers/{q['number']}", json={"choice": correct_choice(q)})
    c.post("/api/v1/exam/submit")
    s = c.get("/api/v1/exam/result").get_json()["data"]["score"]
    assert (s["score"], s["max_score"], s["percent"], s["correct"], s["answered"]) == (4, 6, 66.7, 4, 4)
    assert s["by_subject"] == [{"subject": "Mathematics", "score": 4, "max_score": 4, "correct": 4, "questions": 4},
                               {"subject": "Physics", "score": 0, "max_score": 2, "correct": 0, "questions": 2}]


def test_candidate_responses_never_contain_the_correct_answers(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=6)], schedule=FLEX)
    set_window(app, test_id, -5, 200)
    with app.app_context():
        for q in Question.query.all():
            q.explanation = "SECRET-EXPLANATION"
        db.session.commit()
    c = candidate(app)
    bodies = [c.get("/api/v1/candidate/me"), c.get("/api/v1/exam"), c.post("/api/v1/exam/start"),
              c.get("/api/v1/exam/paper"), c.put("/api/v1/exam/answers/1", json={"choice": 0}),
              c.post("/api/v1/exam/lock", json={"reason": "tab_hidden"})]
    unlock = admin.post(f"/api/v1/attempts/{bodies[2].get_json()['data']['attempt']['id']}/unlock")
    assert unlock.status_code == 200
    bodies += [c.post("/api/v1/exam/submit"), c.get("/api/v1/exam/result"), c.get("/api/v1/exam")]
    for r in bodies:
        assert r.status_code == 200, r.get_json()
        data = r.get_json()
        assert not keys_in(data) & FORBIDDEN_KEYS, (r.request.path, keys_in(data) & FORBIDDEN_KEYS)
        assert "SECRET-EXPLANATION" not in json.dumps(data)


# ---------------------------------------------------------------- lock events
def test_lock_stops_answers_until_an_admin_unlocks(app, live):
    admin, _, _ = live
    c = candidate(app)
    attempt_id = c.post("/api/v1/exam/start").get_json()["data"]["attempt"]["id"]
    a = c.post("/api/v1/exam/lock", json={"reason": "fullscreen_exit"}).get_json()["data"]["attempt"]
    assert a["status"] == "locked" and a["lock_count"] == 1 and a["reference"].startswith("APT-")
    c.post("/api/v1/exam/lock", json={"reason": "tab_hidden"})                     # already locked: no new event
    r = c.put("/api/v1/exam/answers/1", json={"choice": 0})
    assert r.status_code == 423 and err(r) == "ATTEMPT_LOCKED"
    assert c.post("/api/v1/exam/submit").status_code == 423
    assert c.get("/api/v1/exam/paper").get_json()["data"]["attempt"]["status"] == "locked"   # still readable

    other = make_admin(app, email="admin@fast.edu.pk", name="FAST")
    assert other.post(f"/api/v1/attempts/{attempt_id}/unlock").status_code == 404
    assert c.post(f"/api/v1/attempts/{attempt_id}/unlock").status_code == 401    # a candidate can't unlock
    r = admin.post(f"/api/v1/attempts/{attempt_id}/unlock")
    a = r.get_json()["data"]["attempt"]
    assert r.status_code == 200 and a["status"] == "in_progress"
    assert [(e["kind"], e["reason"]) for e in a["events"]] == [("lock", "fullscreen_exit"), ("unlock", None)]
    assert a["events"][1]["by"] == "Dr. Ayesha Khan"
    assert admin.post(f"/api/v1/attempts/{attempt_id}/unlock").status_code == 409  # not locked any more
    assert c.put("/api/v1/exam/answers/1", json={"choice": 0}).status_code == 200
    c.post("/api/v1/exam/lock", json={"reason": "anything"})
    with app.app_context():
        assert ExamAttempt.query.one().events[-1].reason == "other" and ExamAttempt.query.one().lock_count == 2


def test_fixed_time_keeps_running_while_locked(app, live):
    admin, test_id, _ = live
    c = candidate(app)
    a = c.post("/api/v1/exam/start").get_json()["data"]["attempt"]
    c.post("/api/v1/exam/lock", json={"reason": "tab_hidden"})
    time_passes(app, test_id, 20)
    after = admin.post(f"/api/v1/attempts/{a['id']}/unlock").get_json()["data"]["attempt"]
    assert 2350 <= after["remaining_seconds"] <= 2400          # 40 minutes left, the 20 locked minutes are gone
    time_passes(app, test_id, 41)
    assert c.get("/api/v1/exam").get_json()["data"]["gate"]["state"] == "submitted"


def test_flexible_timer_is_frozen_while_locked(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=6)], schedule=FLEX)        # 120 minutes
    set_window(app, test_id, -5, 600)
    c = candidate(app)
    a = c.post("/api/v1/exam/start").get_json()["data"]["attempt"]
    c.post("/api/v1/exam/lock", json={"reason": "fullscreen_exit"})
    time_passes(app, test_id, 30)
    locked = c.get("/api/v1/exam/paper").get_json()["data"]["attempt"]
    assert 7190 <= locked["remaining_seconds"] <= 7200                        # frozen
    after = admin.post(f"/api/v1/attempts/{a['id']}/unlock").get_json()["data"]["attempt"]
    assert 7180 <= after["remaining_seconds"] <= 7200                         # the 30 locked minutes were given back


def test_locked_flexible_attempt_still_closes_at_the_window_end(app):
    admin = make_admin(app)
    test_id, _ = make_test(app, admin, [row(count=6)], schedule=FLEX)
    set_window(app, test_id, -5, 60)
    c = candidate(app)
    c.post("/api/v1/exam/start")
    c.post("/api/v1/exam/lock", json={"reason": "fullscreen_exit"})
    time_passes(app, test_id, 61)
    res = c.get("/api/v1/exam/result")
    assert res.status_code == 200 and res.get_json()["data"]["attempt"]["submit_reason"] == "time_up"


# ---------------------------------------------------------------- roster side
def test_roster_shows_the_attempt_and_protects_started_candidates(app, live):
    admin, test_id, dept = live
    c = candidate(app)
    c.post("/api/v1/exam/start")
    items = admin.get("/api/v1/roster", query_string={"test_id": test_id}).get_json()["data"]["items"]
    started = next(i for i in items if i["roll_number"] == "R-1")
    assert started["attempt"]["status"] == "in_progress" and started["attempt"]["score"] is None
    assert next(i for i in items if i["roll_number"] == "R-2")["attempt"] is None
    r = admin.delete(f"/api/v1/roster/{started['id']}")
    assert r.status_code == 409 and err(r) == "CANDIDATE_HAS_ATTEMPT"
    same = {k: started[k] for k in ("full_name", "email", "roll_number", "date_of_birth")}
    assert admin.put(f"/api/v1/roster/{started['id']}", json={**same, "full_name": "Candidate One"}).status_code == 200
    c.post("/api/v1/exam/submit")
    items = admin.get("/api/v1/roster", query_string={"test_id": test_id}).get_json()["data"]["items"]
    assert next(i for i in items if i["roll_number"] == "R-1")["attempt"]["status"] == "submitted"


def test_started_candidate_cannot_move_to_another_field(app):
    from tests.test_phase5 import make_test as two_field_test
    admin = make_admin(app)
    test_id, eng, med = two_field_test(app, admin)
    cand = {"test_id": test_id, "full_name": "Sana Fatima", "email": "sana@mail.com", "roll_number": "PE-1",
            "date_of_birth": "2008-01-01", "department_id": eng, "access_code": "CAND0001"}
    cid = admin.post("/api/v1/roster", json=cand).get_json()["data"]["candidate"]["id"]
    set_window(app, test_id, -5, 60)
    candidate(app).post("/api/v1/exam/start")
    r = admin.put(f"/api/v1/roster/{cid}", json={**cand, "department_id": med})
    assert r.status_code == 409 and err(r) == "CANDIDATE_HAS_ATTEMPT"
