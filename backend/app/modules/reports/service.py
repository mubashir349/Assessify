"""Phase 7 - reports for one published test: numbers, rule-based insights, CSV export and result emails.

Every number is worked out from the scored attempts (Phase 6 scores on the server at submit), so nothing is stored
twice. Percent = score / max_score x 100 of one attempt. Only SUBMITTED attempts count in averages.
"""
import csv
import io
import statistics

from sqlalchemy import extract

from app.common.errors import ApiError
from app.common.mailer import mail_ready
from app.common.utils import iso, utcnow
from app.models.aptitude_test import AptitudeTest, Schedule
from app.models.candidate import Candidate
from app.models.department import LEVELS
from app.modules.exam.service import finalize_if_overdue
from app.modules.monitor.service import test_state
from app.modules.roster.service import published_test

CANDIDATE_FILTERS = ("submitted", "in_progress", "not_attempted")
EMAIL_FILTERS = ("sent", "failed", "logged", "not_sent", "no_email")   # no_email: Phase 9, roster had none
BUCKETS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 101))
HARDEST_LIMIT = 5
CSV_RISKY_START = ("=", "+", "-", "@", "\t", "\r")


def percent(score, max_score) -> float:
    return round(100 * score / max_score, 1) if max_score else 0.0


def _avg(values: list) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


# ------------------------------------------------------------------------------------------------ test list
def _year(value) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ApiError("BAD_REQUEST", "year must be a number.", 400)


def list_tests(institution_id: int, args, now=None) -> list[dict]:
    """GET /reports/tests?q=&level=&year=  -> published tests, newest first, with a short summary each."""
    now = now or utcnow()
    q = AptitudeTest.query.join(Schedule).filter(AptitudeTest.institution_id == institution_id,
                                                 AptitudeTest.status == "published")
    search, level, year = (args.get("q") or "").strip(), args.get("level"), _year(args.get("year"))
    if search:
        q = q.filter(AptitudeTest.name.ilike(f"%{search}%"))
    if level:
        if level not in LEVELS:
            raise ApiError("BAD_REQUEST", "Unknown level filter.", 400)
        q = q.filter(AptitudeTest.level == level)
    if year:
        q = q.filter(extract("year", Schedule.starts_at) == year)
    tests = q.order_by(Schedule.starts_at.desc(), AptitudeTest.id.desc()).all()
    return [_test_card(t, now) for t in tests]


def _test_card(test: AptitudeTest, now) -> dict:
    candidates = Candidate.query.filter_by(test_id=test.id).all()
    for c in candidates:
        finalize_if_overdue(c.attempt, now)
    done = [c.attempt for c in candidates if c.attempt and c.attempt.status == "submitted"]
    return {"id": test.id, "name": test.name, "level": test.level, "state": test_state(test, now),
            "starts_at": iso(test.schedule.starts_at), "ends_at": iso(test.schedule.ends_at),
            "result_release": test.schedule.result_release,
            "candidates": len(candidates), "submitted": len(done),
            "average_percent": _avg([percent(a.score, a.max_score) for a in done])}


# ------------------------------------------------------------------------------------------------ one test
def _candidate_status(c: Candidate) -> str:
    if c.attempt is None:
        return "not_attempted"
    return "submitted" if c.attempt.status == "submitted" else "in_progress"


def _email_status(c: Candidate) -> str:
    mail = c.attempt.result_email if c.attempt else None
    return mail.status if mail else "not_sent"


def _candidate_row(c: Candidate) -> dict:
    a = c.attempt
    done = a is not None and a.status == "submitted"
    mail = a.result_email if a else None
    return {
        "candidate_id": c.id, "full_name": c.full_name, "roll_number": c.roll_number, "email": c.email,
        "department": {"id": c.department.id, "name": c.department.name},
        "status": _candidate_status(c),
        "attempt_id": a.id if a else None,
        "score": a.score if done else None, "max_score": a.max_score if done else None,
        "percent": percent(a.score, a.max_score) if done else None,
        "answered": a.answered_count if done else None, "questions": len(a.items) if a else None,
        "submitted_at": iso(a.submitted_at) if done else None, "submit_reason": a.submit_reason if done else None,
        "lock_count": a.lock_count if a else 0,
        "rank": None,
        "result_email": mail.to_dict() if mail else None,
    }


def _rank(rows: list[dict]) -> None:
    """Competition ranking on percent (90, 90, 80 -> 1, 1, 3). Not-submitted rows have no rank."""
    scored = sorted((r for r in rows if r["percent"] is not None), key=lambda r: -r["percent"])
    for i, r in enumerate(scored):
        same_as_previous = i > 0 and scored[i - 1]["percent"] == r["percent"]
        r["rank"] = scored[i - 1]["rank"] if same_as_previous else i + 1


