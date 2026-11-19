"""Institution signup (Phase 1, reworked in Phase 10).

The institution comes from the directory (a campus picked in the search box), or is typed by hand when it is not
listed. The admin's work email must be verified with an emailed code first (see app/modules/email_otp).

Three ways in:
  directory_campus_id        picked a campus from the list: name, type, city and website come from the directory
  directory_institution_id   institution is listed but the campus is not: admin types campus name + city
  neither                    institution not listed: admin types everything
"""
from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.common import email_rules
from app.common.errors import ApiError
from app.common.utils import utcnow
from app.common.validation import EMAIL_RE, raise_if, text
from app.extensions import db
from app.models.directory import DirectoryCampus, DirectoryInstitution, InstitutionProof
from app.models.institution import INSTITUTION_TYPES, Institution
from app.models.user import ROLE_INSTITUTION_ADMIN, User
from app.modules.directory.service import find_institution_by_name, holds_place, taken_campus_ids
from app.modules.email_otp import service as otp

PROOF_TYPES = {"application/pdf": b"%PDF", "image/png": b"\x89PNG", "image/jpeg": b"\xff\xd8\xff"}
_TRUE = ("1", "true", "yes", "on")


def _flag(value) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in _TRUE)


def _int_or_none(value, key: str, errors: dict):
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors[key] = "Choose your institution from the list again."
        return None


def _taken(message: str, field: str = "institution_name"):
    return ApiError("INSTITUTION_TAKEN", message, 409, {field: message})


def _from_campus(campus_id: int, errors: dict) -> dict:
    """Picked a campus from the list: everything comes from the directory."""
    campus = db.session.get(DirectoryCampus, campus_id)
    if campus is None:
        errors["institution_name"] = "That campus is no longer in the list. Search again."
        return {}
    p = campus.institution
    return {"name": p.name, "type": p.type, "city": campus.city, "website": p.website,
            "campus_name": campus.campus_name, "campus": campus, "parent": p}


def _same_campus(parent: DirectoryInstitution, campus_name: str, city: str):
    if not campus_name:
        return None
    return next((c for c in parent.campuses
                 if c.campus_name.lower() == campus_name.lower() and c.city.lower() == city.lower()), None)


def _from_parent(data: dict, parent_id: int, errors: dict) -> dict:
    """Institution is listed, campus is not: the admin types the campus name and city."""
    p = db.session.get(DirectoryInstitution, parent_id)
    if p is None:
        errors["institution_name"] = "That institution is no longer in the list. Search again."
        return {}
    campus_name = text(data, "campus_name", "Campus name", errors, min_len=2, max_len=120)
    city = text(data, "city", "City / location", errors, max_len=120)
    same = _same_campus(p, campus_name, city)
    if same is not None:                      # typed a campus that is in the list after all
        return _from_campus(same.id, errors)
    return {"name": p.name, "type": p.type, "city": city, "website": p.website,
            "campus_name": campus_name, "campus": None, "parent": p}


def _typed(data: dict, errors: dict) -> dict:
    """Not in the list: everything is typed by hand."""
    name = text(data, "institution_name", "Institution name", errors, min_len=2, max_len=200)
    itype = text(data, "institution_type", "Institution type", errors, max_len=30)
    city = text(data, "city", "City / location", errors, max_len=120)
    website = text(data, "website", "Website", errors, required=False, max_len=255)
    campus_name = text(data, "campus_name", "Campus name", errors, required=False, max_len=120)
    if itype and itype not in INSTITUTION_TYPES:
        errors["institution_type"] = "Choose one of: " + ", ".join(INSTITUTION_TYPES) + "."
    if website and not website.lower().startswith(("http://", "https://")):
        errors["website"] = "Website must start with http:// or https://"
    parent = find_institution_by_name(name) if name else None       # typed a listed name by hand: link it
    return {"name": parent.name if parent else name, "type": itype, "city": city, "website": website or None,
            "campus_name": campus_name or None, "campus": None, "parent": parent}


def _resolve_institution(data: dict, errors: dict) -> dict:
    """-> {name, type, city, website, campus_name, campus, parent} from the directory or from the typed fields."""
    campus_id = _int_or_none(data.get("directory_campus_id"), "institution_name", errors)
    parent_id = _int_or_none(data.get("directory_institution_id"), "institution_name", errors)
    if campus_id is not None:
        return _from_campus(campus_id, errors)
    if parent_id is not None:
        return _from_parent(data, parent_id, errors)
    return _typed(data, errors)


