from app.common.errors import ApiError
from app.common.validation import EMAIL_RE
from app.models.user import ROLE_INSTITUTION_ADMIN, User

MSG_BAD_LOGIN = "Invalid email or password."

_BLOCKED = {
    "pending": ("INSTITUTION_PENDING", "Your institution is still awaiting Super Admin approval."),
    "rejected": ("INSTITUTION_REJECTED", "Your institution's registration was not approved. Please contact the platform team."),
    "suspended": ("INSTITUTION_SUSPENDED", "Your institution has been suspended. Please contact the platform team."),
}


def authenticate(email: str, password: str) -> User:
    email = (email or "").strip().lower()
    if not email or not password or not EMAIL_RE.match(email):
        raise ApiError("INVALID_CREDENTIALS", MSG_BAD_LOGIN, 401)

    user = User.query.filter_by(email=email).first()
    if user is None:
        User.burn_password_check(password)
        raise ApiError("INVALID_CREDENTIALS", MSG_BAD_LOGIN, 401)
    if not user.check_password(password):
        raise ApiError("INVALID_CREDENTIALS", MSG_BAD_LOGIN, 401)

    # Status messages are only shown AFTER the password is proven right.
    if not user.is_active:
        raise ApiError("ACCOUNT_DISABLED", "This account has been disabled.", 403)
    if user.role == ROLE_INSTITUTION_ADMIN:
        status = user.institution.status if user.institution else "rejected"
        if status in _BLOCKED:
            code, message = _BLOCKED[status]
            raise ApiError(code, message, 403)
    return user
