"""GET /dashboard/summary - real numbers for the Institution Admin dashboard (nothing is hardcoded).

Phase 7 adds tests (live / upcoming), candidates, live attempts, average score and the question bank."""
from flask import Blueprint, g
from sqlalchemy import func

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.utils import iso, utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import Candidate
from app.models.department import Department, Subject
from app.models.exam import ExamAttempt
from app.models.question import Question
from app.modules.exam.service import finalize_if_overdue
from app.modules.monitor.service import test_state
from app.models.user import ROLE_INSTITUTION_ADMIN

bp = Blueprint("dashboard", __name__)


@bp.get("/summary")
@auth_required(ROLE_INSTITUTION_ADMIN)
def summary():
    inst_id = g.current_user.institution_id
    depts = Department.query.filter_by(institution_id=inst_id).order_by(Department.created_at.desc(), Department.id.desc()).all()
    subject_count = (db.session.query(func.count(Subject.id)).join(Department, Subject.department_id == Department.id)
                     .filter(Department.institution_id == inst_id).scalar()) or 0
    by_level: dict = {}
    for d in depts:
        by_level[d.level] = by_level.get(d.level, 0) + 1
    return ok({
        "institution": {"name": g.current_user.institution.name},
        "departments": {"total": len(depts), "by_level": by_level,
                        "general_tests": sum(1 for d in depts if d.mode == "general"),
                        "recent": [{"id": d.id, "name": d.name, "level": d.level, "subject_count": len(d.subjects)} for d in depts[:5]]},
        "subjects": {"total": subject_count},
        **_phase7_numbers(inst_id),
    })


def _phase7_numbers(inst_id: int) -> dict:
    now = utcnow()
    tests = AptitudeTest.query.filter_by(institution_id=inst_id).all()
    published = [t for t in tests if t.status == "published"]
    states = [test_state(t, now) for t in published]
    attempts = (ExamAttempt.query.join(Candidate, ExamAttempt.candidate_id == Candidate.id)
                .filter(Candidate.institution_id == inst_id).all())
    for a in attempts:
        finalize_if_overdue(a, now)          # a timer that ran out counts as submitted
    done = [a for a in attempts if a.status == "submitted" and a.max_score]
    questions = dict(db.session.query(Question.status, func.count(Question.id))
                     .filter(Question.institution_id == inst_id).group_by(Question.status).all())
    upcoming = sorted((t for t in published if test_state(t, now) == "upcoming"), key=lambda t: t.schedule.starts_at)
    return {
        "tests": {"total": len(tests), "published": len(published), "draft": len(tests) - len(published),
                  "live": states.count("live"), "upcoming": states.count("upcoming"), "ended": states.count("ended"),
                  "next": [{"id": t.id, "name": t.name, "starts_at": iso(t.schedule.starts_at)} for t in upcoming[:3]]},
        "candidates": {"total": Candidate.query.filter_by(institution_id=inst_id).count(),
                       "in_progress": sum(1 for a in attempts if a.status == "in_progress"),
                       "locked": sum(1 for a in attempts if a.status == "locked"),
                       "submitted": len(done)},
        "average_percent": round(sum(100 * a.score / a.max_score for a in done) / len(done), 1) if done else None,
        "questions": {"approved": questions.get("approved", 0), "waiting_review": questions.get("draft", 0)},
    }
