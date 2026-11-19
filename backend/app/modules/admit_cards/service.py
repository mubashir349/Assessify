"""Phase 11 - admit cards by email (Institution Admin, one published test at a time).

The admin presses "Send admit cards" on the Roster page. Every candidate WITH an email gets one email: the test
schedule and the reason for the email in the text, and the admit card as a PDF attachment. Each try is written to
admit_card_emails, so the page can say, by name, who got it, who has no email, and why a card was not delivered.

Sending is allowed until the test ends. It is blocked (with the reason) when the test has ended, the roster is
empty, nobody on the roster has an email, or email is not set up on the server.

Before an address is tried, it is checked: a malformed address or a domain with no mail server is reported straight
away without sending. "Address not found" for a real domain (e.g. a typo before @gmail.com) is only known when the
receiving server sends a bounce back to our mailbox a minute later; check_bounces() reads those over IMAP.
"""
import email
import imaplib
import logging
import re
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime

from flask import current_app

from app.common import email_rules
from app.common.errors import ApiError
from app.common.mailer import MailError, mail_batch, mail_ready
from app.common.utils import iso, utcnow
from app.common.validation import EMAIL_RE
from app.extensions import db
from app.models.admit_card import AdmitCardEmail
from app.models.candidate import Candidate
from app.modules.admit_cards import content, pdf
from app.modules.roster.service import _ordered, _term, published_test

log = logging.getLogger(__name__)
MAX_PER_REQUEST = 500
DELIVERED = ("sent", "logged")


# ---------------------------------------------------------------- small helpers
def _cfg(key, default=None):
    return current_app.config.get(key, default)


def login_url(raw: str | None) -> str:
    """CANDIDATE_LOGIN_URL from .env wins; otherwise the address the admin's own page computed (validated)."""
    configured = _cfg("CANDIDATE_LOGIN_URL")
    if configured:
        return configured
    url = (raw or "").strip()
    if re.match(r"^https?://[^\s<>\"']{3,300}$", url):
        return url
    base = (_cfg("FRONTEND_URL") or "").rstrip("/")
    return f"{base}/aptitude/candidate-login.html" if base else "the candidate sign-in page"


def _card(c: Candidate, url: str) -> content.Card:
    return content.build(c, url, _cfg("APP_TIMEZONE", "Asia/Karachi"), _term(c.test))


def _delivered(c: Candidate) -> bool:
    row = c.admit_card
    return bool(row and row.status in DELIVERED and c.email and row.to_email.lower() == c.email.lower())


def _state(c: Candidate) -> str:
    """no_email | not_sent | sent | failed | bounced | changed (email corrected after sending)."""
    if not c.email:
        return "no_email"
    row = c.admit_card
    if row is None:
        return "not_sent"
    if row.to_email.lower() != c.email.lower():
        return "changed"
    return "sent" if row.status in DELIVERED else row.status


def _test_ended(test) -> bool:
    s = test.schedule
    return bool(s and utcnow() >= s.ends_at)


def imap_server() -> str:
    configured = _cfg("MAIL_IMAP_SERVER")
    if configured:
        return configured
    if _cfg("MAIL_BACKEND") == "smtp" and (_cfg("MAIL_SERVER") or "").lower() == "smtp.gmail.com":
        return "imap.gmail.com"
    return ""


# ---------------------------------------------------------------- status (what the Roster page shows)
def blocked_reason(test, candidates: list[Candidate]) -> str | None:
    """Why the Send button is disabled (shown when the mouse is over it). None = it can be pressed."""
    if _test_ended(test):
        return "This test has ended. Admit cards can only be sent before the test ends."
    if not candidates:
        return "The roster is empty. Add candidates first."
    if not any(c.email for c in candidates):
        return ("No candidate on this roster has an email address, so admit cards cannot be emailed. Add email "
                "addresses (use “Correct” on a candidate, or re-import the list with an email column).")
    ready, why = mail_ready(current_app.config)
    if not ready:
        return why
    if not any(_state(c) in ("not_sent", "failed", "bounced", "changed") for c in candidates if c.email):
        return "Every candidate with an email already has their admit card. Use “Send again” to resend."
    return None


