"""Phase 5 table: one candidate on the roster of one published test.

A candidate has no account and no password. They sign in with the one-time access code printed on their test slip
plus a second factor: their date of birth when the institution gave one, otherwise a 6-digit PIN that the system
made and printed on the slip (Phase 9). Exactly one of date_of_birth / pin is set. The code is unique across the
whole platform, so the login needs nothing else.

Phase 9: universities send incomplete lists, so email, roll number and date of birth are optional. A candidate
needs a name plus at least one way to tell them apart (email, phone or roll number). The roll number, when given,
is unique inside one test (a filtered unique index, because SQL Server allows only one NULL in a plain unique one).

The roster belongs to a test (not to the institution in general) because the test decides which fields /
departments exist and which paper a candidate gets (Phase 6 builds it from the candidate's department).
Only PUBLISHED tests take a roster: a published test is locked, so a candidate's field can never disappear from it.

The access code is kept readable (not hashed) on purpose: the admin has to print or email it, and it only works
together with the date of birth, for one test, until that test ends.
"""
from sqlalchemy import CheckConstraint, Index

from app.common.utils import iso, utcnow
from app.extensions import db

# Codes look like 8K4Q-2P1X. No 0/O, 1/I/L, so a code copied from paper is not misread.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_GROUP, CODE_GROUPS = 4, 2
CODE_MIN_LEN, CODE_MAX_LEN = 6, 20          # codes the institution supplies itself in the CSV
PIN_LENGTH = 6                              # Phase 9: second factor for candidates without a date of birth

# CSV import ---------------------------------------------------------------------------------------
# Column -> accepted header spellings (compared lower-case, without spaces, dots, dashes or underscores)
CSV_COLUMNS = {
    "full_name": ("name", "fullname", "candidatename", "studentname", "nameofstudent", "nameofcandidate",
                  "applicantname", "student", "candidate"),
    "email": ("email", "emailaddress", "mail", "gmail", "emailid", "mailid"),
    "phone": ("phone", "phoneno", "phonenumber", "mobile", "mobileno", "mobilenumber", "cell", "cellno",
              "cellnumber", "contact", "contactno", "contactnumber", "whatsapp", "whatsappno"),
    "roll_number": ("rollnumber", "rollno", "roll", "rollnum", "regno", "regnumber", "registrationno",
                    "registrationnumber", "seatno", "seatnumber", "studentid", "candidateid", "enrollmentno"),
    "access_code": ("accesscode", "code", "accesscodeoptional"),
    "date_of_birth": ("dateofbirth", "dob", "birthdate", "birthday", "dateofbirthddmmyyyy", "dobddmmyyyy"),
    "department": ("field", "department", "fielddepartment", "fieldordepartment", "program", "programme",
                   "group", "discipline"),
}
# Phase 9: only the name column is required; at least one of these must be in the file (and filled in each row)
CSV_IDENTIFIERS = ("email", "phone", "roll_number")
CSV_TEMPLATE_HEADER = ["name", "email", "phone", "roll number", "date of birth", "field"]
MAX_IMPORT_ROWS = 5000
MAX_CSV_BYTES = 2 * 1024 * 1024              # 2 MB is about 20,000 rows; far above MAX_IMPORT_ROWS
DOB_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y",
               "%d %B %Y", "%d/%b/%Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y")


class Candidate(db.Model):
    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint("status IN ('Active','Inactive','Pending')", name="status_valid"),
        Index("uq_candidates_test_roll", "test_id", "roll_number", unique=True,
              mssql_where=db.text("is_deleted = 0 AND roll_number IS NOT NULL"),
              sqlite_where=db.text("is_deleted = 0 AND roll_number IS NOT NULL")),
        Index("ix_candidates_test_status_deleted", "test_id", "status", "is_deleted"),
        # Only issued codes must be unique: Inactive / Pending students have none (NULL).
        Index("uq_candidates_code_issued", "access_code", unique=True,
              mssql_where=db.text("access_code IS NOT NULL"),
              sqlite_where=db.text("access_code IS NOT NULL")),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    full_name = db.Column(db.Unicode(150), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(20), nullable=True)                       # Phase 9, digits only (+ allowed first)
    roll_number = db.Column(db.Unicode(50), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    pin = db.Column(db.String(PIN_LENGTH), nullable=True)                 # Phase 9, only when there is no DOB
    # Existing roster entries and newly imported candidates keep their former default eligibility.
    status = db.Column(db.String(12), nullable=False, default="Active", server_default="Active", index=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false(), index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    # stored upper-case. NULL = no code issued: only Active students get an access code (and PIN).
    access_code = db.Column(db.String(20), nullable=True)
    code_generated = db.Column(db.Boolean, nullable=False, default=True)  # False = supplied in the CSV
    last_login_at = db.Column(db.DateTime, nullable=True)
    login_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    test = db.relationship("AptitudeTest", lazy="joined")
    department = db.relationship("Department", lazy="joined")
    institution = db.relationship("Institution", lazy="joined")
    # Phase 6: the candidate's attempt (at most one), shown on the roster
    attempt = db.relationship("ExamAttempt", uselist=False, viewonly=True, lazy="selectin")
    # Phase 11: the admit-card email log row (deleted together with the candidate)
    admit_card = db.relationship("AdmitCardEmail", uselist=False, lazy="selectin", cascade="all, delete-orphan",
                                 passive_deletes=True)

    @property
    def login_with(self) -> str:
        """Which second factor this candidate signs in with: "dob" or "pin"."""
        return "dob" if self.date_of_birth else "pin"

    def to_dict(self) -> dict:
        """Admin view (roster page). The page masks the code, PIN and date of birth until clicked."""
        return {
            "id": self.id,
            "test_id": self.test_id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "roll_number": self.roll_number,
            "status": self.status,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "login_with": self.login_with,
            "pin": self.pin,
            "access_code": self.access_code,
            "code_generated": self.code_generated,
            "department": {"id": self.department.id, "name": self.department.name},
            "last_login_at": iso(self.last_login_at),
            "login_count": self.login_count,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def session_dict(self) -> dict:
        """What the signed-in candidate sees about themselves. Never the access code, PIN or date of birth."""
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
