"""Phase 11 table: the admit-card email log. One row per candidate (the latest try), like result_emails.

status:
    sent     -> the mail server accepted the email (it can still bounce later, see below)
    logged   -> MAIL_BACKEND=console: written to the server terminal only (local testing)
    failed   -> not sent; `error` says why in plain words (bad address, domain has no mail server, server refused...)
    bounced  -> it was sent, but a "delivery failed" reply came back later (address not found, mailbox full...)

to_email keeps the address the card went to. If the admin corrects the candidate's email afterwards, the card counts
as "not sent yet" again, because it never reached the new address.
"""
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

ADMIT_STATUSES = ("sent", "logged", "failed", "bounced")


class AdmitCardEmail(db.Model):
    __tablename__ = "admit_card_emails"
    __table_args__ = (
        CheckConstraint("status IN ('sent','logged','failed','bounced')", name="admit_card_status_valid"),
        UniqueConstraint("candidate_id", name="uq_admit_card_emails_candidate"),
    )

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id"), nullable=False, index=True)
    to_email = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(10), nullable=False)
    error = db.Column(db.Unicode(300), nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=1)
    sent_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=False, default=utcnow)     # last try
    bounced_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {"status": self.status, "to": self.to_email, "error": self.error, "attempts": self.attempts,
                "sent_at": iso(self.sent_at), "bounced_at": iso(self.bounced_at)}
