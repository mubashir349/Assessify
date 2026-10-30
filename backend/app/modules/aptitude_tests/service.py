"""Phase 4 business rules: build a test, check the 1.5x approved pool, schedule it and publish it.

Every query is filtered by the signed-in admin's institution_id (taken from the login, never from the request),
so another institution's test, department or subject id simply gives 404.
check_availability() is the ONLY place the pool rule lives: the wizard, GET /tests/<id> and publish all use it.
"""
import math
from datetime import date, datetime, timezone

from sqlalchemy import func

from app.common.errors import ApiError
from app.common.utils import utcnow
from app.common.validation import raise_if, text
from app.extensions import db
from app.models.aptitude_test import (ANY_DIFFICULTY, MAX_DURATION, MAX_PER_ROW, MIN_DURATION, POOL_FACTOR,
                                      RESULT_RELEASES, TEST_STATUSES, TIMING_MODES, AptitudeTest, Composition,
                                      Schedule)
from app.models.department import LEVELS, Department
from app.models.question import DIFFICULTIES, QUESTION_TYPES, Question
from app.models.user import User

ROW_DIFFICULTIES = (ANY_DIFFICULTY, *DIFFICULTIES)


# ---------------------------------------------------------------- reading
def get_test(institution_id: int, test_id: int) -> AptitudeTest:
    test = AptitudeTest.query.filter_by(id=test_id, institution_id=institution_id).first()
    if test is None:
        raise ApiError("NOT_FOUND", "Test not found.", 404)
    return test


def list_tests(institution_id: int, args) -> list[AptitudeTest]:
    q = AptitudeTest.query.filter_by(institution_id=institution_id)
    status, level, search = args.get("status"), args.get("level"), (args.get("q") or "").strip()
    if status:
        if status not in TEST_STATUSES:
            raise ApiError("BAD_REQUEST", "Unknown status filter.", 400)
        q = q.filter(AptitudeTest.status == status)
    if level:
        if level not in LEVELS:
            raise ApiError("BAD_REQUEST", "Unknown level filter.", 400)
        q = q.filter(AptitudeTest.level == level)
    if search:
        q = q.filter(AptitudeTest.name.ilike(f"%{search}%"))
    return q.order_by(AptitudeTest.created_at.desc(), AptitudeTest.id.desc()).all()


