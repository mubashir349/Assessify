"""Phase 10: the institution directory behind the signup search box, plus email codes (OTP).

directory_institutions  one row per university / college / school network (NED University, City College ...)
directory_campuses      its campuses (NED City Campus Karachi, NED Thar Campus Mithi ...). Signup picks a campus.
email_otps              6-digit codes sent to an admin's work email before signup. Only a hash is stored.
institution_proofs      the authorisation letter / certificate uploaded when an institution has no official email.
"""
from sqlalchemy.dialects import mssql

from app.common.utils import utcnow
from app.extensions import db

# VARBINARY(MAX) on SQL Server (plain LargeBinary would make the old IMAGE type)
BLOB = db.LargeBinary().with_variant(mssql.VARBINARY("max"), "mssql")

SOURCE_SEED = "seed"            # loaded from data/institution_directory.csv
SOURCE_APPROVED = "approved"    # added when the Super Admin approved a "not in the list" signup


class DirectoryInstitution(db.Model):
    __tablename__ = "directory_institutions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode(200), nullable=False, unique=True)
    short_name = db.Column(db.Unicode(40), nullable=True)            # NED, LUMS, FAST ... (also searched)
    type = db.Column(db.String(30), nullable=False)
    website = db.Column(db.String(255), nullable=True)
    # neduet.edu.pk, or several separated by commas (COMSATS: comsats.edu.pk,cuilahore.edu.pk). NULL = not known
    email_domain = db.Column(db.String(255), nullable=True)
    source = db.Column(db.String(20), nullable=False, default=SOURCE_SEED)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    campuses = db.relationship("DirectoryCampus", back_populates="institution", lazy="selectin",
                               cascade="all, delete-orphan", order_by="DirectoryCampus.id")


class DirectoryCampus(db.Model):
    __tablename__ = "directory_campuses"
    __table_args__ = (db.UniqueConstraint("directory_institution_id", "campus_name", "city", name="uq_campus_name_city"),)

    id = db.Column(db.Integer, primary_key=True)
    directory_institution_id = db.Column(db.Integer, db.ForeignKey("directory_institutions.id"), nullable=False, index=True)
    campus_name = db.Column(db.Unicode(120), nullable=False)          # "Main Campus", "Thar Campus", "Clifton Campus"
    city = db.Column(db.Unicode(120), nullable=False)
    address = db.Column(db.Unicode(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    institution = db.relationship("DirectoryInstitution", back_populates="campuses")

    def label(self) -> str:
        return f"{self.institution.name} · {self.campus_name}, {self.city}"


class EmailOtp(db.Model):
    __tablename__ = "email_otps"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)              # HMAC-SHA256 of the code, never the code
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)       # wrong codes typed
    verified_at = db.Column(db.DateTime, nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)                   # set when a signup used this verification


class InstitutionProof(db.Model):
    __tablename__ = "institution_proofs"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, unique=True)
    filename = db.Column(db.Unicode(200), nullable=False)
    content_type = db.Column(db.String(60), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    data = db.deferred(db.Column(BLOB, nullable=False))     # in the database (works on any host); loaded only on download
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