def _person(c: Candidate) -> dict:
    row = c.admit_card
    return {"id": c.id, "full_name": c.full_name, "roll_number": c.roll_number, "email": c.email,
            "department": c.department.name, "state": _state(c),
            "error": row.error if row and row.status in ("failed", "bounced") else None,
            "sent_to": row.to_email if row else None, "sent_at": iso(row.sent_at) if row else None,
            "candidate": c.to_dict()}


def status(institution_id: int, test_id) -> dict:
    """GET /admit-cards?test_id="""
    test = published_test(institution_id, test_id)
    cands = _ordered(test)
    people = [_person(c) for c in cands]
    counts = {k: 0 for k in ("no_email", "not_sent", "sent", "failed", "bounced", "changed")}
    for p in people:
        counts[p["state"]] += 1
    reason = blocked_reason(test, cands)
    ready, mail_note = mail_ready(current_app.config)
    can_resend = (not _test_ended(test)) and ready and counts["sent"] > 0
    return {
        "test": {"id": test.id, "name": test.name, "ended": _test_ended(test),
                 "ends_at": iso(test.schedule.ends_at) if test.schedule else None},
        "total": len(cands), "with_email": len(cands) - counts["no_email"], "counts": counts,
        "can_send": reason is None, "blocked_reason": reason, "can_resend": can_resend,
        "mail_note": mail_note, "bounce_check": bool(imap_server()),
        "no_email": [p for p in people if p["state"] == "no_email"],
        "problems": [p for p in people if p["state"] in ("failed", "bounced")],
        "changed": [p for p in people if p["state"] == "changed"],
        "sent": [{k: p[k] for k in ("id", "full_name", "roll_number", "email", "sent_at")}
                 for p in people if p["state"] == "sent"],
    }


# ---------------------------------------------------------------- sending
def _precheck(address: str) -> str | None:
    """A reason when the address surely cannot receive mail, checked before sending (no email is wasted)."""
    if not EMAIL_RE.match(address or ""):
        return "The email address is not valid (check for typos or spaces)."
    domain = email_rules.domain_of(address)
    if _cfg("EMAIL_MX_CHECK", True) and email_rules.accepts_mail(domain) is False:
        return f"The email domain “{domain}” does not exist or cannot receive email."
    return None


def _record(c: Candidate, status_: str, error: str | None, user) -> None:
    row = c.admit_card
    if row is None:
        row = AdmitCardEmail(candidate_id=c.id, test_id=c.test_id, attempts=0)
        db.session.add(row)
        c.admit_card = row
    row.to_email, row.status, row.error = c.email, status_, (error or None) and error[:300]
    row.attempts = (row.attempts or 0) + 1
    row.sent_by_id, row.sent_at, row.bounced_at = user.id, utcnow(), None


def _targets(cands, ids: set[int] | None, resend: bool) -> list[Candidate]:
    out = []
    for c in cands:
        if not c.email or (ids is not None and c.id not in ids):
            continue
        if resend or not _delivered(c):
            out.append(c)
    return out