def _summary(test: AptitudeTest, rows: list[dict], now) -> dict:
    pcts = [r["percent"] for r in rows if r["percent"] is not None]
    ended = test_state(test, now) == "ended"
    return {
        "candidates": len(rows),
        "submitted": len(pcts),
        "in_progress": sum(1 for r in rows if r["status"] == "in_progress"),
        "not_attempted": sum(1 for r in rows if r["status"] == "not_attempted"),
        "absent": sum(1 for r in rows if r["status"] == "not_attempted") if ended else 0,
        "auto_submitted": sum(1 for r in rows if r["submit_reason"] == "time_up"),
        "average_percent": _avg(pcts),
        "median_percent": round(statistics.median(pcts), 1) if pcts else None,
        "highest_percent": max(pcts) if pcts else None,
        "lowest_percent": min(pcts) if pcts else None,
        "distribution": [{"label": f"{lo}-{min(hi, 100)}%", "count": sum(1 for p in pcts if lo <= p < hi)}
                         for lo, hi in BUCKETS],
    }


def _by_department(test: AptitudeTest, rows: list[dict]) -> list[dict]:
    out = []
    for d in test.departments():
        mine = [r for r in rows if r["department"]["id"] == d.id]
        pcts = [r["percent"] for r in mine if r["percent"] is not None]
        out.append({"id": d.id, "name": d.name, "candidates": len(mine), "submitted": len(pcts),
                    "average_percent": _avg(pcts), "highest_percent": max(pcts) if pcts else None})
    return out


def _submitted_attempts(candidates: list[Candidate]) -> list:
    return [c.attempt for c in candidates if c.attempt and c.attempt.status == "submitted"]


def _by_subject(attempts: list) -> list[dict]:
    subjects: dict[str, dict] = {}
    for a in attempts:
        for i in a.items:
            s = subjects.setdefault(i.subject_name, {"subject": i.subject_name, "questions": 0, "correct": 0,
                                                      "unanswered": 0})
            s["questions"] += 1
            s["correct"] += bool(i.is_correct)
            s["unanswered"] += i.answer_index is None
    for s in subjects.values():
        s["accuracy_percent"] = percent(s["correct"], s["questions"])
    return sorted(subjects.values(), key=lambda s: s["accuracy_percent"])


def _hardest(attempts: list) -> list[dict]:
    """Questions answered correctly least often (asked at least twice, so one unlucky candidate doesn't count)."""
    seen: dict[int, dict] = {}
    for a in attempts:
        for i in a.items:
            q = seen.setdefault(i.question_id, {"question_id": i.question_id, "subject": i.subject_name,
                                                "text": i.question.text[:200], "difficulty": i.question.difficulty,
                                                "asked": 0, "correct": 0})
            q["asked"] += 1
            q["correct"] += bool(i.is_correct)
    items = [q for q in seen.values() if q["asked"] >= 2]
    for q in items:
        q["accuracy_percent"] = percent(q["correct"], q["asked"])
    return sorted(items, key=lambda q: (q["accuracy_percent"], -q["asked"]))[:HARDEST_LIMIT]


def insights(summary: dict, by_dept: list[dict], by_subject: list[dict], hardest: list[dict]) -> list[str]:
    """Plain rules, no AI: always available, and the AI summary builds on the same numbers."""
    if not summary["submitted"]:
        return ["No submitted attempts yet. Insights appear as soon as candidates submit."]
    tips = [f"{summary['submitted']} of {summary['candidates']} candidates submitted; the average score is "
            f"{summary['average_percent']}% (highest {summary['highest_percent']}%, lowest {summary['lowest_percent']}%)."]
    tips.extend(_subject_tips(by_subject))
    tips.extend(_department_tips(by_dept))
    if hardest and hardest[0]["accuracy_percent"] < 30:
        q = hardest[0]
        tips.append(f"Only {q['accuracy_percent']}% answered this {q['subject']} question correctly: "
                    f"\"{q['text'][:90]}\". Check that its answer key is right.")
    if summary["auto_submitted"]:
        tips.append(f"{summary['auto_submitted']} attempt(s) were submitted automatically when time ran out; "
                    f"consider whether the duration is long enough.")
    return tips


def _subject_tips(by_subject: list[dict]) -> list[str]:
    if len(by_subject) < 2:
        return []
    weak, strong = by_subject[0], by_subject[-1]
    tips = [f"Weakest subject: {weak['subject']} ({weak['accuracy_percent']}% correct). "
            f"Strongest: {strong['subject']} ({strong['accuracy_percent']}%)."]
    skipped = max(by_subject, key=lambda s: s["unanswered"] / s["questions"])
    if skipped["unanswered"] / skipped["questions"] >= 0.2:
        tips.append(f"{percent(skipped['unanswered'], skipped['questions'])}% of {skipped['subject']} questions "
                    f"were left unanswered.")
    return tips


