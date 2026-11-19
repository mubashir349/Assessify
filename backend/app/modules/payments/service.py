"""Phase 11 - payments: registration fee and renewals through Safepay.

Signup -> institution is `awaiting_payment` -> payment page (opened with a signed "pay now" link, because the
institution cannot sign in yet) -> Safepay hosted checkout -> back to our page -> the backend asks Safepay itself
whether the payment is done (never trusts the browser) -> paid: institution becomes `pending` and gets the receipt
email -> Super Admin approves (subscription starts that day, approval email) or rejects (automatic refund, email).

A monthly / yearly plan runs out on `paid_until`. An expired institution signs in to a "renew" step (same page);
a paid renewal extends the plan at once, without another approval.
"""
import logging
import re
from datetime import datetime

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.common.errors import ApiError
from app.common.utils import iso, utcnow
from app.extensions import db
from app.models.institution import Institution
from app.models.payment import Payment
from app.modules.payments import emails
from app.payments import GatewayError, gateway_status, get_gateway
from app.payments.safepay import DEAD_STATES, PAID_STATES, REFUNDED_STATES

log = logging.getLogger(__name__)
PLAN_MONTHS = {"monthly": 1, "yearly": 12}
TOKEN_SALT = "assessify-payment-link"


# ---------------------------------------------------------------- plans + subscription dates
def plans() -> list[dict]:
    cfg = current_app.config
    monthly, yearly = cfg["PLAN_MONTHLY_PKR"], cfg["PLAN_YEARLY_PKR"]
    return [
        {"id": "monthly", "label": "Monthly", "amount": monthly, "currency": "PKR", "months": 1,
         "note": "Billed every month"},
        {"id": "yearly", "label": "Yearly", "amount": yearly, "currency": "PKR", "months": 12,
         "saving": max(0, monthly * 12 - yearly),
         "note": f"Save PKR {max(0, monthly * 12 - yearly):,} compared with 12 monthly payments"},
    ]


def _plan(plan_id) -> dict:
    found = next((p for p in plans() if p["id"] == plan_id), None)
    if found is None:
        raise ApiError("VALIDATION_ERROR", "Choose a plan.", 422, {"plan": "Choose monthly or yearly."})
    return found


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar months; 31 Jan + 1 month = 28/29 Feb (the day is clamped to the month's length)."""
    y, m = divmod(dt.month - 1 + months, 12)
    year, month = dt.year + y, m + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.replace(year=year, month=month, day=min(dt.day, days))


def is_expired(inst: Institution, now: datetime | None = None) -> bool:
    return bool(inst.status == "approved" and inst.paid_until and inst.paid_until <= (now or utcnow()))


def start_subscription(inst: Institution) -> None:
    """Called when the Super Admin approves: the paid period starts on the day of approval."""
    if not current_app.config.get("PAYMENTS_ENABLED", True) or inst.paid_until:
        return
    pay = inst.registration_payment()
    if pay is not None and pay.status == "paid":
        inst.plan = pay.plan
        inst.paid_until = add_months(utcnow(), PLAN_MONTHS[pay.plan])


# ---------------------------------------------------------------- "pay now" links (the institution can't sign in yet)
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)


def make_token(inst: Institution) -> str:
    return _serializer().dumps({"i": inst.id})


def pay_link(inst: Institution) -> str:
    return emails.site_url(f"aptitude/institution-payment.html?token={make_token(inst)}")


def institution_from_token(token) -> Institution:
    max_age = int(current_app.config.get("PAYMENT_LINK_DAYS", 7)) * 86400
    try:
        data = _serializer().loads(str(token or ""), max_age=max_age)
    except SignatureExpired:
        raise ApiError("PAYMENT_LINK_EXPIRED", "This payment link has expired. Sign in with your email and password "
                       "to get a new one.", 410)
    except BadSignature:
        raise ApiError("PAYMENT_LINK_INVALID", "This payment link is not valid. Sign in with your email and password "
                       "to open the payment page.", 400)
    inst = db.session.get(Institution, data.get("i")) if isinstance(data, dict) else None
    if inst is None:
        raise ApiError("PAYMENT_LINK_INVALID", "This payment link is not valid.", 400)
    return inst


