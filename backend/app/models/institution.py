from sqlalchemy import CheckConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

STATUSES = ("pending", "approved", "rejected", "suspended")
INSTITUTION_TYPES = ("University", "College", "Institute", "Training Center")


class Institution(db.Model):
    __tablename__ = "institutions"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','suspended')", name="status_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(30), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    website = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_email = db.Column(db.String(255), nullable=True)
    review_note = db.Column(db.String(500), nullable=True)

    users = db.relationship("User", back_populates="institution", lazy="selectin")

    def primary_admin(self):
        admins = [u for u in self.users if u.role == "institution_admin"]
        return min(admins, key=lambda u: u.id) if admins else None

    def to_dict(self) -> dict:
        admin = self.primary_admin()
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "city": self.city,
            "website": self.website,
            "status": self.status,
            "created_at": iso(self.created_at),
            "reviewed_at": iso(self.reviewed_at),
            "review_note": self.review_note,
            "admin": {"full_name": admin.full_name, "email": admin.email, "phone": admin.phone,
                      "designation": admin.designation} if admin else None,
        }
