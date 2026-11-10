"""Phase 10 demo data: sample institution signups for the Super Admin page, plus a proof PDF to upload yourself.

    python seed_directory.py      # first: the institution list
    python seed_phase10.py

Adds (skipped when the admin email already exists):
  1. FAST-NUCES Lahore Campus     APPROVED   fast.admin@nu.edu.pk          from the list, domain matches
  2. NED Thar Campus, Mithi       pending    thar.admin@neduet.edu.pk      from the list, domain matches
  3. Beaconhouse Lahore Branch    pending    bss.lahore.demo@gmail.com     no official email + proof PDF (red tag)
  4. Bright Future College        pending    principal@brightfuture.edu.pk not in the list (typed by hand)
Every demo admin's password is Demo#Pass123. Also writes demo_proof.pdf next to this file for your own signup test.
"""
import sys
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models.directory import DirectoryCampus, DirectoryInstitution, InstitutionProof
from app.models.institution import Institution
from app.models.user import ROLE_INSTITUTION_ADMIN, User

PASSWORD = "Demo#Pass123"   # NOSONAR - demo accounts on a local database only
PROOF_PATH = Path(__file__).parent / "demo_proof.pdf"


def _demo_pdf() -> bytes:
    """A one-page PDF ("Authorisation letter - DEMO ONLY") with a correct cross-reference table, so any viewer opens it."""
    text = (b"BT /F1 20 Tf 60 760 Td (Authorisation letter - DEMO ONLY) Tj 0 -34 Td /F1 12 Tf "
            b"(Beaconhouse School System, Lahore Branch) Tj 0 -20 Td "
            b"(Sana Malik is authorised to register our school on Assessify.) Tj ET")
    objects = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
               b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
               b"<</Length %d>>stream\n" % len(text) + text + b"\nendstream",
               b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


PROOF_PDF = _demo_pdf()

DEMOS = [
    {"short": "FAST-NUCES", "campus": "Lahore Campus", "email": "fast.admin@nu.edu.pk", "admin": "Dr. Kashif Zafar",
     "status": "approved", "domain_ok": True},
    {"short": "NED", "campus": "Thar Campus", "email": "thar.admin@neduet.edu.pk", "admin": "Engr. Ayesha Khan",
     "status": "pending", "domain_ok": True},
    {"short": "Beaconhouse", "campus": "Lahore Branch", "email": "bss.lahore.demo@gmail.com", "admin": "Sana Malik",
     "status": "pending", "no_official": True},
    {"typed": {"name": "Bright Future College", "type": "College", "city": "Hyderabad", "campus_name": "Latifabad Campus",
               "website": "https://www.brightfuture.edu.pk"},
     "email": "principal@brightfuture.edu.pk", "admin": "Imran Ali", "status": "pending", "domain_ok": True},
]


def _campus(short: str, campus: str):
    return (DirectoryCampus.query.join(DirectoryInstitution)
            .filter(DirectoryInstitution.short_name == short, DirectoryCampus.campus_name == campus).first())


def _institution(demo: dict):
    if "typed" in demo:
        return Institution(status=demo["status"], **demo["typed"])
    c = _campus(demo["short"], demo["campus"])
    if c is None:
        return None
    p = c.institution
    return Institution(name=p.name, type=p.type, city=c.city, website=p.website, campus_name=c.campus_name,
                       directory_campus_id=c.id, directory_institution_id=p.id, from_directory=True,
                       status=demo["status"])


def add(demo: dict) -> str:
    if User.query.filter_by(email=demo["email"]).first():
        return f"  {demo['email']}: already there, skipped"
    inst = _institution(demo)
    if inst is None:
        return f"  {demo['email']}: campus not in the directory - run python seed_directory.py first"
    inst.email_domain_verified = bool(demo.get("domain_ok"))
    inst.no_official_email = bool(demo.get("no_official"))
    if inst.no_official_email:
        inst.proof = InstitutionProof(filename="authorisation-letter.pdf", content_type="application/pdf",
                                      size_bytes=len(PROOF_PDF), data=PROOF_PDF)
    admin = User(full_name=demo["admin"], email=demo["email"], role=ROLE_INSTITUTION_ADMIN, institution=inst)
    admin.set_password(PASSWORD)
    db.session.add_all([inst, admin])
    db.session.commit()
    return f"  {demo['email']}: {inst.display_name} ({inst.status})"


def main() -> int:
    app = create_app()
    with app.app_context():
        if DirectoryInstitution.query.count() == 0:
            print("The institution list is empty. Run  python seed_directory.py  first.")
            return 1
        print("Phase 10 demo signups (password for all: " + PASSWORD + "):")
        for demo in DEMOS:
            print(add(demo))
    PROOF_PATH.write_bytes(PROOF_PDF)
    print(f"Wrote {PROOF_PATH.name}: upload it when you test 'We don't have an official email'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