def purpose_of(inst: Institution) -> str | None:
    """What this institution can pay for right now: registration, renewal, or nothing."""
    if inst.status == "awaiting_payment":
        return "registration"
    if inst.status == "approved" and inst.paid_until:
        return "renewal"
    return None


# ---------------------------------------------------------------- payment page
def session_info(token) -> dict:
    """GET /payments/session?token= - what the payment page shows."""
    inst = institution_from_token(token)
    admin = inst.primary_admin()
    purpose = purpose_of(inst)
    reg, latest = inst.registration_payment(), inst.latest_payment()
    return {
        "institution": {"name": inst.display_name, "status": inst.status, "plan": inst.plan,
                        "paid_until": iso(inst.paid_until), "expired": is_expired(inst),
                        "admin_email": admin.email if admin else None},
        "purpose": purpose,
        "plans": plans(),
        "gateway": gateway_status(current_app.config),
        "latest": latest.to_dict() if latest else None,
        "registration": reg.to_dict() if reg else None,
    }


_RETURN_URL = re.compile(r"^https?://[^\s<>\"']{3,400}$")


def start_checkout(data: dict) -> dict:
    """POST /payments/checkout {token, plan, return_url} -> {checkout_url, payment}"""
    inst = institution_from_token(data.get("token"))
    purpose = purpose_of(inst)
    if purpose is None:
        msg = {"pending": "Your payment is already received. The registration is waiting for approval.",
               "rejected": "This registration was not approved, so it cannot be paid for.",
               "suspended": "This institution is suspended. Please contact the platform team."}
        raise ApiError("PAYMENT_NOT_NEEDED", msg.get(inst.status, "No payment is due for this institution."), 409)
    plan = _plan(data.get("plan"))
    return_url = str(data.get("return_url") or "")
    if not _RETURN_URL.match(return_url):
        raise ApiError("VALIDATION_ERROR", "The page address is not valid.", 422, {"return_url": "Invalid address."})
    try:
        gateway = get_gateway(current_app.config)
    except GatewayError as exc:
        raise ApiError(exc.code, exc.message, exc.status)

    pay = Payment(institution_id=inst.id, purpose=purpose, plan=plan["id"], amount_minor=plan["amount"] * 100,
                  currency="PKR", provider="safepay", environment=gateway.environment, status="created")
    db.session.add(pay)
    db.session.flush()
    token = data.get("token")
    base = return_url.split("?")[0].split("#")[0]
    redirect_url = f"{base}?token={token}&result=return&payment={pay.id}"
    cancel_url = f"{base}?token={token}&result=cancel&payment={pay.id}"
    try:
        checkout = gateway.create_checkout(pay.amount_minor, pay.currency, redirect_url, cancel_url,
                                           order_id=f"ASY-{pay.id}")
    except GatewayError as exc:
        db.session.rollback()
        raise ApiError(exc.code, exc.message, exc.status)
    pay.tracker = checkout.tracker
    db.session.commit()
    return {"checkout_url": checkout.url, "payment": pay.to_dict()}


def _payment_for(inst: Institution, data: dict) -> Payment:
    """Find the payment the browser came back for. Safepay sometimes adds its own '?tracker=...' to the end of
    our return address, which turns 'payment=12' into 'payment=12?tracker=...'; so read only the leading digits,
    then try the tracker, then the institution's newest unfinished payment. Which one is picked never decides
    'paid' - reconcile() always asks Safepay about that payment's own tracker."""
    pay = None
    m = re.match(r"\s*(\d+)", str(data.get("payment") or ""))
    if m:
        pay = Payment.query.filter_by(id=int(m.group(1)), institution_id=inst.id).first()
    if pay is None and data.get("tracker"):
        pay = Payment.query.filter_by(tracker=str(data["tracker"])[:100], institution_id=inst.id).first()
    if pay is None:
        pay = (Payment.query.filter(Payment.institution_id == inst.id, Payment.status == "created",
                                    Payment.tracker.isnot(None))
               .order_by(Payment.id.desc()).first())
    if pay is None:
        raise ApiError("NOT_FOUND", "Payment not found.", 404)
    return pay


