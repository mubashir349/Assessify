"""Business rules for fields / departments and their subjects.
Every query is scoped to the caller's institution, so one institution can never see or touch another's data."""
from sqlalchemy.exc import IntegrityError

from app.common.errors import ApiError
from app.common.validation import raise_if, text
from app.extensions import db
from app.models.department import LEVELS, MAX_SUBJECTS, MODES, Department, Subject
from app.common.utils import utcnow


def list_departments(institution_id: int, level: str | None, q: str | None) -> list[Department]:
    query = Department.query.filter_by(institution_id=institution_id)
    if level:
        if level not in LEVELS:
            raise ApiError("BAD_REQUEST", "Unknown level filter.", 400)
        query = query.filter(Department.level == level)
    if q and q.strip():
        query = query.filter(Department.name.ilike(f"%{q.strip()}%"))
    return query.order_by(Department.mode.asc(), Department.name.asc(), Department.id.asc()).all()


def get_department(institution_id: int, department_id: int) -> Department:
    dept = Department.query.filter_by(id=department_id, institution_id=institution_id).first()
    if dept is None:
        raise ApiError("NOT_FOUND", "Field / department not found.", 404)
    return dept


def _clean(data: dict) -> tuple[str, str, str, list[str]]:
    errors: dict = {}
    name = text(data, "name", "Name", errors, min_len=2, max_len=150)
    level = data.get("level")
    mode = data.get("mode")
    if level not in LEVELS:
        errors["level"] = "Choose one of: " + ", ".join(LEVELS) + "."
    if mode not in MODES:
        errors["mode"] = "Choose one of: " + ", ".join(MODES) + "."

    raw = data.get("subjects")
    subjects: list[str] = []
    if not isinstance(raw, list) or not raw:
        errors["subjects"] = "Add at least one subject."
    else:
        seen = set()
        for item in raw:
            s = item.strip() if isinstance(item, str) else ""
            if not s:
                continue
            if len(s) > 120:
                errors["subjects"] = "Each subject must be at most 120 characters."
                break
            if s.lower() not in seen:
                seen.add(s.lower())
                subjects.append(s)
        if "subjects" not in errors:
            if not subjects:
                errors["subjects"] = "Add at least one subject."
            elif len(subjects) > MAX_SUBJECTS:
                errors["subjects"] = f"A maximum of {MAX_SUBJECTS} subjects is allowed."
    raise_if(errors)
    return name, level, mode, subjects


def _ensure_unique_name(institution_id: int, level: str, name: str, ignore_id: int | None = None) -> None:
    clash = Department.query.filter(Department.institution_id == institution_id, Department.level == level,
                                    db.func.lower(Department.name) == name.lower())
    if ignore_id is not None:
        clash = clash.filter(Department.id != ignore_id)
    if clash.first():
        term = LEVELS[level]["term"].lower()
        raise ApiError("DUPLICATE_NAME", f"A {term} with this name already exists at this level.", 409,
                       {"name": "This name is already used."})


def _commit() -> None:
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        detail = str(getattr(exc, "orig", exc))
        if "uq_departments_institution_level_name" in detail:
            raise ApiError("DUPLICATE_NAME", "A field / department with this name already exists.", 409,
                           {"name": "This name is already used."})
        # anything else is a real database problem: show the true reason instead of hiding it
        raise ApiError("DB_CONSTRAINT", "Database rejected this save: " + detail[:300], 409)


def create_department(institution_id: int, data: dict) -> Department:
    name, level, mode, subjects = _clean(data)
    _ensure_unique_name(institution_id, level, name)
    dept = Department(institution_id=institution_id, name=name, level=level, mode=mode)
    dept.subjects = [Subject(name=s, position=i) for i, s in enumerate(subjects)]
    db.session.add(dept)
    _commit()
    return dept


def update_department(institution_id: int, department_id: int, data: dict) -> Department:
    dept = get_department(institution_id, department_id)
    name, level, mode, subjects = _clean(data)
    _ensure_unique_name(institution_id, level, name, ignore_id=dept.id)
    dept.name, dept.level, dept.mode = name, level, mode
    dept.updated_at = utcnow() 
    # keep existing Subject rows for names that stay (future questions will point at them), add/remove the rest
    existing = {s.name.lower(): s for s in dept.subjects}
    keep = []
    for i, s in enumerate(subjects):
        row = existing.pop(s.lower(), None) or Subject(name=s)
        row.name, row.position = s, i
        keep.append(row)
    dept.subjects = keep
    _commit()
    return dept


def delete_department(institution_id: int, department_id: int) -> None:
    dept = get_department(institution_id, department_id)
    db.session.delete(dept)
    db.session.commit()
