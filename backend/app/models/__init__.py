"""Import every model here so Flask-Migrate can see it."""
from app.models.institution import Institution  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.department import Department, Subject  # noqa: F401
from app.models.question import GenerationAttempt, Question  # noqa: F401
from app.models.aptitude_test import AptitudeTest, Composition, Schedule  # noqa: F401
from app.models.candidate import Candidate  # noqa: F401
from app.models.exam import ExamAttempt, LockEvent, PaperItem  # noqa: F401
from app.models.report import ResultEmail  # noqa: F401
from app.models.directory import DirectoryCampus, DirectoryInstitution, EmailOtp, InstitutionProof  # noqa: F401
from app.models.admit_card import AdmitCardEmail  # noqa: F401
from app.models.payment import Payment  # noqa: F401
