"""candidate_required - put it under a route that only a signed-in candidate may call (Phase 5, used by Phase 6).

The candidate's token travels in its own httpOnly cookie, so it never mixes with the admin login cookie."""
import hashlib
from functools import wraps

from flask import g, request
from flask_jwt_extended import decode_token
from jwt import ExpiredSignatureError
from sqlalchemy import select
from sqlalchemy.orm import joinedload, lazyload, selectinload

from app.common.errors import ApiError
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import Candidate
from app.models.department import Department
from app.models.exam import ExamAttempt, PaperItem
from app.models.institution import Institution
from app.models.question import Question

CANDIDATE_COOKIE = "candidate_token"
MSG_SIGN_IN = "Please sign in with your access code."


def code_version(access_code: str) -> str:
    """Short fingerprint of the access code, stored in the token: issuing a new code ends the old sessions."""
    return hashlib.sha256(access_code.encode()).hexdigest()[:12]


def candidate_query():
    """Phase 8 (load test): one round trip for what every exam request needs - the candidate, their test + schedule,
    field, institution and attempt with its paper. Lists nobody reads here (the institution's users, the field's
    subjects, the test's composition rows, lock events) stay unloaded until something asks for them."""
    # populate_existing: always the database's current state, even if an older copy is still in the session
    return select(Candidate).execution_options(populate_existing=True).options(
            joinedload(Candidate.test).options(lazyload(AptitudeTest.rows), joinedload(AptitudeTest.schedule)),
            joinedload(Candidate.department).lazyload(Department.subjects),
            joinedload(Candidate.institution).lazyload(Institution.users),
            selectinload(Candidate.attempt).options(
                lazyload(ExamAttempt.events), lazyload(ExamAttempt.result_email), lazyload(ExamAttempt.candidate),
                # the paper's questions without their long texts: scoring needs only the correct option
                selectinload(ExamAttempt.items).joinedload(PaperItem.question).load_only(
                    Question.id, Question.question_type, Question.correct_index)),
    )


def _load(candidate_id: int) -> Candidate | None:
    return db.session.execute(candidate_query().where(Candidate.id == candidate_id)).unique().scalar_one_or_none()


def load_current_candidate(*, allow_ended: bool = False) -> Candidate:
    from app.modules.candidate_auth.service import check_can_continue

    token = request.cookies.get(CANDIDATE_COOKIE)
    if not token:
        raise ApiError("UNAUTHORIZED", MSG_SIGN_IN, 401)
    try:
        claims = decode_token(token)
    except ExpiredSignatureError:
        raise ApiError("SESSION_EXPIRED", "Your session expired. Please sign in again.", 401)
    except Exception:  # noqa: BLE001  (any damaged / foreign token)
        raise ApiError("UNAUTHORIZED", MSG_SIGN_IN, 401)
    sub = str(claims.get("sub", ""))
    if claims.get("kind") != "candidate" or not sub.startswith("candidate:"):
        raise ApiError("UNAUTHORIZED", MSG_SIGN_IN, 401)
    try:
        candidate = _load(int(sub.split(":", 1)[1]))
    except ValueError:
        candidate = None
    if candidate is None or claims.get("cv") != code_version(candidate.access_code):   # removed / new code issued
        raise ApiError("UNAUTHORIZED", MSG_SIGN_IN, 401)
    check_can_continue(candidate, allow_ended=allow_ended)
    g.current_candidate = candidate
    return candidate


def candidate_required(*, allow_ended: bool = False):
    def decorator(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            load_current_candidate(allow_ended=allow_ended)
            return fn(*args, **kwargs)

        return inner

    return decorator