def _department_tips(by_dept: list[dict]) -> list[str]:
    scored = [d for d in by_dept if d["average_percent"] is not None]
    if len(scored) < 2:
        return []
    low, high = min(scored, key=lambda d: d["average_percent"]), max(scored, key=lambda d: d["average_percent"])
    gap = round(high["average_percent"] - low["average_percent"], 1)
    if gap < 10:
        return []
    return [f"{high['name']} averages {gap} points more than {low['name']} "
            f"({high['average_percent']}% vs {low['average_percent']}%)."]


def _filter_rows(rows: list[dict], args) -> list[dict]:
    status, email = args.get("status") or "", args.get("email") or ""
    if status and status not in CANDIDATE_FILTERS:
        raise ApiError("BAD_REQUEST", "Unknown status filter.", 400)
    if email and email not in EMAIL_FILTERS:
        raise ApiError("BAD_REQUEST", "Unknown email filter.", 400)
    dept = args.get("department_id")
    try:
        dept_id = int(dept) if dept else None
    except ValueError:
        raise ApiError("BAD_REQUEST", "department_id must be a number.", 400)
    search = (args.get("q") or "").strip().lower()
    return [r for r in rows if _row_matches(r, status, email, dept_id, search)]


def _row_matches(r: dict, status: str, email: str, dept_id: int | None, search: str) -> bool:
    checks = (
        not status or r["status"] == status,
        not email or (r["status"] == "submitted" and mail_status(r) == email),
        not dept_id or r["department"]["id"] == dept_id,
        not search or any(search in (r[k] or "").lower() for k in ("full_name", "roll_number", "email")),
    )
    return all(checks)


def _sort_key(r: dict) -> tuple:
    return (r["rank"] is None, r["rank"] or 0, r["roll_number"] or "", r["full_name"])


def mail_status(r: dict) -> str:
    """sent / logged / failed / not_sent, or no_email when the roster has no email for this candidate."""
    if r["result_email"]:
        return r["result_email"]["status"]
    return "not_sent" if r["email"] else "no_email"


def load(institution_id: int, test_id, now=None) -> tuple[AptitudeTest, list[Candidate], list[dict]]:
    now = now or utcnow()
    test = published_test(institution_id, test_id)
    candidates = Candidate.query.filter_by(test_id=test.id).all()
    for c in candidates:
        finalize_if_overdue(c.attempt, now)
    rows = [_candidate_row(c) for c in candidates]
    _rank(rows)
    rows.sort(key=_sort_key)
    return test, candidates, rows


def stats(test: AptitudeTest, candidates: list[Candidate], rows: list[dict], now) -> dict:
    attempts = _submitted_attempts(candidates)
    summary = _summary(test, rows, now)
    by_dept, by_subject, hardest = _by_department(test, rows), _by_subject(attempts), _hardest(attempts)
    return {"summary": summary, "by_department": by_dept, "by_subject": by_subject, "hardest_questions": hardest,
            "insights": insights(summary, by_dept, by_subject, hardest)}


def email_overview(rows: list[dict], config) -> dict:
    ready, message = mail_ready(config)
    counts = dict.fromkeys(EMAIL_FILTERS, 0)
    for r in rows:
        if r["status"] == "submitted":
            counts[mail_status(r)] += 1
    return {"ready": ready, "message": message, "backend": config.get("MAIL_BACKEND", "console"), "counts": counts}


def report(institution_id: int, test_id, args, config, now=None) -> dict:
    """GET /reports/tests/<id>?department_id=&q=&status=&email="""
    now = now or utcnow()
    test, candidates, rows = load(institution_id, test_id, now)
    return {
        "test": {**_test_card(test, now), "timing_mode": test.schedule.timing_mode,
                 "release_on": test.schedule.release_on.isoformat() if test.schedule.release_on else None,
                 "departments": [{"id": d.id, "name": d.name} for d in test.departments()]},
        **stats(test, candidates, rows, now),
        "email": email_overview(rows, config),
        "candidates": _filter_rows(rows, args),
    }


# ------------------------------------------------------------------------------------------------ CSV
def _cell(value) -> str:
    """Spreadsheet-safe text: a cell starting with = + - @ would run as a formula in Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(CSV_RISKY_START) else text


def export_csv(institution_id: int, test_id, args) -> tuple[str, str]:
    test, _, rows = load(institution_id, test_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["rank", "name", "roll number", "email", "field", "status", "score", "max score", "percent",
                "answered", "questions", "submitted at (UTC)", "submitted by", "locks", "result email"])
    for r in _filter_rows(rows, args):
        mail = mail_status(r) if r["status"] == "submitted" else ""
        w.writerow([_cell(v) for v in (r["rank"], r["full_name"], r["roll_number"], r["email"],
                                       r["department"]["name"], r["status"], r["score"], r["max_score"],
                                       r["percent"], r["answered"], r["questions"], r["submitted_at"],
                                       r["submit_reason"], r["lock_count"], mail)])
    safe = "".join(ch if ch.isalnum() else "-" for ch in test.name).strip("-")[:60] or "test"
    return f"report-{safe}.csv", out.getvalue()