def confirm(data: dict) -> dict:
    """POST /payments/confirm {token, payment?, tracker?} - the page calls this after Safepay sends the browser back
    (and again a few times while Safepay is still finishing). The answer comes from Safepay, not from the browser."""
    inst = institution_from_token(data.get("token"))
    pay = _payment_for(inst, data)
    reconcile(pay)
    return {"payment": pay.to_dict(), "institution_status": inst.status, "paid_until": iso(inst.paid_until)}


def cancel(data: dict) -> dict:
    """POST /payments/cancel {token, payment} - Safepay sent the browser to cancel_url."""
    inst = institution_from_token(data.get("token"))
    pay = _payment_for(inst, data)
    reconcile(pay, cancelled_by_user=True)
    return {"payment": pay.to_dict(), "institution_status": inst.status}


# ---------------------------------------------------------------- the one place that changes a payment's status
def reconcile(pay: Payment, cancelled_by_user: bool = False) -> Payment:
    if pay.status in ("paid", "refunded", "refund_failed") or not pay.tracker:
        return pay
    try:
        info = get_gateway(current_app.config).fetch(pay.tracker)
    except GatewayError as exc:
        raise ApiError(exc.code, exc.message, exc.status)
    pay.gateway_state = info.state[:40]

    if info.state in PAID_STATES:
        problem = None
        if info.amount_minor is not None and info.amount_minor != pay.amount_minor:
            problem = f"Safepay reports a different amount ({info.amount_minor / 100:,.0f}) than expected."
        elif info.currency and str(info.currency).upper() != pay.currency:
            problem = "Safepay reports a different currency than expected."
        elif info.api_key and current_app.config.get("SAFEPAY_API_KEY") and \
                info.api_key != current_app.config["SAFEPAY_API_KEY"]:
            problem = "This payment belongs to a different Safepay account."
        if problem:
            log.error("Payment %s NOT accepted: %s", pay.id, problem)
            pay.status, pay.failure_reason = "failed", problem
            db.session.commit()
            return pay
        _mark_paid(pay, info.card_hint)
        return pay

    if info.state in REFUNDED_STATES:
        pay.status, pay.refunded_at = "refunded", pay.refunded_at or utcnow()
        db.session.commit()
        return pay

    if info.state in DEAD_STATES or cancelled_by_user:
        pay.status = "cancelled"
        pay.failure_reason = ("You cancelled the payment on the Safepay page." if cancelled_by_user and
                              info.state not in DEAD_STATES else
                              "The payment session expired before it was completed.")
        send_mail = not pay.failure_email_sent
        pay.failure_email_sent = True
        db.session.commit()
        if send_mail:
            emails.payment_not_completed(pay, pay_link(pay.institution))
        return pay

    db.session.commit()     # still in progress (e.g. 3-D Secure step) - the page asks again shortly
    return pay


def _mark_paid(pay: Payment, card_hint: str | None) -> None:
    inst = pay.institution
    now = utcnow()
    pay.status, pay.paid_at, pay.card_hint = "paid", now, (card_hint or None) and card_hint[:60]
    pay.failure_reason = None
    pay.receipt_no = f"ASY-{now.year}-{pay.id:06d}"
    if pay.purpose == "registration":
        if inst.status == "awaiting_payment":
            inst.status = "pending"
        inst.plan = pay.plan
    else:
        start = inst.paid_until if inst.paid_until and inst.paid_until > now else now
        inst.paid_until = add_months(start, PLAN_MONTHS[pay.plan])
        inst.plan = pay.plan
    db.session.commit()
    emails.payment_received(pay)


