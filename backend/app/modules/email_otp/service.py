"""Phase 10: email verification codes for institution signup.

send_code(email)            -> emails a 6-digit code (10 min). 60 s between codes, 5 codes per email per hour.
verify_code(email, code)    -> a signed token that says "this email was verified", valid 30 minutes.
check_token(token, email)   -> used by signup; the code row is then marked used so one code makes one account.

Only an HMAC of the code is stored, so the database never holds a working code.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.common import email_rules
from app.common.errors import ApiError
from app.common.mailer import MailError, send_mail
from app.common.utils import utcnow
from app.common.validation import EMAIL_RE
from app.extensions import db
from app.models.directory import EmailOtp
from app.models.user import User

_TOKEN_SALT = "assessify-signup-email"


def _hash(email: str, code: str) -> str:
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{email}|{code}".encode(), hashlib.sha256).hexdigest()


def clean_email(raw) -> str:
    email = raw.strip().lower() if isinstance(raw, str) else ""
    if not email:
        raise ApiError("VALIDATION_ERROR", "Please fix the highlighted fields.", 422, {"admin_email": "Work email is required."})
    if len(email) > 255 or not EMAIL_RE.match(email):
        raise ApiError("VALIDATION_ERROR", "Please fix the highlighted fields.", 422,
                       {"admin_email": "Enter a valid email address."})
    return email


def _check_domain(email: str) -> None:
    """Free providers are allowed here (an institution without official email still verifies its address);
    the signup decides if a free address is acceptable. A made-up domain is refused before any code is sent."""
    domain = email_rules.domain_of(email)
    if email_rules.is_free(domain) or not current_app.config.get("EMAIL_MX_CHECK", True):
        return
    if email_rules.accepts_mail(domain) is False:
        raise ApiError("EMAIL_DOMAIN_INVALID", f"'{domain}' cannot receive email. Check the spelling of your work email.",
                       422, {"admin_email": f"'{domain}' has no mail server. Check the spelling."})


def send_code(raw_email, ip: str | None) -> dict:
    cfg = current_app.config
    email = clean_email(raw_email)
    if User.query.filter_by(email=email).first():
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists. Sign in instead.", 409,
                       {"admin_email": "This email is already registered."})
    _check_domain(email)

    now = utcnow()
    last = EmailOtp.query.filter_by(email=email).order_by(EmailOtp.created_at.desc(), EmailOtp.id.desc()).first()
    if last and (now - last.created_at).total_seconds() < cfg["OTP_RESEND_SECONDS"]:
        wait = int(cfg["OTP_RESEND_SECONDS"] - (now - last.created_at).total_seconds()) + 1
        raise ApiError("OTP_TOO_SOON", f"Please wait {wait} seconds before asking for a new code.", 429, {"retry_after": wait})
    hour_ago = now - timedelta(hours=1)
    if EmailOtp.query.filter(EmailOtp.email == email, EmailOtp.created_at >= hour_ago).count() >= cfg["OTP_MAX_PER_HOUR"]:
        raise ApiError("TOO_MANY_ATTEMPTS", "Too many codes were sent to this email. Try again in an hour.", 429,
                       {"retry_after": 3600})
    _limit_ip(ip)

    code = f"{secrets.randbelow(1_000_000):06d}"
    row = EmailOtp(email=email, code_hash=_hash(email, code), created_at=now,
                   expires_at=now + timedelta(minutes=cfg["OTP_TTL_MINUTES"]))
    db.session.add(row)
    db.session.commit()
    try:
        how = send_mail(email, "Your Assessify verification code",
                        f"Your Assessify verification code is {code}.\n\n"
                        f"It expires in {cfg['OTP_TTL_MINUTES']} minutes. Enter it on the institution signup page.\n"
                        "If you did not ask for this code, you can ignore this email.\n\n— Assessify")
    except MailError as e:
        db.session.delete(row)            # a code that never left must not count against the limits
        db.session.commit()
        raise ApiError("MAIL_FAILED", f"The code could not be emailed: {e}", 502)
    return {"sent_to": email, "expires_in": cfg["OTP_TTL_MINUTES"] * 60, "resend_after": cfg["OTP_RESEND_SECONDS"],
            "delivery": how}       # "logged" = MAIL_BACKEND=console: the code is in the server terminal


def _limit_ip(ip: str | None) -> None:
    from app.common import throttle
    key = [(f"otp-ip:{ip or '-'}", current_app.config["OTP_MAX_PER_IP_HOUR"])]
    throttle.check(key, 3600, "Too many codes were requested from your network. Try again in {minutes} minutes.")
    throttle.record_failure(key)          # every send counts (the throttle module counts events, not only failures)


def verify_code(raw_email, raw_code) -> dict:
    cfg = current_app.config
    email = clean_email(raw_email)
    code = raw_code.strip() if isinstance(raw_code, str) else ""
    if not (len(code) == 6 and code.isdigit()):
        raise ApiError("VALIDATION_ERROR", "Enter the 6-digit code from the email.", 422, {"otp": "Enter the 6-digit code."})

    now = utcnow()
    row = (EmailOtp.query.filter(EmailOtp.email == email, EmailOtp.verified_at.is_(None))
           .order_by(EmailOtp.created_at.desc(), EmailOtp.id.desc()).first())
    if row is None:
        raise ApiError("OTP_NOT_FOUND", "No code was sent to this email. Click Send code first.", 400, {"otp": "Send a code first."})
    if row.expires_at <= now:
        raise ApiError("OTP_EXPIRED", "This code has expired. Click Resend code to get a new one.", 400, {"otp": "Code expired."})
    if row.attempts >= cfg["OTP_MAX_TRIES"]:
        raise ApiError("OTP_LOCKED", "Too many wrong codes. Click Resend code to get a new one.", 429, {"otp": "Too many wrong tries."})
    if not hmac.compare_digest(row.code_hash, _hash(email, code)):
        row.attempts += 1
        db.session.commit()
        left = cfg["OTP_MAX_TRIES"] - row.attempts
        if left <= 0:
            raise ApiError("OTP_LOCKED", "Too many wrong codes. Click Resend code to get a new one.", 429,
                           {"otp": "Too many wrong tries."})
        raise ApiError("OTP_WRONG", f"That code is not right. {left} {'try' if left == 1 else 'tries'} left.", 400,
                       {"otp": f"Wrong code. {left} left."})

    row.verified_at = now
    db.session.commit()
    token = URLSafeTimedSerializer(cfg["SECRET_KEY"], salt=_TOKEN_SALT).dumps({"e": email, "o": row.id})
    return {"email": email, "email_token": token, "valid_minutes": cfg["OTP_VERIFIED_MINUTES"]}


def check_token(token, email: str) -> EmailOtp:
    """Signup: the token must be ours, fresh, for this exact email, and not used by an earlier signup."""
    bad = ApiError("EMAIL_NOT_VERIFIED", "Verify your work email with the code we send you first.", 422,
                   {"admin_email": "Email not verified."})
    if not isinstance(token, str) or not token:
        raise bad
    max_age = current_app.config["OTP_VERIFIED_MINUTES"] * 60
    try:
        data = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_TOKEN_SALT).loads(token, max_age=max_age)
    except SignatureExpired:
        raise ApiError("EMAIL_NOT_VERIFIED", "Your email verification expired. Send a new code and verify again.", 422,
                       {"admin_email": "Verification expired."})
    except BadSignature:
        raise bad
    if not isinstance(data, dict) or data.get("e") != email:
        raise bad
    row = db.session.get(EmailOtp, data.get("o"))
    if row is None or row.email != email or row.verified_at is None or row.used_at is not None:
        raise bad
    return row
