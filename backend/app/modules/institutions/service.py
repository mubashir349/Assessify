from sqlalchemy.exc import IntegrityError

from app.common.errors import ApiError
from app.common.validation import EMAIL_RE, PHONE_RE, raise_if, text
from app.extensions import db
from app.models.institution import INSTITUTION_TYPES, Institution
from app.models.user import ROLE_INSTITUTION_ADMIN, User


def register_institution(data: dict) -> Institution:
    errors: dict = {}
    name = text(data, "institution_name", "Institution name", errors, min_len=2, max_len=200)
    itype = text(data, "institution_type", "Institution type", errors, max_len=30)
    city = text(data, "city", "City / location", errors, max_len=120)
    website = text(data, "website", "Website", errors, required=False, max_len=255)
    full_name = text(data, "admin_name", "Full name", errors, min_len=2, max_len=150)
    email = text(data, "admin_email", "Work email", errors, max_len=255).lower()
    phone = text(data, "admin_phone", "Phone", errors, max_len=30)
    designation = text(data, "admin_designation", "Designation", errors, required=False, max_len=120)
    password = data.get("password") if isinstance(data.get("password"), str) else ""

    if itype and itype not in INSTITUTION_TYPES:
        errors["institution_type"] = "Choose one of: " + ", ".join(INSTITUTION_TYPES) + "."
    if email and not EMAIL_RE.match(email):
        errors["admin_email"] = "Enter a valid email address."
    if phone and not PHONE_RE.match(phone):
        errors["admin_phone"] = "Enter a valid phone number."
    if website and not website.lower().startswith(("http://", "https://")):
        errors["website"] = "Website must start with http:// or https://"
    if len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    elif len(password) > 128:
        errors["password"] = "Password is too long."
    raise_if(errors)

    if User.query.filter_by(email=email).first():
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409,
                       {"admin_email": "This email is already registered."})

    inst = Institution(name=name, type=itype, city=city, website=website or None, status="pending")
    admin = User(full_name=full_name, email=email, phone=phone, designation=designation or None,
                 role=ROLE_INSTITUTION_ADMIN, institution=inst)
    admin.set_password(password)
    db.session.add_all([inst, admin])
    try:
        db.session.commit()
    except IntegrityError:  # two people submitting the same email at the same moment
        db.session.rollback()
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409,
                       {"admin_email": "This email is already registered."})
    return inst
