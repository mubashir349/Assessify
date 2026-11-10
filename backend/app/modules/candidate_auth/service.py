"""Phase 5 candidate sign-in: one-time access code + date of birth. No account, no password.
Phase 9: a candidate the institution gave no date of birth signs in with the 6-digit PIN printed on their slip.
The login page has a "Date of birth | PIN" switch; the server accepts only the factor that candidate has, and a
wrong choice gets the same refusal as a wrong value, so the answer never tells which factor a code uses.

Refusals:
  wrong code OR wrong date of birth / PIN -> 401 INVALID_ACCESS_CODE (one message for all, so a code can't be confirmed)
  too many wrong tries               -> 429 TOO_MANY_ATTEMPTS (per code: guessing the date of birth of a leaked slip;
                                        per network address, looser: guessing codes. Exam halls share one address.)
  institution not approved any more  -> 403 INSTITUTION_NOT_ACTIVE
  the test's window has ended        -> 403 TEST_CLOSED
Before the start time the login works; the start page shows the countdown (Phase 6 enforces it on the server).

The failure counters live in this process's memory. That is enough for one server (python run.py / waitress);
several server processes would need a shared store (see app/common/throttle.py).
"""
import hmac
from datetime import timedelta

from flask import current_app

from app.common import throttle
from app.common.candidate import candidate_query
from app.common.errors import ApiError
from app.common.utils import utcnow
from app.extensions import commit_keep, db
from app.models.candidate import PIN_LENGTH, Candidate
from app.modules.roster.service import canonical_code, parse_dob

_TRY_LATER = "Too many wrong attempts. Wait {minutes} minute(s) and try again, or ask your proctor for help."


def reset_limits() -> None:
    throttle.reset()


def _second_factor(date_of_birth, pin, errors: dict):
    """("dob", date) or ("pin", "123456") from the login form; fills `errors` when neither is usable."""
    pin_text = "".join(str(pin or "").split())
    if pin_text:
        if not (pin_text.isdigit() and len(pin_text) == PIN_LENGTH):
            errors["pin"] = f"The PIN is {PIN_LENGTH} digits (it is on your test slip)."
        return "pin", pin_text
    if not str(date_of_birth or "").strip():
        errors["date_of_birth"] = "Enter your date of birth, or the PIN from your test slip."
        return "dob", None
    dob = parse_dob(date_of_birth)
    if dob is None:
        errors["date_of_birth"] = "Enter the date as YYYY-MM-DD."
    return "dob", dob


def _factor_matches(candidate: Candidate | None, kind: str, value) -> bool:
    if candidate is None:
        return False
    if candidate.date_of_birth is not None:
        return kind == "dob" and candidate.date_of_birth == value
    return kind == "pin" and bool(candidate.pin) and hmac.compare_digest(candidate.pin, value)


def authenticate(access_code, date_of_birth, remote_addr: str | None, pin=None) -> Candidate:
    errors = {}
    code = canonical_code(access_code)
    if not code:
        errors["access_code"] = "Enter the access code from your test slip."
    kind, value = _second_factor(date_of_birth, pin, errors)
    if errors:
        raise ApiError("VALIDATION_ERROR", "Please fix the highlighted fields.", 422, errors)

    cfg = current_app.config
    keys = [(f"code:{code}", cfg["CANDIDATE_LOGIN_MAX_FAILS"]), (f"ip:{remote_addr}", cfg["CANDIDATE_LOGIN_MAX_FAILS_PER_IP"])]
    throttle.check(keys, cfg["CANDIDATE_LOGIN_WINDOW_SECONDS"], _TRY_LATER)

    candidate = db.session.execute(candidate_query().where(Candidate.access_code == code)).unique().scalar_one_or_none()
    if not _factor_matches(candidate, kind, value):
        throttle.record_failure(keys)
        raise ApiError("INVALID_ACCESS_CODE", "Access code, date of birth or PIN is incorrect. Please check your test "
                       "slip and try again.", 401)

    check_can_continue(candidate)
    candidate.last_login_at = utcnow()
    candidate.login_count = (candidate.login_count or 0) + 1
    commit_keep()
    return candidate


def check_can_continue(candidate: Candidate, *, allow_ended: bool = False) -> None:
    """Re-checked on every candidate request, like the admin login: suspending an institution cuts candidates off."""
    if candidate.institution is None or candidate.institution.status != "approved":
        raise ApiError("INSTITUTION_NOT_ACTIVE", "This institution's tests are not available right now.", 403)
    test = candidate.test
    if test.status != "published" or test.schedule is None:
        raise ApiError("TEST_CLOSED", "This test is not available.", 403)
    if not allow_ended and utcnow() >= test.schedule.ends_at:
        raise ApiError("TEST_CLOSED", "This test has ended. Your access code is no longer valid.", 403)


def session_lifetime(candidate: Candidate) -> timedelta:
    """Until one hour after the test ends, but never more than CANDIDATE_SESSION_HOURS."""
    until_end = candidate.test.schedule.ends_at + timedelta(hours=1) - utcnow()
    cap = timedelta(hours=current_app.config["CANDIDATE_SESSION_HOURS"])
    return max(timedelta(minutes=5), min(until_end, cap))
