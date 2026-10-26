"""GET /dashboard/summary - real numbers for the Institution Admin dashboard (nothing is hardcoded)."""
from flask import Blueprint, g
from sqlalchemy import func

from app.common.decorators import auth_required
from app.common.responses import ok
from app.extensions import db
from app.models.department import Department, Subject
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
    })
