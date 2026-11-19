"""Phase 7: sends plain-text email. MAIL_BACKEND=console (default) only writes it to the server log.

send_mail(...) returns "sent" or "logged", and raises MailError with a short, safe reason when sending fails.

Phase 11: attachments (admit card PDFs) and mail_batch(), which keeps ONE connection to the mail server open for a
whole list of emails (a roster of 300 students would otherwise log in to Gmail 300 times). MailError.kind tells
whether the problem is this one address ("recipient") or the mail setup itself ("setup" / "server"), so a batch
can stop at once when the password is wrong instead of failing every student the same way.
"""
import logging
import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


class MailError(Exception):
    def __init__(self, message: str, kind: str = "server"):
        super().__init__(message)
        self.kind = kind          # "recipient" = only this address · "setup" = mail settings · "server" = connection


def mail_ready(config) -> tuple[bool, str]:
    """(ready, explanation) - shown on the Reports / Roster page before sending."""
    backend = config.get("MAIL_BACKEND", "console")
    if backend == "console":
        return True, "MAIL_BACKEND=console: emails are written to the server terminal, not really sent."
    if backend != "smtp":
        return False, f"Unknown MAIL_BACKEND '{backend}'. Use console or smtp in backend/.env."
    if not config.get("MAIL_SERVER") or not (config.get("MAIL_FROM") or config.get("MAIL_USERNAME")):
        return False, "Set MAIL_SERVER and MAIL_USERNAME (or MAIL_FROM) in backend/.env to send emails."
    return True, f"Emails are sent through {config['MAIL_SERVER']}."


def _connect(cfg) -> smtplib.SMTP:
    """Always encrypted, with the server certificate checked: port 465 = SSL from the start, any other port =
    STARTTLS. The password never travels in clear text."""
    context = ssl.create_default_context()
    host, port, timeout = cfg["MAIL_SERVER"], int(cfg["MAIL_PORT"]), cfg["MAIL_TIMEOUT_SECONDS"]
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    smtp = smtplib.SMTP(host, port, timeout=timeout)
    smtp.starttls(context=context)
    return smtp


def _message(cfg, to: str, subject: str, body: str, attachments) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.get("MAIL_FROM") or cfg["MAIL_USERNAME"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for filename, data, mimetype in attachments or ():
        main, _, sub = (mimetype or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=filename)
    return msg


def _open(cfg) -> smtplib.SMTP:
    try:
        smtp = _connect(cfg)
        username, password = cfg.get("MAIL_USERNAME"), cfg.get("MAIL_PASSWORD")
        if username and password:
            smtp.login(username, password)
        return smtp
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server refused the username / password (for Gmail: use an App Password).", "setup")
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Could not connect to the mail server: %s", type(exc).__name__)
        raise MailError("The mail server could not be reached. Check MAIL_SERVER / MAIL_PORT and the internet "
                        "connection.", "server")


def _deliver(smtp: smtplib.SMTP, msg: EmailMessage) -> None:
    try:
        smtp.send_message(msg)
    except smtplib.SMTPRecipientsRefused as exc:
        code, text = next(iter(exc.recipients.values()), (0, b""))
        detail = text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text)
        log.info("Recipient refused (%s): %s", code, detail[:200])
        raise MailError("The mail server refused this address (it may not exist).", "recipient")
    except smtplib.SMTPSenderRefused:
        raise MailError("The mail server refused the sender address (check MAIL_FROM).", "setup")
    except smtplib.SMTPDataError as exc:
        if 500 <= exc.smtp_code < 600 and exc.smtp_code in (550, 551, 553):
            raise MailError("The mail server rejected this email for this address.", "recipient")
        raise MailError("The mail server refused the email (possibly the daily sending limit).", "server")
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError) as exc:
        log.warning("Sending an email failed: %s", type(exc).__name__)
        raise MailError("The mail server could not be reached or refused the email.", "server")


def send_mail(to: str, subject: str, body: str, attachments=None) -> str:
    """One email. attachments = [(filename, bytes, "application/pdf"), ...]"""
    with mail_batch() as send:
        return send(to, subject, body, attachments)


@contextmanager
def mail_batch():
    """with mail_batch() as send: send(to, subject, body, attachments) -> "sent" | "logged" (or raises MailError).
    Opens the SMTP connection lazily, reuses it for every email, reconnects once if the server drops it."""
    cfg = current_app.config
    ready, why = mail_ready(cfg)
    if not ready:
        raise MailError(why, "setup")
    state: dict = {"smtp": None}

    def send(to: str, subject: str, body: str, attachments=None) -> str:
        if cfg.get("MAIL_BACKEND") == "console":
            names = ", ".join(a[0] for a in attachments or ()) or "none"
            log.warning("EMAIL (console, not sent) to=%s subject=%s attachments=%s\n%s", to, subject, names, body)
            return "logged"
        msg = _message(cfg, to, subject, body, attachments)
        for tries in range(2):
            if state["smtp"] is None:
                state["smtp"] = _open(cfg)
            try:
                _deliver(state["smtp"], msg)
                return "sent"
            except MailError as exc:
                if exc.kind != "server" or tries == 1:
                    raise
                _close(state)        # connection dropped (servers close idle / long sessions) -> one fresh try
        return "sent"   # not reached

    try:
        yield send
    finally:
        _close(state)


def _close(state: dict) -> None:
    smtp, state["smtp"] = state.get("smtp"), None
    if smtp is not None:
        try:
            smtp.quit()
        except Exception:  # noqa: BLE001  closing must never turn a sent email into an error
            pass