def send(user, data: dict) -> dict:
    """POST /admit-cards/send {test_id, candidate_ids?, resend?, login_url?}"""
    test = published_test(user.institution_id, data.get("test_id"))
    cands = _ordered(test)
    raw_ids = data.get("candidate_ids")
    if raw_ids is not None and (not isinstance(raw_ids, list)
                                or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw_ids)):
        raise ApiError("VALIDATION_ERROR", "candidate_ids must be a list of numbers.", 422,
                       {"candidate_ids": "Send a list of candidate ids, or leave it out to send to everyone."})
    ids = set(raw_ids) if raw_ids is not None else None
    resend = data.get("resend") is True

    reason = blocked_reason(test, cands)
    if reason and not (resend and "already has their admit card" in reason):
        raise ApiError("ADMIT_CARDS_BLOCKED", reason, 409)

    url = login_url(data.get("login_url"))
    targets = _targets(cands, ids, resend)[:MAX_PER_REQUEST]
    results = {"sent": [], "failed": [], "stopped": None}
    font = _cfg("ADMIT_CARD_FONT", "")
    try:
        with mail_batch() as deliver:
            for c in targets:
                problem = _precheck(c.email)
                if problem:
                    _record(c, "failed", problem, user)
                    results["failed"].append({"id": c.id, "full_name": c.full_name, "email": c.email,
                                              "reason": problem})
                    db.session.commit()
                    continue
                card = _card(c, url)
                subject, body = content.email_text(card)
                attachment = (f"Admit card - {c.full_name}.pdf".replace("/", "-"), pdf.render(card, font),
                              "application/pdf")
                try:
                    outcome = deliver(c.email, subject, body, [attachment])
                except MailError as exc:
                    _record(c, "failed", str(exc), user)
                    results["failed"].append({"id": c.id, "full_name": c.full_name, "email": c.email,
                                              "reason": str(exc)})
                    db.session.commit()
                    if exc.kind != "recipient":
                        # the mail setup itself is the problem: every other student would fail the same way
                        results["stopped"] = str(exc)
                        break
                    continue
                _record(c, outcome, None, user)
                results["sent"].append({"id": c.id, "full_name": c.full_name, "email": c.email,
                                        "status": outcome})
                db.session.commit()
    except MailError as exc:           # could not even start (e.g. mail not configured)
        raise ApiError("MAIL_NOT_CONFIGURED", str(exc), 503)

    after = status(user.institution_id, test.id)
    return {"tried": len(results["sent"]) + len(results["failed"]), "sent": results["sent"],
            "failed": results["failed"], "stopped": results["stopped"],
            "no_email": after["no_email"], "status": after}


def card_pdf(institution_id: int, candidate_id: int, raw_login_url: str | None) -> tuple[str, bytes]:
    """GET /admit-cards/<candidate_id>.pdf - the same PDF the email carries (preview / print)."""
    c = Candidate.query.filter_by(id=candidate_id, institution_id=institution_id).first()
    if c is None:
        raise ApiError("NOT_FOUND", "Candidate not found.", 404)
    card = _card(c, login_url(raw_login_url))
    return f"Admit card - {c.full_name}.pdf".replace("/", "-"), pdf.render(card, _cfg("ADMIT_CARD_FONT", ""))


# ---------------------------------------------------------------- bounces ("address not found" comes back later)
_STATUS_TEXT = [
    (re.compile(r"\b5\.1\.[0-3]\b"), "Address not found: this mailbox does not exist."),
    (re.compile(r"\b5\.2\.2\b"), "The mailbox is full."),
    (re.compile(r"\b5\.2\.1\b"), "The mailbox is disabled or not accepting email."),
    (re.compile(r"\b5\.7\.\d\b"), "The receiving server rejected the email (blocked or treated as spam)."),
    (re.compile(r"\b4\.\d\.\d\b"), "Delivery is delayed; the receiving server will keep trying."),
]


def _bounce_reason(text: str) -> str:
    for pattern, reason in _STATUS_TEXT:
        if pattern.search(text):
            return reason
    if re.search(r"(?i)does not exist|no such user|user unknown|address not found|couldn't be found|unknown user",
                 text):
        return "Address not found: this mailbox does not exist."
    return "The email bounced back (it could not be delivered)."


