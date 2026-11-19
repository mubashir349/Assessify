from flask import current_app

from app.common import throttle
from app.common.errors import ApiError
from app.common.validation import EMAIL_RE
from app.models.user import ROLE_INSTITUTION_ADMIN, User

MSG_BAD_LOGIN = "Invalid email or password."
_TRY_LATER = "Too many wrong sign-in attempts. Wait {minutes} minute(s) and try again."

_BLOCKED = {
    "pending": ("INSTITUTION_PENDING", "Your payment is received. Your institution is now awaiting Super Admin approval;"
                " you will get an email when it is approved."),
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
        inst = user.institution
        status = inst.status if inst else "rejected"
        # Phase 11: unpaid registration or expired subscription -> the page goes to the payment step (signed link)
        if status == "awaiting_payment" or (inst is not None and _expired(inst)):
            from app.modules.payments.service import make_token
            expired = status != "awaiting_payment"
            raise ApiError("INSTITUTION_SUBSCRIPTION_EXPIRED" if expired else "INSTITUTION_PAYMENT_REQUIRED",
                           "Your subscription has ended. Renew it to continue." if expired else
                           "Your registration is saved, but the subscription fee is not paid yet. Pay it to send "
                           "your registration for approval.", 402, {"payment_token": make_token(inst)})
        if status in _BLOCKED:
            code, message = _BLOCKED[status]
            if status == "pending" and inst is not None and inst.registration_payment() is None:
                message = "Your institution is still awaiting Super Admin approval."
            raise ApiError(code, message, 403)
    return user


def _expired(inst) -> bool:
    from app.modules.payments.service import is_expired
    return is_expired(inst)
