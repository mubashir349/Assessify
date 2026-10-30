"""Phase 7: one row per result email sent to a candidate (the "email log" on the Reports page).

A candidate gets at most one row (unique attempt_id); sending again (e.g. after a failure) updates the same row.
status:  sent    -> the mail server accepted it
         failed  -> the mail server refused it or could not be reached (`error` says why)
         logged  -> MAIL_BACKEND=console: nothing was sent, the email was written to the server log (local testing)
"""
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

EMAIL_STATUSES = ("sent", "failed", "logged")


class ResultEmail(db.Model):
    __tablename__ = "result_emails"
    __table_args__ = (
        CheckConstraint("status IN ('sent','failed','logged')", name="result_email_status_valid"),
        UniqueConstraint("attempt_id", name="uq_result_emails_attempt"),
    )

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id"), nullable=False, index=True)
    to_email = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(10), nullable=False)
    error = db.Column(db.Unicode(300), nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=1)        # how many times we tried
    sent_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=False, default=utcnow)    # last try

    def to_dict(self) -> dict:
        return {"status": self.status, "to": self.to_email, "error": self.error, "attempts": self.attempts,
                "sent_at": iso(self.sent_at)}