def parse_bounce(raw: bytes) -> list[tuple[str, str]]:
    """[(failed address, reason)] from one 'Delivery Status Notification' email (empty if it is not a bounce)."""
    msg = email.message_from_bytes(raw)
    found: dict[str, str] = {}
    text_parts = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            payload = part.get_payload()
            blocks = payload if isinstance(payload, list) else [payload]
            for block in blocks:
                block_text = block.as_string() if hasattr(block, "as_string") else str(block)
                for m in re.finditer(r"(?im)^Final-Recipient:\s*rfc822;\s*<?([^>\s]+)>?", block_text):
                    found[m.group(1).lower()] = _bounce_reason(block_text)
        elif ctype == "text/plain":
            try:
                text_parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8",
                                                                       "replace"))
            except Exception:  # noqa: BLE001
                pass
    for addr in (msg.get("X-Failed-Recipients") or "").split(","):
        addr = addr.strip().lower()
        if addr and addr not in found:
            found[addr] = _bounce_reason("\n".join(text_parts))
    return list(found.items())


def check_bounces(user, data: dict) -> dict:
    """POST /admit-cards/check-bounces {test_id} - reads 'delivery failed' replies from the sending mailbox (read-only,
    nothing is deleted or marked as read) and marks those admit cards as bounced, with the reason."""
    test = published_test(user.institution_id, data.get("test_id"))
    server = imap_server()
    if not server:
        raise ApiError("BOUNCE_CHECK_UNAVAILABLE", "Bounce checking needs MAIL_IMAP_SERVER (or Gmail) in backend/.env.",
                       409)
    rows = AdmitCardEmail.query.filter(AdmitCardEmail.test_id == test.id,
                                       AdmitCardEmail.status.in_(("sent", "bounced"))).all()
    if not rows:
        return {"checked": 0, "bounced": [], "status": status(user.institution_id, test.id)}
    since = min(r.sent_at for r in rows) - timedelta(days=1)
    by_address: dict[str, list[AdmitCardEmail]] = {}
    for r in rows:
        by_address.setdefault(r.to_email.lower(), []).append(r)

    newly = []
    try:
        box = imaplib.IMAP4_SSL(server, 993, timeout=_cfg("MAIL_TIMEOUT_SECONDS", 20))
    except TypeError:            # Python < 3.9 has no timeout argument
        box = imaplib.IMAP4_SSL(server, 993)
    except OSError:
        raise ApiError("BOUNCE_CHECK_FAILED", f"Could not reach the mailbox server {server}.", 503)
    try:
        try:
            box.login(_cfg("MAIL_USERNAME") or "", _cfg("MAIL_PASSWORD") or "")
        except imaplib.IMAP4.error:
            raise ApiError("BOUNCE_CHECK_FAILED", "The mailbox refused the username / password. For Gmail, IMAP must "
                           "be allowed and MAIL_PASSWORD must be an App Password.", 503)
        box.select("INBOX", readonly=True)
        criteria = f'(SINCE {since.strftime("%d-%b-%Y")} OR FROM "mailer-daemon" FROM "postmaster")'
        typ, data_ = box.search(None, criteria)
        ids = (data_[0] or b"").split() if typ == "OK" else []
        checked = 0
        for num in ids[-300:]:
            typ, msg_data = box.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            checked += 1
            msg_date = None
            try:
                msg_date = parsedate_to_datetime(email.message_from_bytes(raw).get("Date")).astimezone(None)
            except Exception:  # noqa: BLE001
                pass
            for address, reason in parse_bounce(raw):
                for row in by_address.get(address, []):
                    if msg_date is not None:
                        sent = row.sent_at.replace(tzinfo=timezone.utc)
                        if msg_date < sent - timedelta(minutes=5):
                            continue        # an old bounce from before this card was (re)sent
                    if row.status != "bounced":
                        row.status, row.error, row.bounced_at = "bounced", reason, utcnow()
                        newly.append(row)
        db.session.commit()
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    named = []
    for row in newly:
        c = db.session.get(Candidate, row.candidate_id)
        named.append({"id": row.candidate_id, "full_name": c.full_name if c else "", "email": row.to_email,
                      "reason": row.error})
    return {"checked": checked, "bounced": named, "status": status(user.institution_id, test.id)}
