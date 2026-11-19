"""Phase 11: emails about payment and approval. All of them are sent by Assessify (our mail account), never by the
gateway, so the wording and timing are ours. A failed email is logged and never undoes a payment or a decision."""
import logging

from flask import current_app, has_request_context, request

from app.common.mailer import MailError, send_mail
from app.modules.admit_cards.content import fmt

log = logging.getLogger(__name__)
PLAN_LABEL = {"monthly": "Monthly", "yearly": "Yearly"}


def site_url(path: str) -> str:
    base = current_app.config.get("SITE_URL") or (request.host_url if has_request_context() else "") \
        or current_app.config.get("FRONTEND_URL", "")
    return base.rstrip("/") + "/" + path.lstrip("/")


def _tz() -> str:
    return current_app.config.get("APP_TIMEZONE", "Asia/Karachi")


def _money(amount: float, currency: str = "PKR") -> str:
    return f"{currency} {amount:,.0f}"


def _send(to: str | None, subject: str, body: str) -> bool:
    if not to:
        return False
    try:
        send_mail(to, subject, body)
        return True
    except MailError as exc:
        log.warning("Could not send '%s' to %s: %s", subject, to, exc)
        return False


def _admin(inst):
    a = inst.primary_admin()
    return (a.email, a.full_name) if a else (None, "")


def payment_received(payment) -> bool:
    inst = payment.institution
    to, name = _admin(inst)
    plan = PLAN_LABEL.get(payment.plan, payment.plan)
    lines = [
        f"Dear {name},",
        "",
        f"We have received your payment for {inst.display_name}. Thank you.",
        "",
        f"  Amount: {_money(payment.amount, payment.currency)}",
        f"  Plan: {plan}",
        f"  Receipt number: {payment.receipt_no}",
        f"  Safepay reference: {payment.tracker}",
        *([f"  Paid with: {payment.card_hint}"] if payment.card_hint else []),
        f"  Date: {fmt(payment.paid_at, _tz())}",
        "",
    ]
    if payment.purpose == "registration":
        lines += [
            "Your registration is now waiting for review by the Assessify team. We will email you as soon as it is "
            "approved, and then you can sign in. Your subscription period starts on the day of approval.",
            "",
            "If the registration is not approved, the full amount is refunded automatically to the same card.",
        ]
    else:
        lines += [f"Your subscription has been renewed. It is now valid until {fmt(inst.paid_until, _tz())}."]
    lines += ["", "Keep this email as your receipt.", "", "Assessify"]
    subject = ("Payment received: registration under review" if payment.purpose == "registration"
               else "Payment received: subscription renewed")
    return _send(to, subject, "\n".join(lines))


def payment_not_completed(payment, pay_link: str) -> bool:
    inst = payment.institution
    to, name = _admin(inst)
    reason = payment.failure_reason or "The payment was cancelled or did not go through."
    body = "\n".join([
        f"Dear {name},",
        "",
        f"Your payment of {_money(payment.amount, payment.currency)} for {inst.display_name} was not completed.",
        f"  Reason: {reason}",
        "  No money was taken for this attempt.",
        "",
        "You can try again with this link (it works for "
        f"{current_app.config.get('PAYMENT_LINK_DAYS', 7)} days):",
        f"  {pay_link}",
        "",
        "If the problem continues, try another card or contact your bank.",
        "",
        "Assessify",
    ])
    return _send(to, "Your Assessify payment was not completed", body)


def approved(inst) -> bool:
    to, name = _admin(inst)
    lines = [
        f"Dear {name},",
        "",
        f"Good news: {inst.display_name} has been approved on Assessify. You can now sign in:",
        f"  {site_url('aptitude/institution-login.html')}",
        "",
    ]
    if inst.paid_until:
        lines += [f"Your {PLAN_LABEL.get(inst.plan, inst.plan or '').lower()} subscription is active until "
                  f"{fmt(inst.paid_until, _tz())}.", ""]
    if inst.review_note:
        lines += [f"Note from the Assessify team: {inst.review_note}", ""]
    lines += ["Assessify"]
    return _send(to, "Your institution is approved on Assessify", "\n".join(lines))


def rejected(inst, refund: dict | None) -> bool:
    to, name = _admin(inst)
    lines = [
        f"Dear {name},",
        "",
        f"We are sorry: the registration of {inst.display_name} on Assessify was not approved.",
    ]
    if inst.review_note:
        lines += [f"  Reason: {inst.review_note}"]
    lines.append("")
    if refund and refund.get("status") == "refunded":
        lines += [f"Your payment of {refund['amount']} (receipt {refund['receipt_no']}) has been refunded to the "
                  "card you paid with. Depending on your bank, it can take 5 to 10 working days to appear.", ""]
    elif refund and refund.get("status") == "refund_failed":
        lines += [f"Your payment of {refund['amount']} (receipt {refund['receipt_no']}) will be refunded. The "
                  "automatic refund did not go through, so our team will complete it by hand and email you.", ""]
    lines += ["If you think this was a mistake, reply to the platform team with more details.", "", "Assessify"]
    return _send(to, "Your Assessify registration was not approved", "\n".join(lines))


def refund_completed(payment, by_hand: bool) -> bool:
    inst = payment.institution
    to, name = _admin(inst)
    body = "\n".join([
        f"Dear {name},",
        "",
        f"Your payment of {_money(payment.amount, payment.currency)} (receipt {payment.receipt_no}) for "
        f"{inst.display_name} has been refunded" + (" by our team." if by_hand else "."),
        "Depending on your bank, it can take 5 to 10 working days to appear on your card.",
        "",
        "Assessify",
    ])
    return _send(to, "Your Assessify payment has been refunded", body)
