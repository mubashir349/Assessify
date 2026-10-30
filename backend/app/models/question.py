"""Phase 3 tables: AI generation attempts and the questions they produce.

Lifecycle of a question (column `status`):
    draft     -> just generated (or edited). Visible only in Draft Review.
    approved  -> checked by an admin. The ONLY status the Question Bank shows. Approved questions are not
                 edited, rejected or regenerated any more, so nothing can overwrite them by accident.
    rejected  -> turned down by an admin (optional reason). Hidden from the bank. Can be regenerated.
    replaced  -> a draft/rejected question that was regenerated. Kept for history; `replaced_by_id`
                 points at the new draft that took its place.

Department / subject / level are stored as a *snapshot* (plain text) as well as `department_id`, so a question
keeps its labels even if the field / department is renamed or deleted later (department_id then becomes NULL).
Text columns use Unicode types so SQL Server stores symbols like ², π, ≤ correctly (NVARCHAR). Long text uses
Unicode() with no length = NVARCHAR(max) (not the old NTEXT type, which SQL Server cannot search with LOWER/LIKE).
"""
from sqlalchemy import CheckConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

# ---- single source of truth for labels; the frontend reads them from GET /meta ----
QUESTION_TYPES = {"mcq": "MCQ", "true_false": "True/False"}
DIFFICULTIES = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}
QUESTION_STATUSES = ("draft", "approved", "rejected", "replaced")
ATTEMPT_STATUSES = ("processing", "completed", "partial", "failed")
TRUE_FALSE_OPTIONS = ["True", "False"]


class GenerationAttempt(db.Model):
    __tablename__ = "generation_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('processing','completed','partial','failed')", name="status_valid"),
        CheckConstraint("question_type IN ('mcq','true_false')", name="question_type_valid"),
        CheckConstraint("difficulty IN ('easy','medium','hard')", name="difficulty_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)

    # snapshot of what was chosen on the Generate screen
    department_name = db.Column(db.Unicode(150), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    subject_name = db.Column(db.Unicode(120), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)
    difficulty = db.Column(db.String(10), nullable=False)
    requested_count = db.Column(db.Integer, nullable=False)
    marks = db.Column(db.Integer, nullable=False, default=1)
    focus = db.Column(db.Unicode(500), nullable=True)            # optional "Description / focus" from the form

    # the uploaded PDF itself is NOT stored - only safe metadata and the extracted text (needed for "Regenerate")
    # source_kind: "pdf" (1+ uploaded PDFs) or "description" (no PDF - questions from the admin's description)
    source_kind = db.Column(db.String(20), nullable=False, default="pdf", server_default="pdf")
    source_files = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    source_filename = db.Column(db.Unicode(255), nullable=False)
    source_pages = db.Column(db.Integer, nullable=False, default=0)
    source_chars = db.Column(db.Integer, nullable=False, default=0)   # characters extracted from the PDF
    source_truncated = db.Column(db.Boolean, nullable=False, default=False)
    source_sha256 = db.Column(db.String(64), nullable=False, index=True)
    # True = the PDF was photos / scans and the AI read the text from the pictures (OCR) - review extra carefully
    source_ocr = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    source_text = db.Column(db.Unicode(), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="processing", index=True)
    generated_count = db.Column(db.Integer, nullable=False, default=0)
    discarded_count = db.Column(db.Integer, nullable=False, default=0)   # AI items that failed validation
    error_code = db.Column(db.String(50), nullable=True)
    error_message = db.Column(db.Unicode(500), nullable=True)          # safe, human-readable only
    provider = db.Column(db.String(30), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    questions = db.relationship("Question", back_populates="attempt", lazy="selectin",
                                order_by="Question.position, Question.id")
    created_by = db.relationship("User")

    def counts(self) -> dict:
        c = dict.fromkeys(QUESTION_STATUSES, 0)
        for q in self.questions:
            c[q.status] = c.get(q.status, 0) + 1
        return c

    def to_dict(self, with_questions: bool = False, include_replaced: bool = False) -> dict:
        data = {
            "id": self.id,
            "department_id": self.department_id,
            "department_name": self.department_name,
            "level": self.level,
            "subject": self.subject_name,
            "question_type": self.question_type,
            "difficulty": self.difficulty,
            "requested_count": self.requested_count,
            "marks": self.marks,
            "focus": self.focus,
            "source": {"kind": self.source_kind or "pdf", "files": self.source_files,
                       "filename": self.source_filename, "pages": self.source_pages,
                       "characters": self.source_chars, "truncated": self.source_truncated,
                       "ocr": bool(self.source_ocr)},
            "status": self.status,
            "generated_count": self.generated_count,
            "discarded_count": self.discarded_count,
            "error": {"code": self.error_code, "message": self.error_message} if self.error_code else None,
            "provider": self.provider,
            "model": self.model,
            "counts": self.counts(),
            "created_by": self.created_by.full_name if self.created_by else None,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }
        if with_questions:
            data["questions"] = [q.to_dict() for q in self.questions if include_replaced or q.status != "replaced"]
        return data


class Question(db.Model):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','approved','rejected','replaced')", name="status_valid"),
        CheckConstraint("question_type IN ('mcq','true_false')", name="question_type_valid"),
        CheckConstraint("difficulty IN ('easy','medium','hard')", name="difficulty_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("generation_attempts.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    department_name = db.Column(db.Unicode(150), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    subject_name = db.Column(db.Unicode(120), nullable=False)
    topic = db.Column(db.Unicode(120), nullable=True)

    question_type = db.Column(db.String(20), nullable=False)
    text = db.Column(db.Unicode(), nullable=False)
    options = db.Column(db.JSON, nullable=False)                  # list of strings
    correct_index = db.Column(db.Integer, nullable=False)          # 0-based index into options
    explanation = db.Column(db.Unicode(), nullable=True)
    difficulty = db.Column(db.String(10), nullable=False)
    marks = db.Column(db.Integer, nullable=False, default=1)
    position = db.Column(db.Integer, nullable=False, default=0)   # order inside its attempt

    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    is_edited = db.Column(db.Boolean, nullable=False, default=False)
    rejection_reason = db.Column(db.Unicode(500), nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    regenerated_from_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=True)
    replaced_by_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    attempt = db.relationship("GenerationAttempt", back_populates="questions")
    reviewed_by = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "attempt_id": self.attempt_id,
            "department_id": self.department_id,
            "department_name": self.department_name,
            "level": self.level,
            "subject": self.subject_name,
            "topic": self.topic,
            "question_type": self.question_type,
            "text": self.text,
            "options": list(self.options or []),
            "correct_index": self.correct_index,
            "explanation": self.explanation,
            "difficulty": self.difficulty,
            "marks": self.marks,
            "status": self.status,
            "is_edited": self.is_edited,
            "rejection_reason": self.rejection_reason,
            "reviewed_by": self.reviewed_by.full_name if self.reviewed_by else None,
            "reviewed_at": iso(self.reviewed_at),
            "regenerated_from_id": self.regenerated_from_id,
            "replaced_by_id": self.replaced_by_id,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }
