from flask import current_app

from app.common import throttle
from app.common.errors import ApiError
from app.common.validation import EMAIL_RE
from app.models.user import ROLE_INSTITUTION_ADMIN, User

MSG_BAD_LOGIN = "Invalid email or password."
_TRY_LATER = "Too many wrong sign-in attempts. Wait {minutes} minute(s) and try again."

_BLOCKED = {
    "pending": ("INSTITUTION_PENDING", "Your institution is still awaiting Super Admin approval."),
    "rejected": ("INSTITUTION_REJECTED", "Your institution's registration was not approved. Please contact the platform team."),
    "suspended": ("INSTITUTION_SUSPENDED", "Your institution has been suspended. Please contact the platform team."),
}


def _limits(email: str, remote_addr: str | None) -> list[tuple[str, int]]:
    """Phase 8: wrong passwords per account (guessing one password) and per network address (trying many accounts)."""
    cfg = current_app.config
    return [(f"admin-email:{email}", cfg["ADMIN_LOGIN_MAX_FAILS"]),
            (f"admin-ip:{remote_addr}", cfg["ADMIN_LOGIN_MAX_FAILS_PER_IP"])]


def authenticate(email: str, password: str, remote_addr: str | None = None) -> User:
    email = (email or "").strip().lower()
    if not email or not password or not EMAIL_RE.match(email):
        raise ApiError("INVALID_CREDENTIALS", MSG_BAD_LOGIN, 401)
    keys = _limits(email, remote_addr)
    throttle.check(keys, current_app.config["ADMIN_LOGIN_WINDOW_SECONDS"], _TRY_LATER)

    user = User.query.filter_by(email=email).first()
    if user is None:
        User.burn_password_check(password)
    if user is None or not user.check_password(password):
        throttle.record_failure(keys)
        raise ApiError("INVALID_CREDENTIALS", MSG_BAD_LOGIN, 401)
    throttle.clear(keys[:1])

    # Status messages are only shown AFTER the password is proven right.
    if not user.is_active:
        raise ApiError("ACCOUNT_DISABLED", "This account has been disabled.", 403)
    if user.role == ROLE_INSTITUTION_ADMIN:
        status = user.institution.status if user.institution else "rejected"
        if status in _BLOCKED:
            code, message = _BLOCKED[status]
            raise ApiError(code, message, 403)
    return user
