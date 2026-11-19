from sqlalchemy import func, or_

from app.common.errors import ApiError
from app.common.utils import utcnow
from app.extensions import db
from app.models.institution import STATUSES, Institution
from app.models.user import User
from app.modules.directory.service import add_from_approved

# current status -> statuses the Super Admin may move it to
TRANSITIONS = {
    "awaiting_payment": {"rejected"},          # Phase 11: has not paid yet -> can only be turned down (no refund)
    "pending": {"approved", "rejected"},
    "approved": {"suspended"},
    "suspended": {"approved"},
    "rejected": {"approved"},
}


def list_institutions(status: str | None, q: str | None):
    query = Institution.query
    if status:
        if status not in STATUSES:
            raise ApiError("BAD_REQUEST", "Unknown status filter.", 400)
        query = query.filter(Institution.status == status)
    if q:
        like = f"%{q.strip()}%"
        admin_ids = db.session.query(User.institution_id).filter(User.email.ilike(like))
        query = query.filter(or_(Institution.name.ilike(like), Institution.city.ilike(like),
                                 Institution.campus_name.ilike(like), Institution.id.in_(admin_ids)))
    items = query.order_by(Institution.created_at.desc(), Institution.id.desc()).limit(500).all()

    counts = dict.fromkeys(STATUSES, 0)
    for status_value, n in db.session.query(Institution.status, func.count()).group_by(Institution.status):
        counts[status_value] = n
    counts["total"] = sum(counts.values())
    return items, counts


def change_status(institution_id: int, new_status: str, note: str | None, reviewer_email: str) -> Institution:
    """Phase 11: approving starts the paid subscription and emails the institution; rejecting a paid registration
    refunds it automatically and emails the institution. The outcome of the refund is kept on inst._refund."""
    from app.modules.payments import emails as pay_emails
    from app.modules.payments import service as payments

    inst = db.session.get(Institution, institution_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found.", 404)
    if new_status not in STATUSES or new_status in ("pending", "awaiting_payment"):
        raise ApiError("BAD_REQUEST", "Status must be approved, rejected or suspended.", 400)
    if new_status not in TRANSITIONS.get(inst.status, set()):
        if inst.status == "awaiting_payment" and new_status == "approved":
            raise ApiError("NOT_PAID", "This institution has not paid the registration fee yet, so it cannot be "
                           "approved.", 409)
        raise ApiError("INVALID_TRANSITION", f"Cannot change an institution from {inst.status} to {new_status}.", 409)
    reg = inst.registration_payment()
    if new_status == "approved" and inst.status == "rejected" and reg is not None and reg.status == "refunded":
        raise ApiError("PAYMENT_REFUNDED", "This institution's registration fee was refunded when it was rejected, so "
                       "it cannot be approved without paying again.", 409)

    previous = inst.status
    if new_status == "approved":
        add_from_approved(inst)          # Phase 10: a hand-typed institution / campus joins the directory
    inst.status = new_status
    inst.reviewed_at = utcnow()
    inst.reviewed_by_email = reviewer_email
    inst.review_note = (note or "").strip()[:500] or None
    if new_status == "approved" and previous in ("pending", "rejected"):
        payments.start_subscription(inst)
    db.session.commit()

    inst._refund = None
    if new_status == "approved" and previous in ("pending", "rejected"):
        pay_emails.approved(inst)
    elif new_status == "rejected":
        inst._refund = payments.refund_registration(inst) if previous != "awaiting_payment" else None
        pay_emails.rejected(inst, inst._refund)
    return inst


def proof_of(institution_id: int):
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found.", 404)
    if inst.proof is None:
        raise ApiError("NOT_FOUND", "This institution did not upload a proof document.", 404)
    return inst.proof
