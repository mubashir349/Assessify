"""Phase 7 - result emails. The admin presses "Send results" on the Reports page; each submitted candidate gets one
plain-text email with their score and per-subject marks. Every try is recorded in result_emails (the email log).

Sending again only goes to candidates that were not sent yet or failed, unless `resend` is true.
"""
from flask import current_app

from app.common.errors import ApiError
from app.common.mailer import MailError, mail_ready, send_mail
from app.common.utils import utcnow
from app.extensions import db
from app.models.candidate import Candidate
from app.models.report import ResultEmail
from app.modules.reports.service import load, percent

MAX_PER_REQUEST = 500


def _subject_lines(attempt) -> list[str]:
    subjects: dict[str, list[int]] = {}
    for i in attempt.items:
        s = subjects.setdefault(i.subject_name, [0, 0])
        s[0] += i.marks if i.is_correct else 0
        s[1] += i.marks
    return [f"  {name}: {got} / {out_of}" for name, (got, out_of) in subjects.items()]


def compose(c: Candidate) -> tuple[str, str]:
    a, t = c.attempt, c.test
    body = "\n".join([
        f"Dear {c.full_name},",
        "",
        f"Your result for {t.name} ({c.institution.name}):",
        "",
        f"  Score: {a.score} / {a.max_score} ({percent(a.score, a.max_score)}%)",
        f"  Correct answers: {a.correct_count} of {len(a.items)}",
        "",
        "By subject:",
        *_subject_lines(a),
        "",
        *([f"Roll number: {c.roll_number}", ""] if c.roll_number else []),
        "This email was sent automatically. Please contact your institution if you have questions.",
    ])
    return f"Your result: {t.name}", body


def _ids(data: dict) -> set[int] | None:
    raw = data.get("candidate_ids")
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw):
        raise ApiError("VALIDATION_ERROR", "candidate_ids must be a list of numbers.", 422,
                       {"candidate_ids": "Send a list of candidate ids, or leave it out to send to everyone."})
    return set(raw)


def _targets(candidates: list[Candidate], ids: set[int] | None, resend: bool) -> list[Candidate]:
    out = []
    for c in candidates:
        a = c.attempt
        if a is None or a.status != "submitted" or (ids is not None and c.id not in ids) or not c.email:
            continue                      # Phase 9: a candidate without an email is skipped (shown as "no email")
        if resend or a.result_email is None or a.result_email.status == "failed":
            out.append(c)
    return out


def _record(c: Candidate, status: str, error: str | None, user) -> None:
    row = ResultEmail.query.filter_by(attempt_id=c.attempt.id).first()
    if row is None:
        row = ResultEmail(attempt_id=c.attempt.id, test_id=c.test_id, attempts=0)
        db.session.add(row)
    row.to_email, row.status, row.error = c.email, status, error
    row.attempts = (row.attempts or 0) + 1
    row.sent_by_id, row.sent_at = user.id, utcnow()


def send_results(user, test_id, data: dict) -> dict:
    """POST /reports/tests/<id>/send-results {candidate_ids?: [..], resend?: bool}"""
    ready, why = mail_ready(current_app.config)
    if not ready:
        raise ApiError("MAIL_NOT_CONFIGURED", why, 503)
    ids, resend = _ids(data), data.get("resend") is True
    _, candidates, _ = load(user.institution_id, test_id)
    targets = _targets(candidates, ids, resend)
    if len(targets) > MAX_PER_REQUEST:
        targets = targets[:MAX_PER_REQUEST]
    counts = {"sent": 0, "logged": 0, "failed": 0}
    for c in targets:
        subject, body = compose(c)
        try:
            # Results are already saved and submitted at this point. Attach the same branded PDF that
            # teachers can download; never attach question text or answer keys.
            from app.modules.reports.pdf import render_student_result
            pdf_data = render_student_result(c, current_app.config.get("ADMIT_CARD_FONT", ""),
                                             current_app.config.get("APP_TIMEZONE", "Asia/Karachi"))
            filename = "Result - " + "".join(ch if ch.isalnum() or ch in " -_" else "-" for ch in c.full_name)[:70]
            attachment = (filename.strip() + ".pdf", pdf_data, "application/pdf")
            status, error = send_mail(c.email, subject, body, [attachment]), None
        except MailError as exc:
            status, error = "failed", str(exc)[:300]
        _record(c, status, error, user)
        counts[status] += 1
        db.session.commit()
    remaining = len(_targets(candidates, ids, False))
    return {**counts, "tried": len(targets), "remaining": remaining}
