"""Phase 10: institution directory - the search box on the signup page and the "add to directory" step on approval."""
from sqlalchemy import func, or_

from app.common import email_rules
from app.extensions import db
from app.models.directory import SOURCE_APPROVED, DirectoryCampus, DirectoryInstitution
from app.models.institution import Institution

ACTIVE_STATUSES = ("pending", "approved", "suspended")    # a rejected signup frees the campus again
MAX_RESULTS = 25


def _like(word: str) -> str:
    """User text inside LIKE: %, _ and [ (SQL Server) are matched literally."""
    for ch in ("\\", "%", "_", "["):
        word = word.replace(ch, "\\" + ch)
    return f"%{word}%"


def taken_campus_ids(campus_ids) -> set[int]:
    if not campus_ids:
        return set()
    rows = (db.session.query(Institution.directory_campus_id)
            .filter(Institution.directory_campus_id.in_(list(campus_ids)), Institution.status.in_(ACTIVE_STATUSES)))
    return {r[0] for r in rows}


def campus_dict(c: DirectoryCampus, taken: bool) -> dict:
    inst = c.institution
    return {
        "campus_id": c.id,
        "institution_id": inst.id,
        "institution_name": inst.name,
        "short_name": inst.short_name,
        "campus_name": c.campus_name,
        "city": c.city,
        "address": c.address,
        "type": inst.type,
        "website": inst.website,
        "email_domain": inst.email_domain,
        "label": c.label(),
        "registered": taken,
    }


def search(q: str | None) -> list[dict]:
    words = [w for w in (q or "").strip().split() if w][:5]
    if not words or len("".join(words)) < 2:
        return []
    query = DirectoryCampus.query.join(DirectoryInstitution)
    for w in words:
        pat = _like(w[:60])
        query = query.filter(or_(DirectoryInstitution.name.ilike(pat, escape="\\"),
                                 DirectoryInstitution.short_name.ilike(pat, escape="\\"),
                                 DirectoryCampus.campus_name.ilike(pat, escape="\\"),
                                 DirectoryCampus.city.ilike(pat, escape="\\")))
    rows = query.order_by(DirectoryInstitution.name, DirectoryCampus.campus_name).limit(MAX_RESULTS).all()
    taken = taken_campus_ids(c.id for c in rows)
    return [campus_dict(c, c.id in taken) for c in rows]


def find_institution_by_name(name: str) -> DirectoryInstitution | None:
    return DirectoryInstitution.query.filter(func.lower(DirectoryInstitution.name) == name.strip().lower()).first()


def add_from_approved(inst: Institution) -> None:
    """Super Admin approved a signup that was typed by hand: put it in the directory so the next person finds it.
    Called inside the approve transaction (the caller commits)."""
    if inst.directory_campus_id:
        return
    parent = db.session.get(DirectoryInstitution, inst.directory_institution_id) if inst.directory_institution_id else None
    parent = parent or find_institution_by_name(inst.name)
    if parent is None:
        admin = inst.primary_admin()
        domain = email_rules.domain_of(admin.email) if admin else ""
        parent = DirectoryInstitution(name=inst.name, type=inst.type, website=inst.website, source=SOURCE_APPROVED,
                                      email_domain=None if (inst.no_official_email or email_rules.is_free(domain)) else domain)
        db.session.add(parent)
        db.session.flush()
    campus_name = inst.campus_name or "Main Campus"
    campus = next((c for c in parent.campuses
                   if c.campus_name.lower() == campus_name.lower() and c.city.lower() == inst.city.lower()), None)
    if campus is None:
        campus = DirectoryCampus(institution=parent, campus_name=campus_name, city=inst.city)
        db.session.add(campus)
        db.session.flush()
    inst.directory_institution_id = parent.id
    inst.directory_campus_id = campus.id
    if not inst.campus_name:
        inst.campus_name = campus_name