# ---------------------------------------------------------------- validation
def _count(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n == value or isinstance(value, str) else None


def clean_compositions(institution_id: int, level, raw, errors: dict) -> list[tuple[Department, list[dict]]]:
    """[{department_id, rows: [{subject, question_type, difficulty, count}]}] -> [(Department, [clean rows])].
    Records the first problem in errors["compositions"]; a department of another institution raises 404."""
    def bad(msg):
        errors.setdefault("compositions", msg)

    if not isinstance(raw, list) or not raw:
        bad("Select at least one field / department.")
        return []
    groups, seen_depts = [], set()
    for item in raw:
        if not isinstance(item, dict):
            bad("Each composition must be an object.")
            continue
        dept_id = _count(item.get("department_id"))
        if dept_id is None:
            bad("department_id must be a number.")
            continue
        dept = Department.query.filter_by(id=dept_id, institution_id=institution_id).first()
        if dept is None:
            raise ApiError("NOT_FOUND", "Field / department not found.", 404)
        if dept.id in seen_depts:
            bad(f"{dept.name} is selected twice.")
            continue
        seen_depts.add(dept.id)
        if level in LEVELS and dept.level != level:
            bad(f"{dept.name} is a {dept.level} {LEVELS[dept.level]['term'].lower()}, not {level}.")
            continue
        subjects = {s.name.lower(): s.name for s in dept.subjects}
        rows_in = item.get("rows")
        if not isinstance(rows_in, list) or not rows_in:
            bad(f"{dept.name} needs at least one subject row.")
            continue
        rows, keys = [], set()
        for r in rows_in:
            r = r if isinstance(r, dict) else {}
            subject = subjects.get(str(r.get("subject") or "").strip().lower())
            qtype, diff, count = r.get("question_type"), r.get("difficulty"), _count(r.get("count"))
            if subject is None:
                bad(f"{dept.name}: choose one of its subjects.")
            elif qtype not in QUESTION_TYPES:
                bad(f"{dept.name} → {subject}: question type must be one of " + ", ".join(QUESTION_TYPES) + ".")
            elif diff not in ROW_DIFFICULTIES:
                bad(f"{dept.name} → {subject}: difficulty must be one of " + ", ".join(ROW_DIFFICULTIES) + ".")
            elif count is None or not 1 <= count <= MAX_PER_ROW:
                bad(f"{dept.name} → {subject}: questions per candidate must be between 1 and {MAX_PER_ROW}.")
            elif (subject.lower(), qtype, diff) in keys:
                bad(f"{dept.name} → {subject}: two rows have the same type and difficulty. Merge them into one row.")
            else:
                keys.add((subject.lower(), qtype, diff))
                rows.append({"subject": subject, "question_type": qtype, "difficulty": diff, "count": count})
        groups.append((dept, rows))
    return groups


def _parse_utc(value, key: str, label: str, errors: dict) -> datetime | None:
    """'2026-11-05T09:00:00Z' (or any ISO time with an offset) -> naive UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        errors[key] = f"{label} is required."
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        errors[key] = f"{label} must be an ISO date-time, e.g. 2026-11-05T09:00:00Z."
        return None
    if dt.tzinfo is None:
        errors[key] = f"{label} must include a timezone (send UTC with a trailing Z)."
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def clean_schedule(raw, errors: dict) -> dict:
    s = raw if isinstance(raw, dict) else {}
    out: dict = {}
    mode = s.get("timing_mode")
    if mode not in TIMING_MODES:
        errors["schedule.timing_mode"] = "Choose one of: " + ", ".join(TIMING_MODES) + "."
    starts = _parse_utc(s.get("starts_at"), "schedule.starts_at", "Start time", errors)
    ends = _parse_utc(s.get("ends_at"), "schedule.ends_at", "End time", errors)
    window = None
    if starts and ends:
        if ends <= starts:
            errors["schedule.ends_at"] = "End time must be after the start time."
        else:
            window = int((ends - starts).total_seconds() // 60)

    if mode == "fixed" and window is not None:
        duration = window
        if not MIN_DURATION <= duration <= MAX_DURATION:
            errors["schedule.ends_at"] = f"A fixed-time test must last {MIN_DURATION}–{MAX_DURATION} minutes."
    else:
        duration = _count(s.get("duration_minutes"))
        if mode == "flexible":
            if duration is None or not MIN_DURATION <= duration <= MAX_DURATION:
                errors["schedule.duration_minutes"] = f"Time limit must be {MIN_DURATION}–{MAX_DURATION} minutes."
            elif window is not None and duration > window:
                errors["schedule.duration_minutes"] = (f"Time limit ({duration} min) is longer than the window "
                                                       f"({window} min).")

    release = s.get("result_release")
    release_on = None
    if release not in RESULT_RELEASES:
        errors["schedule.result_release"] = "Choose one of: " + ", ".join(RESULT_RELEASES) + "."
    elif release == "scheduled":
        try:
            release_on = date.fromisoformat(str(s.get("release_on") or ""))
        except ValueError:
            errors["schedule.release_on"] = "Choose the date results are released (YYYY-MM-DD)."
        else:
            if ends and release_on < ends.date():
                errors["schedule.release_on"] = "Results can't be released before the test ends."

    out.update(timing_mode=mode, starts_at=starts, ends_at=ends, duration_minutes=duration,
               result_release=release, release_on=release_on)
    return out


def _clean(institution_id: int, data: dict) -> dict:
    errors: dict = {}
    name = text(data, "name", "Test name", errors, min_len=3, max_len=200)
    level = data.get("level")
    if level not in LEVELS:
        errors["level"] = "Choose one of: " + ", ".join(LEVELS) + "."
    groups = clean_compositions(institution_id, level, data.get("compositions"), errors)
    schedule = clean_schedule(data.get("schedule"), errors)
    raise_if(errors)
    return {"name": name, "level": level, "groups": groups, "schedule": schedule}


# ---------------------------------------------------------------- the 1.5x pool rule
def needed_for(count: int) -> int:
    return math.ceil(count * POOL_FACTOR)


def check_availability(institution_id: int, level: str, groups: list[tuple[Department, list[dict]]]) -> dict:
    """For every row: needed = ceil(count x 1.5) vs approved questions with the same department, subject, type and
    difficulty ('any' = every difficulty). Rows that share a subject + type draw from the same questions, so they are
    also checked together against the approved total of the difficulties they cover."""
    dept_ids = [d.id for d, _ in groups]
    counts: dict = {}
    if dept_ids:
        found = (db.session.query(Question.department_id, func.lower(Question.subject_name), Question.question_type,
                                  Question.difficulty, func.count(Question.id))
                 .filter(Question.institution_id == institution_id, Question.status == "approved",
                         Question.level == level, Question.department_id.in_(dept_ids))
                 .group_by(Question.department_id, func.lower(Question.subject_name), Question.question_type,
                           Question.difficulty).all())
        counts = {(dep, subj, qt, diff): n for dep, subj, qt, diff, n in found}

    def pool(dept_id, subject, qtype, diffs) -> int:
        return sum(counts.get((dept_id, subject.lower(), qtype, d), 0) for d in diffs)

    def covers(diff):
        return tuple(DIFFICULTIES) if diff == ANY_DIFFICULTY else (diff,)

    def label(dept, subject, qtype, diff):
        diff_label = "Any difficulty" if diff == ANY_DIFFICULTY else DIFFICULTIES.get(diff, diff)
        return f"{dept.name} → {subject} · {QUESTION_TYPES[qtype]}, {diff_label}"

    rows_out, shortfalls = [], []
    for dept, rows in groups:
        shared: dict = {}
        for r in rows:
            needed = needed_for(r["count"])
            have = pool(dept.id, r["subject"], r["question_type"], covers(r["difficulty"]))
            item = {"department_id": dept.id, "department": dept.name, **r, "needed": needed, "pool": have,
                    "short": max(0, needed - have), "sufficient": have >= needed}
            rows_out.append(item)
            if not item["sufficient"]:
                shortfalls.append({**item, "label": label(dept, r["subject"], r["question_type"], r["difficulty"])})
            shared.setdefault((r["subject"], r["question_type"]), []).append((r, needed))
        for (subject, qtype), group in shared.items():
            if len(group) < 2 or any(not x["sufficient"] for x in rows_out
                                     if x["department_id"] == dept.id and x["subject"] == subject
                                     and x["question_type"] == qtype):
                continue   # a single row, or already reported row by row
            diffs = sorted({d for r, _ in group for d in covers(r["difficulty"])})
            needed, have = sum(n for _, n in group), pool(dept.id, subject, qtype, diffs)
            if have < needed:
                shortfalls.append({"department_id": dept.id, "department": dept.name, "subject": subject,
                                   "question_type": qtype, "difficulty": "combined", "count": sum(r["count"] for r, _ in group),
                                   "needed": needed, "pool": have, "short": needed - have, "sufficient": False,
                                   "label": f"{dept.name} → {subject} · {QUESTION_TYPES[qtype]}, all rows together "
                                            f"(they share the same questions)"})
    return {"pool_factor": POOL_FACTOR, "all_sufficient": not shortfalls, "rows": rows_out, "shortfalls": shortfalls}


def preview_availability(institution_id: int, data: dict) -> dict:
    """POST /tests/availability - used live by the wizard; nothing is saved."""
    errors: dict = {}
    level = data.get("level")
    if level not in LEVELS:
        errors["level"] = "Choose one of: " + ", ".join(LEVELS) + "."
    groups = clean_compositions(institution_id, level, data.get("compositions"), errors)
    raise_if(errors)
    return check_availability(institution_id, level, groups)


def _groups_of(test: AptitudeTest) -> list[tuple[Department, list[dict]]]:
    return [(d, [{"subject": r.subject_name, "question_type": r.question_type, "difficulty": r.difficulty,
                  "count": r.question_count} for r in test.rows if r.department_id == d.id]) for d in test.departments()]


def availability_of(test: AptitudeTest) -> dict:
    return check_availability(test.institution_id, test.level, _groups_of(test))


# ---------------------------------------------------------------- writing
def _apply(test: AptitudeTest, clean: dict) -> None:
    test.name, test.level = clean["name"], clean["level"]
    test.rows = [Composition(department_id=dept.id, subject_name=r["subject"], question_type=r["question_type"],
                             difficulty=r["difficulty"], question_count=r["count"], position=i)
                 for i, (dept, r) in enumerate((d, r) for d, rows in clean["groups"] for r in rows)]
    if test.schedule is None:
        test.schedule = Schedule()
    for key, value in clean["schedule"].items():
        setattr(test.schedule, key, value)
    test.updated_at = utcnow()


def _require_draft(test: AptitudeTest) -> None:
    if test.status != "draft":
        raise ApiError("TEST_LOCKED", "A published test can't be changed or deleted.", 409)


def create_test(user: User, data: dict) -> AptitudeTest:
    clean = _clean(user.institution_id, data)
    test = AptitudeTest(institution_id=user.institution_id, created_by_id=user.id, status="draft")
    _apply(test, clean)
    db.session.add(test)
    db.session.commit()
    return test


def update_test(institution_id: int, test_id: int, data: dict) -> AptitudeTest:
    test = get_test(institution_id, test_id)
    _require_draft(test)
    clean = _clean(institution_id, data)
    test.rows = []
    db.session.flush()   # remove the old rows first so the unique (row) constraint never sees old + new together
    _apply(test, clean)
    db.session.commit()
    return test


def delete_test(institution_id: int, test_id: int) -> None:
    test = get_test(institution_id, test_id)
    _require_draft(test)
    db.session.delete(test)
    db.session.commit()


def publish_test(institution_id: int, test_id: int) -> AptitudeTest:
    """Re-checks everything on the server: the disabled button in the browser is only a convenience."""
    test = get_test(institution_id, test_id)
    if test.status != "draft":
        raise ApiError("INVALID_TRANSITION", "This test is already published.", 409)
    # The stored test is re-validated as if it were sent again (departments / subjects may have changed since).
    _clean(institution_id, {"name": test.name, "level": test.level,
                            "compositions": [{"department_id": d.id, "rows": rows} for d, rows in _groups_of(test)],
                            "schedule": test.schedule.to_dict() if test.schedule else None})
    if test.schedule.starts_at <= utcnow():
        raise ApiError("SCHEDULE_IN_PAST", "The start time has already passed. Choose a later date or time.", 422,
                       {"schedule.starts_at": "The start time has already passed."})
    avail = availability_of(test)
    if not avail["all_sufficient"]:
        n = len(avail["shortfalls"])
        raise ApiError("POOL_TOO_SMALL", f"Publishing is blocked: {n} subject row(s) don't have enough approved "
                       f"questions ({POOL_FACTOR}× the questions per candidate).", 409,
                       {"shortfalls": avail["shortfalls"]})
    test.status, test.published_at = "published", utcnow()
    db.session.commit()
    return test


# ---------------------------------------------------------------- guards used by Phase 2 (departments)
def tests_using(department_id: int) -> list[Composition]:
    return Composition.query.filter_by(department_id=department_id).all()
