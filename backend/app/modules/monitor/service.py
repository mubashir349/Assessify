"""Phase 7 - live monitor. One snapshot of every candidate on a published test, read by the page every few seconds.

Monitor status of a candidate (worked out here, not stored):
    not_started     no attempt yet
    in_progress     answering, and the page talked to the server in the last MONITOR_DISCONNECTED_SECONDS
    disconnected    in progress, but nothing arrived for longer (closed laptop, lost Wi-Fi, ...)
    locked          left fullscreen / switched tab; waits for the proctor's Unlock
    auto_submitted  submitted because the time ran out
    completed       submitted by the candidate, or ended by the proctor (submit_reason = admin)

Overdue attempts are submitted before the snapshot is built (finalize_if_overdue), so a timer that ran out while
the candidate was offline shows as auto_submitted. Access codes and dates of birth are never part of the snapshot.
"""
from sqlalchemy import func

from app.common.errors import ApiError
from app.common.utils import iso, utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import Candidate
from app.models.exam import LOCK_REASONS, ExamAttempt
from app.modules.exam.service import finalize_if_overdue
from app.modules.roster.service import published_test

MONITOR_STATUSES = ("not_started", "in_progress", "disconnected", "locked", "auto_submitted", "completed")


def test_state(test: AptitudeTest, now) -> str:
    sc = test.schedule
    if now < sc.starts_at:
        return "upcoming"
    if now >= sc.ends_at:
        return "ended"
    return "live"


def list_tests(institution_id: int, now=None) -> list[dict]:
    """Published tests for the test picker: live first, then upcoming (soonest first), then ended (latest first)."""
    now = now or utcnow()
    tests = AptitudeTest.query.filter_by(institution_id=institution_id, status="published").all()
    order = {"live": 0, "upcoming": 1, "ended": 2}
    tests.sort(key=lambda t: (order[test_state(t, now)], _sort_time(t, now)))
    counts = _candidate_counts([t.id for t in tests])
    return [{"id": t.id, "name": t.name, "level": t.level, "state": test_state(t, now),
             "starts_at": iso(t.schedule.starts_at), "ends_at": iso(t.schedule.ends_at),
             "timing_mode": t.schedule.timing_mode, "candidates": counts.get(t.id, 0)} for t in tests]


def _sort_time(test: AptitudeTest, now) -> float:
    sc = test.schedule
    if test_state(test, now) == "ended":
        return -sc.ends_at.timestamp()
    return sc.starts_at.timestamp()


def _candidate_counts(test_ids: list[int]) -> dict:
    if not test_ids:
        return {}
    rows = (db.session.query(Candidate.test_id, func.count(Candidate.id))
            .filter(Candidate.test_id.in_(test_ids)).group_by(Candidate.test_id).all())
    return dict(rows)


def monitor_status(attempt: ExamAttempt | None, now, offline_after: int) -> str:
    if attempt is None:
        return "not_started"
    if attempt.status == "locked":
        return "locked"
    if attempt.status == "submitted":
        return "auto_submitted" if attempt.submit_reason == "time_up" else "completed"
    seen = attempt.last_seen_at or attempt.started_at
    return "disconnected" if (now - seen).total_seconds() > offline_after else "in_progress"


def _last_lock_reason(attempt: ExamAttempt) -> str | None:
    locks = [e for e in attempt.events if e.kind == "lock"]
    return LOCK_REASONS.get(locks[-1].reason, LOCK_REASONS["other"]) if locks else None


def _attempt_view(a: ExamAttempt, now) -> dict:
    answered = sum(1 for i in a.items if i.answer_index is not None)
    seen = a.last_seen_at or a.started_at
    return {
        "id": a.id, "reference": a.reference, "status": a.status,
        "started_at": iso(a.started_at), "deadline_at": iso(a.deadline_at),
        "remaining_seconds": 0 if a.status == "submitted" else a.remaining_seconds(now),
        "answered_count": answered, "question_count": len(a.items),
        "lock_count": a.lock_count, "locked_at": iso(a.locked_at), "lock_reason": _last_lock_reason(a),
        "submitted_at": iso(a.submitted_at), "submit_reason": a.submit_reason,
        "score": a.score, "max_score": a.max_score,
        "last_seen_at": iso(seen), "seconds_since_seen": max(0, int((now - seen).total_seconds())),
    }


def _row(c: Candidate, now, offline_after: int) -> dict:
    a = c.attempt
    return {
        "candidate_id": c.id, "full_name": c.full_name, "roll_number": c.roll_number, "email": c.email,
        "department": {"id": c.department.id, "name": c.department.name},
        "status": monitor_status(a, now, offline_after),
        "attempt": _attempt_view(a, now) if a else None,
    }


def _matches(row: dict, status: str, dept_id: int | None, search: str) -> bool:
    if status and row["status"] != status:
        return False
    if dept_id and row["department"]["id"] != dept_id:
        return False
    if not search:
        return True
    return any(search in (row[k] or "").lower() for k in ("full_name", "roll_number", "email"))


def _filters(args) -> tuple[str, int | None, str]:
    status = (args.get("status") or "").strip()
    if status and status not in MONITOR_STATUSES:
        raise ApiError("BAD_REQUEST", "Unknown status filter.", 400)
    dept = args.get("department_id")
    try:
        dept_id = int(dept) if dept else None
    except ValueError:
        raise ApiError("BAD_REQUEST", "department_id must be a number.", 400)
    return status, dept_id, (args.get("q") or "").strip().lower()


def snapshot(institution_id: int, args, offline_after: int, now=None) -> dict:
    """GET /monitor?test_id=&status=&department_id=&q= -> counts for the whole test + the filtered rows."""
    now = now or utcnow()
    status, dept_id, search = _filters(args)
    test = published_test(institution_id, args.get("test_id"))
    candidates = Candidate.query.filter_by(test_id=test.id).order_by(Candidate.roll_number, Candidate.id).all()
    for c in candidates:
        finalize_if_overdue(c.attempt, now)
    rows = [_row(c, now, offline_after) for c in candidates]
    counts = dict.fromkeys(MONITOR_STATUSES, 0)
    for r in rows:
        counts[r["status"]] += 1
    return {
        "test": {"id": test.id, "name": test.name, "level": test.level, "state": test_state(test, now),
                 "schedule": test.schedule.to_dict(),
                 "departments": [{"id": d.id, "name": d.name} for d in test.departments()]},
        "server_now": iso(now),
        "disconnected_after_seconds": offline_after,
        "counts": {"all": len(rows), **counts},
        "items": [r for r in rows if _matches(r, status, dept_id, search)],
    }
