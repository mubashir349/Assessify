"""Phase 4 tables: an aptitude test, its paper composition (one row per subject line) and its schedule.

Lifecycle (column `status`):
    draft      -> saved from the Create Test wizard. Can be edited or deleted.
    published  -> passed the 1.5x pool check and the schedule check. Locked: no edits, no delete.

Composition rows point at a department (FK) and store the subject as a name, the same way Phase 3 questions do,
so the pool check is a plain match on (department, subject, type, difficulty).
The department FK has NO cascade on purpose: SQL Server refuses a second cascade path into test_compositions,
and a test must never lose part of its paper silently. Deleting a department a test uses is refused instead (409).

All datetimes are naive UTC, like everywhere else in the database.
"""
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.common.utils import iso, utcnow
from app.extensions import db
from app.models.department import LEVELS

# ---- single source of truth; the frontend reads these from GET /meta ----
POOL_FACTOR = 1.5          # pool needed = ceil(per-candidate count x 1.5), so candidates get different random papers
ANY_DIFFICULTY = "any"
TEST_STATUSES = ("draft", "published")
TIMING_MODES = {
    "flexible": {"label": "Flexible window",
                 "description": "Each candidate gets their own timer from when they start, inside the window"},
    "fixed": {"label": "Fixed time",
              "description": "Everyone starts and ends together; a late starter gets less time"},
}
RESULT_RELEASES = {"immediate": "Show score immediately on submission", "scheduled": "Release later via email"}
MAX_PER_ROW = 200           # questions per candidate in one composition row
MIN_DURATION, MAX_DURATION = 5, 600   # minutes


class AptitudeTest(db.Model):
    __tablename__ = "tests"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published')", name="status_valid"),
        CheckConstraint("level IN ('Undergraduate','Masters','PhD')", name="level_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.Unicode(200), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(15), nullable=False, default="draft", index=True)
    published_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    rows = db.relationship("Composition", back_populates="test", cascade="all, delete-orphan",
                           order_by="Composition.position", lazy="selectin")
    schedule = db.relationship("Schedule", back_populates="test", cascade="all, delete-orphan",
                               uselist=False, lazy="selectin")

    def departments(self) -> list:
        seen, out = set(), []
        for r in self.rows:
            if r.department_id not in seen:
                seen.add(r.department_id)
                out.append(r.department)
        return out

    def summary_dict(self) -> dict:
        per_candidate: dict = {}
        for r in self.rows:
            per_candidate[str(r.department_id)] = per_candidate.get(str(r.department_id), 0) + r.question_count
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level,
            "term": LEVELS[self.level]["term"],
            "status": self.status,
            "departments": [{"id": d.id, "name": d.name, "mode": d.mode} for d in self.departments()],
            "questions_per_candidate": per_candidate,
            "schedule": self.schedule.to_dict() if self.schedule else None,
            "published_at": iso(self.published_at),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def to_dict(self) -> dict:
        data = self.summary_dict()
        data["compositions"] = [
            {"department_id": d.id, "rows": [r.to_dict() for r in self.rows if r.department_id == d.id]}
            for d in self.departments()
        ]
        return data


class Composition(db.Model):
    __tablename__ = "test_compositions"
    __table_args__ = (
        UniqueConstraint("test_id", "department_id", "subject_name", "question_type", "difficulty",
                         name="uq_test_compositions_row"),
        CheckConstraint("question_type IN ('mcq','true_false')", name="question_type_valid"),
        CheckConstraint("difficulty IN ('any','easy','medium','hard')", name="difficulty_valid"),
        CheckConstraint(f"question_count BETWEEN 1 AND {MAX_PER_ROW}", name="count_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    subject_name = db.Column(db.Unicode(120), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)
    difficulty = db.Column(db.String(10), nullable=False)
    question_count = db.Column(db.Integer, nullable=False)   # per candidate
    position = db.Column(db.Integer, nullable=False, default=0)

    test = db.relationship("AptitudeTest", back_populates="rows")
    department = db.relationship("Department", lazy="joined")

    def to_dict(self) -> dict:
        return {"id": self.id, "subject": self.subject_name, "question_type": self.question_type,
                "difficulty": self.difficulty, "count": self.question_count}


class Schedule(db.Model):
    __tablename__ = "test_schedules"
    __table_args__ = (
        CheckConstraint("timing_mode IN ('flexible','fixed')", name="timing_mode_valid"),
        CheckConstraint("result_release IN ('immediate','scheduled')", name="result_release_valid"),
        CheckConstraint("ends_at > starts_at", name="window_valid"),
    )

    test_id = db.Column(db.Integer, db.ForeignKey("tests.id", ondelete="CASCADE"), primary_key=True)
    timing_mode = db.Column(db.String(10), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)     # flexible: window opens · fixed: everyone starts
    ends_at = db.Column(db.DateTime, nullable=False)       # flexible: window closes · fixed: hard stop for everyone
    duration_minutes = db.Column(db.Integer, nullable=False)   # flexible: per-candidate timer · fixed: ends - starts
    result_release = db.Column(db.String(10), nullable=False)
    release_on = db.Column(db.Date, nullable=True)         # required when result_release = scheduled

    test = db.relationship("AptitudeTest", back_populates="schedule")

    def to_dict(self) -> dict:
        return {
            "timing_mode": self.timing_mode,
            "starts_at": iso(self.starts_at),
            "ends_at": iso(self.ends_at),
            "duration_minutes": self.duration_minutes,
            "result_release": self.result_release,
            "release_on": self.release_on.isoformat() if self.release_on else None,
        }
