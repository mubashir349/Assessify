"""Phase 11 table: payments (registration fee and renewals), made through Safepay's hosted checkout.

One row per checkout started. The gateway's session id is the "tracker" (track_...). A payment only becomes `paid`
after the backend has asked Safepay itself (GET /reporter/api/v1/payments/<tracker>, signed with the secret key) and
seen TRACKER_ENDED with the right amount. The browser landing on the "success" page proves nothing on its own.

status:
    created        -> checkout started, the institution has not finished paying yet
    paid           -> Safepay confirmed it
    failed         -> Safepay reported the payment failed
    cancelled      -> the institution cancelled on the checkout page, or the session expired
    refunded       -> money sent back (automatic when the Super Admin rejects the registration)
    refund_failed  -> the automatic refund was refused; the Super Admin can retry, or refund in the Safepay
                      dashboard and mark it as refunded by hand

Amounts are stored in paisa (PKR x 100), the unit Safepay uses.
"""
from sqlalchemy import CheckConstraint, Index

from app.common.utils import iso, utcnow
from app.extensions import db

PAYMENT_STATUSES = ("created", "paid", "failed", "cancelled", "refunded", "refund_failed")
PURPOSES = ("registration", "renewal")


class Payment(db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("status IN ('created','paid','failed','cancelled','refunded','refund_failed')",
                        name="status_valid"),
        CheckConstraint("purpose IN ('registration','renewal')", name="purpose_valid"),
        CheckConstraint("[plan] IN ('monthly','yearly')", name="plan_valid"),   # [plan]: PLAN is reserved in SQL Server
        # unique only when filled in: SQL Server allows a single NULL in a plain UNIQUE constraint
        Index("uq_payments_tracker", "tracker", unique=True,
              mssql_where=db.text("tracker IS NOT NULL"), sqlite_where=db.text("tracker IS NOT NULL")),
        Index("uq_payments_receipt_no", "receipt_no", unique=True,
              mssql_where=db.text("receipt_no IS NOT NULL"), sqlite_where=db.text("receipt_no IS NOT NULL")),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    purpose = db.Column(db.String(20), nullable=False, default="registration")
    plan = db.Column(db.String(10), nullable=False)
    amount_minor = db.Column(db.Integer, nullable=False)          # paisa
    currency = db.Column(db.String(3), nullable=False, default="PKR")
    provider = db.Column(db.String(20), nullable=False, default="safepay")
    environment = db.Column(db.String(12), nullable=False, default="sandbox")
    tracker = db.Column(db.String(100), nullable=True)                 # Safepay session id (track_...)
    status = db.Column(db.String(15), nullable=False, default="created", index=True)
    gateway_state = db.Column(db.String(40), nullable=True)            # last tracker state seen, e.g. TRACKER_ENDED
    receipt_no = db.Column(db.String(30), nullable=True)               # ours, e.g. ASY-2026-000012
    card_hint = db.Column(db.Unicode(60), nullable=True)               # e.g. "VISA ending 1005" (never the card)
    failure_reason = db.Column(db.Unicode(300), nullable=True)
    refund_error = db.Column(db.Unicode(300), nullable=True)
    refund_note = db.Column(db.Unicode(300), nullable=True)            # "refunded by hand in the Safepay dashboard"
    failure_email_sent = db.Column(db.Boolean, nullable=False, default=False)   # "payment not completed" mail sent once
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)

    institution = db.relationship("Institution", back_populates="payments")

    @property
    def amount(self) -> float:
        return self.amount_minor / 100

    def to_dict(self) -> dict:
        return {
            "id": self.id, "purpose": self.purpose, "plan": self.plan, "amount": self.amount,
            "currency": self.currency, "provider": self.provider, "environment": self.environment,
            "status": self.status, "receipt_no": self.receipt_no, "card_hint": self.card_hint,
            "reference": self.tracker, "failure_reason": self.failure_reason, "refund_error": self.refund_error,
            "refund_note": self.refund_note, "created_at": iso(self.created_at), "paid_at": iso(self.paid_at),
            "refunded_at": iso(self.refunded_at),
        }
