"""Phase 6 tables: a candidate's attempt at their test, the random paper built for it, and its lock events.

One candidate has at most ONE attempt (unique candidate_id). It is created when the candidate presses Start, and the
paper is drawn at that moment from the institution's APPROVED questions, so every candidate gets their own random
selection, question order and MCQ option order.

Lifecycle (column `status`):
    in_progress -> started, answers are saved one by one.
    locked      -> the browser reported a fullscreen exit / tab switch. Answers are refused until an Institution Admin
                   unlocks it (Phase 7 monitor). Fixed time keeps running; a flexible timer is frozen.
    submitted   -> final. Scored on the server. `submit_reason` = candidate | time_up | admin (ended from the monitor).

Times are naive UTC like everywhere else. `deadline_at` is the moment the paper closes for THIS candidate:
    fixed    -> the test's end time (a late starter gets less time),
    flexible -> started_at + duration, never after the window's end (moved forward by the locked time on unlock).

Paper items point at the approved question (approved questions are never edited or deleted) and store the shuffled
option order, so the candidate's answer is kept as the ORIGINAL option index and scoring is a plain comparison.
The correct answer is never sent to the candidate - see ExamAttempt.paper_dict / PaperItem.candidate_dict.
"""
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

ATTEMPT_STATUSES = ("in_progress", "locked", "submitted")
SUBMIT_REASONS = ("candidate", "time_up", "admin")
# What the browser may report as the reason for a lock. Anything else is stored as "other".
LOCK_REASONS = {
    "fullscreen_exit": "Left fullscreen",
    "tab_hidden": "Switched tab or minimised the window",
    "other": "Left the test window",
}


class ExamAttempt(db.Model):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('in_progress','locked','submitted')", name="status_valid"),
        UniqueConstraint("candidate_id", name="uq_exam_attempts_candidate"),
    )

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id"), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id"), nullable=False, index=True)
    status = db.Column(db.String(15), nullable=False, default="in_progress", index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    deadline_at = db.Column(db.DateTime, nullable=False)
    locked_at = db.Column(db.DateTime, nullable=True)          # set while status = locked
    lock_count = db.Column(db.Integer, nullable=False, default=0)
    submitted_at = db.Column(db.DateTime, nullable=True)
    submit_reason = db.Column(db.String(15), nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)       # Phase 7: last request from the candidate's page

    # filled once, on submit (server-side scoring)
    score = db.Column(db.Integer, nullable=True)
    max_score = db.Column(db.Integer, nullable=False, default=0)
    correct_count = db.Column(db.Integer, nullable=True)
    answered_count = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    candidate = db.relationship("Candidate", lazy="joined")
    test = db.relationship("AptitudeTest")
    items = db.relationship("PaperItem", back_populates="attempt", cascade="all, delete-orphan",
                            order_by="PaperItem.position", lazy="selectin")
    events = db.relationship("LockEvent", back_populates="attempt", cascade="all, delete-orphan",
                             order_by="LockEvent.id", lazy="selectin")
    result_email = db.relationship("ResultEmail", uselist=False, viewonly=True, lazy="selectin")   # Phase 7

    @property
    def reference(self) -> str:
        """What the lock screen shows, so the proctor can find the attempt: APT-<year>-<id>."""
        return f"APT-{self.started_at.year}-{self.id:05d}"

    def remaining_seconds(self, now) -> int:
        """Locked + flexible: the timer is frozen at the moment of the lock."""
        until = self.locked_at if (self.status == "locked" and self.test.schedule.timing_mode == "flexible") else now
        return max(0, int((self.deadline_at - until).total_seconds()))

    def to_dict(self, now=None) -> dict:
        """Status for the candidate. Never contains answers' correctness."""
        now = now or utcnow()
        answered = sum(1 for i in self.items if i.answer_index is not None)
        return {
            "id": self.id,
            "reference": self.reference,
            "status": self.status,
            "timing_mode": self.test.schedule.timing_mode,
            "started_at": iso(self.started_at),
            "deadline_at": iso(self.deadline_at),
            "remaining_seconds": 0 if self.status == "submitted" else self.remaining_seconds(now),
            "server_now": iso(now),
            "locked_at": iso(self.locked_at),
            "lock_count": self.lock_count,
            "submitted_at": iso(self.submitted_at),
            "submit_reason": self.submit_reason,
            "question_count": len(self.items),
            "answered_count": answered,
        }

    def admin_dict(self, now=None) -> dict:
        """For the institution admin (roster now, monitor in Phase 7): adds the score and the lock history."""
        return {**self.to_dict(now), "score": self.score, "max_score": self.max_score,
                "correct_count": self.correct_count, "events": [e.to_dict() for e in self.events]}

    def paper_dict(self) -> list[dict]:
        load_question_texts([i.question for i in self.items])
        return [i.candidate_dict() for i in self.items]


def load_question_texts(questions: list) -> None:
    """Phase 8 (load test): exam requests load the paper's questions WITHOUT their long text columns (fetching
    NVARCHAR(MAX) rows is the slowest part on SQL Server). When the whole paper is shown, fetch the texts of all
    its questions in ONE query instead of one query per question."""
    from sqlalchemy import inspect, select
    from sqlalchemy.orm import load_only

    from app.models.question import Question
    missing = [q.id for q in questions if "text" in inspect(q).unloaded]
    if missing:
        db.session.execute(select(Question).where(Question.id.in_(missing))
                           .options(load_only(Question.text, Question.options))
                           .execution_options(populate_existing=True)).scalars().all()


class PaperItem(db.Model):
    __tablename__ = "exam_paper_items"
    __table_args__ = (
        UniqueConstraint("attempt_id", "position", name="uq_exam_paper_items_position"),
    )

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)              # 1-based question number on the paper
    subject_name = db.Column(db.Unicode(120), nullable=False)
    option_order = db.Column(db.JSON, nullable=False)              # shown option j = question.options[option_order[j]]
    marks = db.Column(db.Integer, nullable=False, default=1)
    answer_index = db.Column(db.Integer, nullable=True)            # ORIGINAL option index the candidate chose
    flagged = db.Column(db.Boolean, nullable=False, default=False)
    answered_at = db.Column(db.DateTime, nullable=True)
    is_correct = db.Column(db.Boolean, nullable=True)              # set on submit

    attempt = db.relationship("ExamAttempt", back_populates="items")
    question = db.relationship("Question", lazy="joined")

    def shown_choice(self):
        """The candidate's answer as the position they clicked (0-based), or None."""
        if self.answer_index is None:
            return None
        return list(self.option_order).index(self.answer_index)

    def candidate_dict(self) -> dict:
        """One question as the candidate sees it. NO correct answer, explanation, difficulty or question id."""
        q = self.question
        return {
            "number": self.position,
            "subject": self.subject_name,
            "question_type": q.question_type,
            "text": q.text,
            "options": [q.options[k] for k in self.option_order],
            "marks": self.marks,
            "choice": self.shown_choice(),
            "flagged": self.flagged,
        }


class LockEvent(db.Model):
    __tablename__ = "exam_lock_events"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(15), nullable=False)               # lock | unlock
    reason = db.Column(db.String(30), nullable=True)              # LOCK_REASONS key (lock only)
    by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)   # the admin who unlocked
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    attempt = db.relationship("ExamAttempt", back_populates="events")
    by_user = db.relationship("User")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "reason": self.reason, "by": self.by_user.full_name if self.by_user else None,
                "at": iso(self.created_at)}
