"""Phase 5 table: one candidate on the roster of one published test.

A candidate has no account and no password. They sign in with the one-time access code printed on their test slip
plus their date of birth. The code is unique across the whole platform, so the login needs nothing else.

The roster belongs to a test (not to the institution in general) because the test decides which fields /
departments exist and which paper a candidate gets (Phase 6 builds it from the candidate's department).
Only PUBLISHED tests take a roster: a published test is locked, so a candidate's field can never disappear from it.

The access code is kept readable (not hashed) on purpose: the admin has to print or email it, and it only works
together with the date of birth, for one test, until that test ends.
"""
from sqlalchemy import UniqueConstraint

from app.common.utils import iso, utcnow
from app.extensions import db

# Codes look like 8K4Q-2P1X. No 0/O, 1/I/L, so a code copied from paper is not misread.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_GROUP, CODE_GROUPS = 4, 2
CODE_MIN_LEN, CODE_MAX_LEN = 6, 20          # codes the institution supplies itself in the CSV

# CSV import ----------------------------------------------------------------------------------------
# Column -> accepted header spellings (compared lower-case, without spaces, dots, dashes or underscores)
CSV_COLUMNS = {
    "full_name": ("name", "fullname", "candidatename", "studentname"),
    "email": ("email", "emailaddress", "mail"),
    "roll_number": ("rollnumber", "rollno", "roll", "rollnum"),
    "access_code": ("accesscode", "code", "accesscodeoptional"),
    "date_of_birth": ("dateofbirth", "dob", "birthdate"),
    "department": ("field", "department", "fielddepartment", "fieldordepartment"),
}
CSV_REQUIRED = ("full_name", "email", "roll_number", "date_of_birth", "department")
CSV_TEMPLATE_HEADER = ["name", "email", "roll number", "access code", "date of birth", "field"]
MAX_IMPORT_ROWS = 5000
MAX_CSV_BYTES = 2 * 1024 * 1024              # 2 MB is about 20,000 rows; far above MAX_IMPORT_ROWS
DOB_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y")


class Candidate(db.Model):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("test_id", "roll_number", name="uq_candidates_test_roll"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    full_name = db.Column(db.Unicode(150), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    roll_number = db.Column(db.Unicode(50), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    access_code = db.Column(db.String(20), nullable=False, unique=True)   # stored upper-case
    code_generated = db.Column(db.Boolean, nullable=False, default=True)  # False = supplied in the CSV
    last_login_at = db.Column(db.DateTime, nullable=True)
    login_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    test = db.relationship("AptitudeTest", lazy="joined")
    department = db.relationship("Department", lazy="joined")
    institution = db.relationship("Institution", lazy="joined")

    def to_dict(self) -> dict:
        """Admin view (roster page). The page masks the code and date of birth until clicked."""
        return {
            "id": self.id,
            "test_id": self.test_id,
            "full_name": self.full_name,
            "email": self.email,
            "roll_number": self.roll_number,
            "date_of_birth": self.date_of_birth.isoformat(),
            "access_code": self.access_code,
            "code_generated": self.code_generated,
            "department": {"id": self.department.id, "name": self.department.name},
            "last_login_at": iso(self.last_login_at),
            "login_count": self.login_count,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def session_dict(self) -> dict:
        """What the signed-in candidate sees about themselves. Never the access code or date of birth."""
        t = self.test
        return {
            "id": self.id,
            "full_name": self.full_name,
            "roll_number": self.roll_number,
            "department": {"id": self.department.id, "name": self.department.name},
            "institution": {"id": self.institution.id, "name": self.institution.name},
            "test": {"id": t.id, "name": t.name, "level": t.level,
                     "schedule": t.schedule.to_dict() if t.schedule else None,
                     "subjects": list(dict.fromkeys(r.subject_name for r in t.rows if r.department_id == self.department_id)),
                     "question_count": sum(r.question_count for r in t.rows if r.department_id == self.department_id)},
        }
