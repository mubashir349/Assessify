"""Phase 6 - taking the test. Every rule that decides time, paper and score lives here, on the server.

Time gate
    start before the test's start time      -> 403 TEST_NOT_STARTED (details: starts_at, seconds_left)
    start at / after the end time            -> 403 TEST_CLOSED
    fixed     : deadline = the test's end time, so a late starter simply gets less time
    flexible  : deadline = start + duration, never after the window's end
Paper
    drawn once, at start, from APPROVED questions matching each composition row of the candidate's field
    (department + subject + type + difficulty, 'any' = all three). Random selection, random order inside each
    subject, random MCQ option order. Rows that share questions never repeat one on the same paper.
Answers
    saved one by one. After the deadline -> the attempt is submitted ("time_up") and 409 TIME_UP; nothing is changed.
    While locked -> 423 ATTEMPT_LOCKED. After submitting -> 409 ALREADY_SUBMITTED.
Auto-submit
    no background job is needed: any request that touches an attempt past its deadline submits it first
    (finalize_if_overdue). The test page also calls submit when its timer reaches zero.
Scoring
    on submit, on the server: an answer is correct when the chosen ORIGINAL option index equals the question's
    correct_index. The correct answers never leave the server in any candidate response.
"""
import secrets
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from app.common.errors import ApiError
from app.common.utils import iso, utcnow
from app.extensions import db
from app.models.aptitude_test import ANY_DIFFICULTY
from app.models.candidate import Candidate
from app.models.exam import LOCK_REASONS, ExamAttempt, LockEvent, PaperItem
from app.models.question import DIFFICULTIES, Question

_rng = secrets.SystemRandom()


# ------------------------------------------------------------------------------------------------ helpers
def attempt_of(candidate: Candidate) -> ExamAttempt | None:
    return ExamAttempt.query.filter_by(candidate_id=candidate.id).first()


def _require_attempt(candidate: Candidate) -> ExamAttempt:
    attempt = attempt_of(candidate)
    if attempt is None:
        raise ApiError("ATTEMPT_NOT_STARTED", "You have not started this test yet.", 409)
    return attempt


def _overdue(attempt: ExamAttempt, now) -> bool:
    if attempt.status == "submitted":
        return False
    sc = attempt.test.schedule
    if attempt.status == "locked" and sc.timing_mode == "flexible":
        return now >= sc.ends_at          # timer frozen, but the window still closes for everyone
    return now >= attempt.deadline_at


def finalize_if_overdue(attempt: ExamAttempt | None, now=None) -> bool:
    """Auto-submit: call before acting on an attempt. Returns True when it was submitted just now."""
    now = now or utcnow()
    if attempt is None or not _overdue(attempt, now):
        return False
    _score_and_submit(attempt, "time_up", now)
    db.session.commit()
    return True


def _score_and_submit(attempt: ExamAttempt, reason: str, now) -> None:
    score = correct = answered = 0
    for item in attempt.items:
        item.is_correct = item.answer_index is not None and item.answer_index == item.question.correct_index
        answered += item.answer_index is not None
        if item.is_correct:
            correct += 1
            score += item.marks
    attempt.score, attempt.correct_count, attempt.answered_count = score, correct, answered
    attempt.max_score = sum(i.marks for i in attempt.items)
    attempt.status, attempt.submitted_at, attempt.submit_reason = "submitted", now, reason
    attempt.locked_at = None


