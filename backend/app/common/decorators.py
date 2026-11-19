"""auth_required(...) - put it under a route to require a logged-in user (optionally with a role)."""
from functools import wraps

from flask import g
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from app.common.errors import ApiError
from app.extensions import db
from app.models.user import User, ROLE_INSTITUTION_ADMIN


def load_current_user() -> User:
    """Reads the login cookie, loads the user from the database and re-checks they may still act.
    Re-checking on every request means suspending an institution cuts off sessions immediately."""
    verify_jwt_in_request()
    identity = str(get_jwt_identity())
    if get_jwt().get("kind") == "candidate" or not identity.isdigit():   # a candidate token is never an admin login
        raise ApiError("UNAUTHORIZED", "Please sign in.", 401)
    user = db.session.get(User, int(identity))
    if user is None or not user.is_active:
        raise ApiError("UNAUTHORIZED", "Please sign in again.", 401)
    if user.role == ROLE_INSTITUTION_ADMIN and (user.institution is None or user.institution.status != "approved"):
        raise ApiError("INSTITUTION_NOT_ACTIVE", "Your institution is not active.", 403)
    if user.role == ROLE_INSTITUTION_ADMIN and user.institution.paid_until is not None:
        from app.common.utils import utcnow
        if user.institution.paid_until <= utcnow():          # Phase 11: subscription ended while signed in
            raise ApiError("INSTITUTION_SUBSCRIPTION_EXPIRED", "Your subscription has ended. Sign in again to renew "
                           "it.", 402)
    g.current_user = user
    return user


def auth_required(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            user = load_current_user()
            if roles and user.role not in roles:
                raise ApiError("FORBIDDEN", "You do not have access to this.", 403)
            return fn(*args, **kwargs)

        return inner

    return decorator
