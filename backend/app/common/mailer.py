"""Phase 7: sends one plain-text email. MAIL_BACKEND=console (default) only writes it to the server log.

send_mail(...) returns "sent" or "logged", and raises MailError with a short, safe reason when sending fails.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


class MailError(Exception):
    pass


def mail_ready(config) -> tuple[bool, str]:
    """(ready, explanation) - shown on the Reports page before sending."""
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


def send_mail(to: str, subject: str, body: str) -> str:
    cfg = current_app.config
    ready, why = mail_ready(cfg)
    if not ready:
        raise MailError(why)
    if cfg.get("MAIL_BACKEND") == "console":
        log.warning("EMAIL (console, not sent) to=%s subject=%s\n%s", to, subject, body)
        return "logged"

    msg = EmailMessage()
    msg["From"] = cfg.get("MAIL_FROM") or cfg["MAIL_USERNAME"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with _connect(cfg) as smtp:
            username, password = cfg.get("MAIL_USERNAME"), cfg.get("MAIL_PASSWORD")
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server refused the username / password.")
    except smtplib.SMTPRecipientsRefused:
        raise MailError("The mail server refused this address.")
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Sending a result email failed: %s", type(exc).__name__)
        raise MailError("The mail server could not be reached or refused the email.")
    return "sent"