# ------------------------------------------------------------------------------------------------ gate
def gate(candidate: Candidate, now=None) -> dict:
    """What the start page needs: can this candidate start now, and if not, why. Uses the SERVER clock."""
    now = now or utcnow()
    sc = candidate.test.schedule
    attempt = attempt_of(candidate)
    finalize_if_overdue(attempt, now)
    if attempt is not None:
        state = "submitted" if attempt.status == "submitted" else "resume"
    elif now < sc.starts_at:
        state = "not_started"
    elif now >= sc.ends_at:
        state = "closed"
    else:
        state = "open"
    return {
        "state": state,                                   # not_started | open | resume | submitted | closed
        "can_start": state in ("open", "resume"),
        "server_now": iso(now),
        "starts_at": iso(sc.starts_at),
        "ends_at": iso(sc.ends_at),
        "seconds_until_start": max(0, int((sc.starts_at - now).total_seconds())),
        "timing_mode": sc.timing_mode,
        "duration_minutes": sc.duration_minutes,
        # what a candidate starting NOW would get (fixed: only the time left until the end)
        "minutes_if_started_now": max(0, int((_deadline_for(sc, max(now, sc.starts_at)) - max(now, sc.starts_at))
                                             .total_seconds() // 60)),
        "attempt": attempt.to_dict(now) if attempt else None,
    }


def _deadline_for(sc, started_at):
    if sc.timing_mode == "fixed":
        return sc.ends_at
    return min(started_at + timedelta(minutes=sc.duration_minutes), sc.ends_at)


# ------------------------------------------------------------------------------------------------ paper
def _covers(diff: str) -> tuple:
    return tuple(DIFFICULTIES) if diff == ANY_DIFFICULTY else (diff,)


def build_paper(candidate: Candidate) -> list[tuple[Question, str]]:
    """Random questions for every composition row of the candidate's field: [(question, subject)] in paper order.

    Specific-difficulty rows draw first, then 'any' rows, so an 'any' row can't use up the only easy questions a
    'easy' row needs. A question is never used twice on one paper."""
    test = candidate.test
    rows = [r for r in test.rows if r.department_id == candidate.department_id]
    if not rows:
        raise ApiError("PAPER_UNAVAILABLE", "Your field has no questions in this test. Please contact your proctor.", 409)
    used: set[int] = set()
    picked: dict[int, list[Question]] = {}
    for r in sorted(rows, key=lambda r: (r.difficulty == ANY_DIFFICULTY, r.position)):
        pool = (Question.query
                .filter(Question.institution_id == test.institution_id, Question.status == "approved",
                        Question.level == test.level, Question.department_id == r.department_id,
                        db.func.lower(Question.subject_name) == r.subject_name.lower(),
                        Question.question_type == r.question_type, Question.difficulty.in_(_covers(r.difficulty)))
                .all())
        pool = [q for q in pool if q.id not in used]
        if len(pool) < r.question_count:
            raise ApiError("PAPER_UNAVAILABLE", "Not enough questions are available to build your paper. "
                           "Please contact your proctor.", 409)
        chosen = _rng.sample(pool, r.question_count)
        used.update(q.id for q in chosen)
        picked[r.id] = chosen

    # Paper order: subjects in the order the test lists them; questions shuffled inside each subject.
    by_subject: dict[str, list[Question]] = {}
    for r in rows:
        by_subject.setdefault(r.subject_name, []).extend(picked[r.id])
    paper = []
    for subject, qs in by_subject.items():
        _rng.shuffle(qs)
        paper.extend((q, subject) for q in qs)
    return paper


def _option_order(q: Question) -> list[int]:
    order = list(range(len(q.options or [])))
    if q.question_type == "mcq":          # True / False keeps its natural order
        _rng.shuffle(order)
    return order


def start(candidate: Candidate, now=None) -> ExamAttempt:
    """Pressing Start. Pressing it again (reload, lost connection) returns the same attempt and paper."""
    now = now or utcnow()
    attempt = attempt_of(candidate)
    if attempt is not None:
        finalize_if_overdue(attempt, now)
        if attempt.status == "submitted":
            raise ApiError("ALREADY_SUBMITTED", "You have already submitted this test.", 409)
        return attempt

    sc = candidate.test.schedule
    if now < sc.starts_at:
        seconds = int((sc.starts_at - now).total_seconds())
        raise ApiError("TEST_NOT_STARTED", "The test has not started yet. Please wait for the start time.", 403,
                       {"starts_at": iso(sc.starts_at), "seconds_left": seconds})
    if now >= sc.ends_at:
        raise ApiError("TEST_CLOSED", "This test has ended.", 403)

    attempt = ExamAttempt(candidate_id=candidate.id, test_id=candidate.test_id, status="in_progress",
                          started_at=now, deadline_at=_deadline_for(sc, now))
    for n, (q, subject) in enumerate(build_paper(candidate), start=1):
        attempt.items.append(PaperItem(question_id=q.id, question=q, position=n, subject_name=subject,
                                       option_order=_option_order(q), marks=q.marks or 1))
    attempt.max_score = sum(i.marks for i in attempt.items)
    db.session.add(attempt)
    try:
        db.session.commit()
    except IntegrityError:            # a double click started it twice at the same moment: keep the first one
        db.session.rollback()
        return _require_attempt(candidate)
    return attempt


def current(candidate: Candidate) -> ExamAttempt:
    attempt = _require_attempt(candidate)
    finalize_if_overdue(attempt)
    return attempt


# ------------------------------------------------------------------------------------------------ answers / lock / submit
def _require_open(attempt: ExamAttempt, now) -> None:
    if finalize_if_overdue(attempt, now):
        raise ApiError("TIME_UP", "Time is up. Your test was submitted with the answers saved before the end time.", 409)
    if attempt.status == "submitted":
        raise ApiError("ALREADY_SUBMITTED", "You have already submitted this test.", 409)
    if attempt.status == "locked":
        raise ApiError("ATTEMPT_LOCKED", "Your test is locked. Please ask your proctor to unlock it.", 423)


def save_answer(candidate: Candidate, number: int, data: dict, now=None) -> PaperItem:
    """{choice: 0-based position as shown | null (clear), flagged?: bool}. Either key may be left out."""
    now = now or utcnow()
    attempt = _require_attempt(candidate)
    _require_open(attempt, now)
    item = next((i for i in attempt.items if i.position == number), None)
    if item is None:
        raise ApiError("NOT_FOUND", "There is no such question on your paper.", 404)

    errors = {}
    if "choice" in data:
        choice = data["choice"]
        if choice is None:
            item.answer_index, item.answered_at = None, now
        elif isinstance(choice, bool) or not isinstance(choice, int) or not 0 <= choice < len(item.option_order):
            errors["choice"] = f"choice must be a number from 0 to {len(item.option_order) - 1}, or null to clear."
        else:
            item.answer_index, item.answered_at = item.option_order[choice], now
    if "flagged" in data:
        if not isinstance(data["flagged"], bool):
            errors["flagged"] = "flagged must be true or false."
        else:
            item.flagged = data["flagged"]
    if not errors and "choice" not in data and "flagged" not in data:
        errors["choice"] = "Send choice and/or flagged."
    if errors:
        db.session.rollback()
        raise ApiError("VALIDATION_ERROR", "Please fix the highlighted fields.", 422, errors)
    db.session.commit()
    return item


def lock(candidate: Candidate, reason, now=None) -> ExamAttempt:
    """The browser reports a fullscreen exit / tab switch. Locking twice is harmless (one event)."""
    now = now or utcnow()
    attempt = _require_attempt(candidate)
    if finalize_if_overdue(attempt, now) or attempt.status != "in_progress":
        return attempt
    reason = reason if reason in LOCK_REASONS else "other"
    attempt.status, attempt.locked_at = "locked", now
    attempt.lock_count = (attempt.lock_count or 0) + 1
    attempt.events.append(LockEvent(kind="lock", reason=reason, created_at=now))
    db.session.commit()
    return attempt


def unlock(attempt: ExamAttempt, user, now=None) -> ExamAttempt:
    """Institution Admin unlocks (Phase 7's monitor calls this). Flexible: the frozen minutes are given back,
    never past the window's end. Fixed: the end time never moves."""
    now = now or utcnow()
    if finalize_if_overdue(attempt, now):
        raise ApiError("TIME_UP", "Time is up; the attempt was submitted.", 409)
    if attempt.status != "locked":
        raise ApiError("INVALID_TRANSITION", "This attempt is not locked.", 409)
    sc = attempt.test.schedule
    if sc.timing_mode == "flexible":
        attempt.deadline_at = min(attempt.deadline_at + (now - attempt.locked_at), sc.ends_at)
    attempt.status, attempt.locked_at = "in_progress", None
    attempt.events.append(LockEvent(kind="unlock", by_user_id=user.id, created_at=now))
    db.session.commit()
    return attempt


def submit(candidate: Candidate, now=None) -> ExamAttempt:
    """The candidate presses Submit, or their timer reached zero. A locked attempt can't be submitted by the
    candidate (it is submitted automatically when time runs out). Submitting twice returns the same result."""
    now = now or utcnow()
    attempt = _require_attempt(candidate)
    if finalize_if_overdue(attempt, now) or attempt.status == "submitted":
        return attempt
    if attempt.status == "locked":
        raise ApiError("ATTEMPT_LOCKED", "Your test is locked. Please ask your proctor to unlock it.", 423)
    _score_and_submit(attempt, "candidate", now)
    db.session.commit()
    return attempt


# ------------------------------------------------------------------------------------------------ result
def result(candidate: Candidate, now=None) -> dict:
    """After submitting. The score is shown only when the test releases results immediately; otherwise the page
    says it will be emailed (Phase 7 sends the emails). Never shows which questions were right or the answers."""
    now = now or utcnow()
    attempt = _require_attempt(candidate)
    finalize_if_overdue(attempt, now)
    if attempt.status != "submitted":
        raise ApiError("NOT_SUBMITTED", "Your test has not been submitted yet.", 409)
    sc = attempt.test.schedule
    data = {
        "attempt": attempt.to_dict(now),
        "release": sc.result_release,
        "release_on": sc.release_on.isoformat() if sc.release_on else None,
        "email": candidate.email,
        "score": None,
    }
    if sc.result_release == "immediate":
        subjects: dict[str, dict] = {}
        for i in attempt.items:
            s = subjects.setdefault(i.subject_name, {"subject": i.subject_name, "score": 0, "max_score": 0,
                                                      "correct": 0, "questions": 0})
            s["questions"] += 1
            s["max_score"] += i.marks
            if i.is_correct:
                s["correct"] += 1
                s["score"] += i.marks
        data["score"] = {
            "score": attempt.score, "max_score": attempt.max_score,
            "percent": round(100 * attempt.score / attempt.max_score, 1) if attempt.max_score else 0.0,
            "correct": attempt.correct_count, "answered": attempt.answered_count, "questions": len(attempt.items),
            "by_subject": list(subjects.values()),
        }
    return data


# ------------------------------------------------------------------------------------------------ Phase 7 (monitor)
def mark_seen(candidate: Candidate, now=None) -> None:
    """One small UPDATE: the candidate's page is still talking to the server."""
    (ExamAttempt.query.filter(ExamAttempt.candidate_id == candidate.id, ExamAttempt.status != "submitted")
     .update({ExamAttempt.last_seen_at: now or utcnow()}, synchronize_session=False))
    db.session.commit()


def end_by_admin(attempt: ExamAttempt, now=None) -> ExamAttempt:
    """The proctor ends a candidate's test from the monitor: scored with the answers saved so far."""
    now = now or utcnow()
    if finalize_if_overdue(attempt, now) or attempt.status == "submitted":
        raise ApiError("ALREADY_SUBMITTED", "This attempt is already submitted.", 409)
    _score_and_submit(attempt, "admin", now)
    db.session.commit()
    return attempt
