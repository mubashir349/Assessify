from sqlalchemy import CheckConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

STATUSES = ("pending", "approved", "rejected", "suspended")
INSTITUTION_TYPES = ("University", "College", "School", "Institute", "Training Center")


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
    # Phase 10: which directory campus this is (NULL = typed by hand; filled in when the Super Admin approves it)
    directory_campus_id = db.Column(db.Integer, db.ForeignKey("directory_campuses.id"), nullable=True, index=True)
    directory_institution_id = db.Column(db.Integer, db.ForeignKey("directory_institutions.id"), nullable=True)
    campus_name = db.Column(db.Unicode(120), nullable=True)
    from_directory = db.Column(db.Boolean, nullable=False, default=False)          # picked from the list at signup
    email_domain_verified = db.Column(db.Boolean, nullable=False, default=False)   # admin email matches the domain
    no_official_email = db.Column(db.Boolean, nullable=False, default=False)       # free email + proof document

    users = db.relationship("User", back_populates="institution", lazy="selectin")
    proof = db.relationship("InstitutionProof", uselist=False, lazy="select", cascade="all, delete-orphan")

    @property
    def display_name(self) -> str:
        return f"{self.name} · {self.campus_name}" if self.campus_name else self.name

    def primary_admin(self):
        admins = [u for u in self.users if u.role == "institution_admin"]
        return min(admins, key=lambda u: u.id) if admins else None

    def to_dict(self) -> dict:
        admin = self.primary_admin()
        return {
            "id": self.id,
            "name": self.name,
            "campus_name": self.campus_name,
            "display_name": self.display_name,
            "type": self.type,
            "city": self.city,
            "website": self.website,
            "status": self.status,
            "created_at": iso(self.created_at),
            "reviewed_at": iso(self.reviewed_at),
            "review_note": self.review_note,
            "from_directory": bool(self.from_directory),
            "email_domain_verified": bool(self.email_domain_verified),
            "no_official_email": bool(self.no_official_email),
            "has_proof": self.proof is not None,
            "admin": {"full_name": admin.full_name, "email": admin.email} if admin else None,
        }