# ---------------------------------------------------------------- webhooks (optional; only a hint to re-check)
def _tracker_in(body) -> str | None:
    if not isinstance(body, dict):
        return None
    for path in (("data", "tracker"), ("data", "tracker", "token"), ("tracker",), ("notification", "tracker"),
                 ("data", "notification", "tracker")):
        cur = body
        for part in path:
            cur = cur.get(part) if isinstance(cur, dict) else None
        if isinstance(cur, str) and cur.startswith("track_"):
            return cur
    return None


def webhook(raw_body: bytes, signature: str | None, body) -> dict:
    """POST /payments/webhook - Safepay calls this (needs a public https address, so not on localhost). A webhook
    with a wrong signature is refused. A good one only makes us ask Safepay again; it never marks a payment by itself."""
    try:
        gateway = get_gateway(current_app.config)
    except GatewayError:
        raise ApiError("PAYMENTS_NOT_CONFIGURED", "Payments are not set up.", 503)
    if current_app.config.get("SAFEPAY_WEBHOOK_SECRET") and not gateway.verify_webhook(raw_body, signature):
        raise ApiError("BAD_SIGNATURE", "Webhook signature does not match.", 400)
    tracker = _tracker_in(body)
    pay = Payment.query.filter_by(tracker=tracker).first() if tracker else None
    if pay is not None:
        try:
            reconcile(pay)
        except ApiError as exc:
            log.warning("Webhook re-check for payment %s failed: %s", pay.id, exc.message)
    return {"received": True}


# ---------------------------------------------------------------- refunds (Super Admin rejects a paid registration)
def _refund_dict(pay: Payment) -> dict:
    return {"status": pay.status, "amount": f"{pay.currency} {pay.amount:,.0f}", "receipt_no": pay.receipt_no,
            "error": pay.refund_error}


def refund_registration(inst: Institution) -> dict | None:
    """Automatic refund when a paid registration is rejected. Returns what happened (for the email and the page)."""
    pay = inst.registration_payment()
    if pay is None or pay.status not in ("paid", "refund_failed"):
        return None
    try:
        state = get_gateway(current_app.config).refund(pay.tracker, pay.amount_minor, pay.currency)
        pay.status, pay.refunded_at, pay.gateway_state, pay.refund_error = "refunded", utcnow(), state[:40], None
    except GatewayError as exc:
        log.error("Automatic refund of payment %s failed: %s", pay.id, exc.message)
        pay.status, pay.refund_error = "refund_failed", exc.message[:300]
    db.session.commit()
    return _refund_dict(pay)


def retry_refund(institution_id: int) -> dict:
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found.", 404)
    pay = inst.registration_payment()
    if pay is None or pay.status != "refund_failed":
        raise ApiError("NOTHING_TO_REFUND", "There is no failed refund to retry for this institution.", 409)
    result = refund_registration(inst)
    if result and result["status"] == "refunded":
        emails.refund_completed(pay, by_hand=False)
    return {"payment": pay.to_dict(), "institution": inst.to_dict()}


def mark_refunded_by_hand(institution_id: int, note: str | None, reviewer_email: str) -> dict:
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found.", 404)
    pay = inst.registration_payment()
    if pay is None or pay.status != "refund_failed":
        raise ApiError("NOTHING_TO_REFUND", "There is no failed refund for this institution.", 409)
    pay.status, pay.refunded_at = "refunded", utcnow()
    pay.refund_note = (f"Refunded by hand by {reviewer_email}" + (f": {note.strip()}" if note and note.strip() else ""))[:300]
    db.session.commit()
    emails.refund_completed(pay, by_hand=True)
    return {"payment": pay.to_dict(), "institution": inst.to_dict()}


def payments_of(institution_id: int) -> list[dict]:
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found.", 404)
    return [p.to_dict() for p in inst.payments]