def _check_not_registered(inst: dict) -> None:
    campus = inst["campus"]
    if campus is not None:
        if taken_campus_ids([campus.id]):
            raise _taken(f"{campus.label()} is already registered. Ask its admin to add you, or contact support.")
        return
    q = Institution.query.filter(func.lower(Institution.name) == inst["name"].lower(),
                                 func.lower(Institution.city) == inst["city"].lower(),
                                 holds_place())
    for existing in q:
        if (existing.campus_name or "").lower() == (inst["campus_name"] or "").lower():
            raise _taken(f"{existing.display_name} ({existing.city}) is already registered.")


def _check_email(email: str, no_official: bool, parent, website: str | None, errors: dict) -> bool:
    """Work-email rules. Returns True when the email's domain is confirmed to belong to the institution."""
    domain = email_rules.domain_of(email)
    expected = parent.email_domain if parent else None
    shown = " or ".join("@" + d for d in email_rules.domain_list(expected))
    if no_official:
        if expected:
            errors["admin_email"] = (f"{parent.name} has official email addresses ({shown}). "
                                     "Use yours instead of ticking 'no official email'.")
        return False
    if email_rules.is_free(domain):
        errors["admin_email"] = (f"@{domain} is a personal email. Use your institution's work email, or tick "
                                 "'We don't have an official email' and upload a proof document.")
        return False
    if expected and not email_rules.matches(domain, expected):
        errors["admin_email"] = f"Use your {shown} email address (the official domain of {parent.name})."
        return False
    if expected:
        return True
    host = email_rules.host_of(website)
    return bool(host) and (email_rules.matches(domain, host) or email_rules.matches(host, domain))


def _read_proof(file, required: bool, errors: dict):
    if file is None or not getattr(file, "filename", ""):
        if required:
            errors["proof"] = "Upload an authorisation letter or registration certificate (PDF, JPG or PNG)."
        return None
    max_bytes = current_app.config["PROOF_MAX_MB"] * 1024 * 1024
    data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        errors["proof"] = f"The proof file must be at most {current_app.config['PROOF_MAX_MB']} MB."
        return None
    kind = next((ct for ct, magic in PROOF_TYPES.items() if data.startswith(magic)), None)
    if kind is None:
        errors["proof"] = "The proof must be a PDF, JPG or PNG file."
        return None
    name = file.filename.replace("\\", "/").rsplit("/", 1)[-1][:200] or "proof"
    return InstitutionProof(filename=name, content_type=kind, size_bytes=len(data), data=data)


def _check_password(password: str, errors: dict) -> None:
    if len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    elif len(password) > 128:
        errors["password"] = "Password is too long."


def register_institution(data: dict, proof_file=None) -> Institution:
    errors: dict = {}
    inst = _resolve_institution(data, errors)
    full_name = text(data, "admin_name", "Full name", errors, min_len=2, max_len=150)
    email = text(data, "admin_email", "Work email", errors, max_len=255).lower()
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    no_official = _flag(data.get("no_official_email"))

    if email and not EMAIL_RE.match(email):
        errors["admin_email"] = "Enter a valid email address."
    _check_password(password, errors)
    domain_ok = False
    if inst and email and "admin_email" not in errors:
        domain_ok = _check_email(email, no_official, inst["parent"], inst["website"], errors)
    proof = _read_proof(proof_file, no_official, errors) if no_official else None
    raise_if(errors)

    if User.query.filter_by(email=email).first():
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409,
                       {"admin_email": "This email is already registered."})
    _check_not_registered(inst)
    otp_row = otp.check_token(data.get("email_token"), email)

    campus, parent = inst["campus"], inst["parent"]
    institution = Institution(
        name=inst["name"], type=inst["type"], city=inst["city"], website=inst["website"],
        # Phase 11: with payments on, the fee comes first; the Super Admin only sees it once it is paid
        status="awaiting_payment" if current_app.config.get("PAYMENTS_ENABLED", True) else "pending",
        campus_name=inst["campus_name"], directory_campus_id=campus.id if campus else None,
        directory_institution_id=parent.id if parent else None, from_directory=campus is not None,
        email_domain_verified=domain_ok, no_official_email=no_official)
    admin = User(full_name=full_name, email=email, role=ROLE_INSTITUTION_ADMIN, institution=institution)
    admin.set_password(password)
    if proof is not None:
        institution.proof = proof
    otp_row.used_at = utcnow()
    db.session.add_all([institution, admin])
    try:
        db.session.commit()
    except IntegrityError:  # two people submitting the same email at the same moment
        db.session.rollback()
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409,
                       {"admin_email": "This email is already registered."})
    return institution
