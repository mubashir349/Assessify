from sqlalchemy import CheckConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from app.common.utils import iso, utcnow
from app.extensions import db

ROLE_SUPER_ADMIN = "super_admin"
ROLE_INSTITUTION_ADMIN = "institution_admin"
ROLES = (ROLE_SUPER_ADMIN, ROLE_INSTITUTION_ADMIN)  # candidates log in through their own flow (Phase 5)

# Used to spend the same time on "unknown email" as on "wrong password" (no user enumeration by timing).
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('super_admin','institution_admin')", name="role_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True, index=True)  # NULL = platform staff
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=True)
    designation = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    institution = db.relationship("Institution", back_populates="users")

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @staticmethod
    def burn_password_check(raw: str) -> None:
        check_password_hash(_DUMMY_HASH, raw)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role,
            "created_at": iso(self.created_at),
            "institution": {"id": self.institution.id, "name": self.institution.name, "type": self.institution.type,
                            "status": self.institution.status} if self.institution else None,
        }
