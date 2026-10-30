from sqlalchemy import func, or_

from app.common.errors import ApiError
from app.common.utils import utcnow
from app.extensions import db
from app.models.institution import STATUSES, Institution
from app.models.user import User

# current status -> statuses the Super Admin may move it to
TRANSITIONS = {
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
        query = query.filter(or_(Institution.name.ilike(like), Institution.city.ilike(like), Institution.id.in_(admin_ids)))
    items = query.order_by(Institution.created_at.desc(), Institution.id.desc()).limit(500).all()

    counts = dict.fromkeys(STATUSES, 0)
    for status_value, n in db.session.query(Institution.status, func.count()).group_by(Institution.status):
        counts[status_value] = n
    counts["total"] = sum(counts.values())
    return items, counts


def change_status(institution_id: int, new_status: str, note: str | None, reviewer_email: str) -> Institution:
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found.", 404)
    if new_status not in STATUSES or new_status == "pending":
        raise ApiError("BAD_REQUEST", "Status must be approved, rejected or suspended.", 400)
    if new_status not in TRANSITIONS.get(inst.status, set()):
        raise ApiError("INVALID_TRANSITION", f"Cannot change an institution from {inst.status} to {new_status}.", 409)

    inst.status = new_status
    inst.reviewed_at = utcnow()
    inst.reviewed_by_email = reviewer_email
    inst.review_note = (note or "").strip()[:500] or None
    db.session.commit()
    return inst
