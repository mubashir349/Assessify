"""candidate_required - put it under a route that only a signed-in candidate may call (Phase 5, used by Phase 6).

The candidate's token travels in its own httpOnly cookie, so it never mixes with the admin login cookie."""
import hashlib
from functools import wraps

from flask import g, request
from flask_jwt_extended import decode_token
from jwt import ExpiredSignatureError

from app.common.errors import ApiError
from app.extensions import db
from app.models.candidate import Candidate

CANDIDATE_COOKIE = "candidate_token"


def code_version(access_code: str) -> str:
    """Short fingerprint of the access code, stored in the token: issuing a new code ends the old sessions."""
    return hashlib.sha256(access_code.encode()).hexdigest()[:12]


def load_current_candidate(*, allow_ended: bool = False) -> Candidate:
    from app.modules.candidate_auth.service import check_can_continue

    token = request.cookies.get(CANDIDATE_COOKIE)
    if not token:
        raise ApiError("UNAUTHORIZED", "Please sign in with your access code.", 401)
    try:
        claims = decode_token(token)
    except ExpiredSignatureError:
        raise ApiError("SESSION_EXPIRED", "Your session expired. Please sign in again.", 401)
    except Exception:  # noqa: BLE001  (any damaged / foreign token)
        raise ApiError("UNAUTHORIZED", "Please sign in with your access code.", 401)
    sub = str(claims.get("sub", ""))
    if claims.get("kind") != "candidate" or not sub.startswith("candidate:"):
        raise ApiError("UNAUTHORIZED", "Please sign in with your access code.", 401)
    try:
        candidate = db.session.get(Candidate, int(sub.split(":", 1)[1]))
    except ValueError:
        candidate = None
    if candidate is None or claims.get("cv") != code_version(candidate.access_code):   # removed / new code issued
        raise ApiError("UNAUTHORIZED", "Please sign in with your access code.", 401)
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
