"""Phase 2 tables: a Department (Field for Undergraduate) belongs to one institution and owns its Subjects."""
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

# Single source of truth. The frontend reads these from GET /api/v1/meta - it hardcodes none of them.
LEVELS = {
    "Undergraduate": {"term": "Field", "term_plural": "Fields",
                      "name_placeholder": "e.g. Pre-Engineering, Commerce"},
    "Masters": {"term": "Department", "term_plural": "Departments",
                "name_placeholder": "e.g. Data Science, Physics"},
    "PhD": {"term": "Department", "term_plural": "Departments",
            "name_placeholder": "e.g. Data Science, Physics"},
}
MODES = {
    "general": {"label": "General test", "description": "Same subjects for every student (e.g. Maths + English)"},
    "field": {"label": "Specific to a field / department", "description": "Own subjects per field"},
}
DEFAULT_LEVEL = "Undergraduate"
DEFAULT_MODE = "field"
MAX_SUBJECTS = 50


class Department(db.Model):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("institution_id", "level", "name", name="uq_departments_institution_level_name"),
        CheckConstraint("mode IN ('general','field')", name="mode_valid"),
        CheckConstraint("level IN ('Undergraduate','Masters','PhD')", name="level_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    mode = db.Column(db.String(10), nullable=False, default=DEFAULT_MODE)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    subjects = db.relationship("Subject", back_populates="department", cascade="all, delete-orphan",
                               order_by="Subject.position", lazy="selectin")

    def to_dict(self) -> dict:
        term = LEVELS[self.level]["term"]
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level,
            "term": term,
            "mode": self.mode,
            "subjects": [s.name for s in self.subjects],
            "subject_count": len(self.subjects),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }


class Subject(db.Model):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("department_id", "name", name="uq_subjects_department_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    department = db.relationship("Department", back_populates="subjects")
