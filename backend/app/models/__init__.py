"""Import every model here so Flask-Migrate can see it."""
from app.models.institution import Institution  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.department import Department, Subject  # noqa: F401
from app.models.question import GenerationAttempt, Question  # noqa: F401
