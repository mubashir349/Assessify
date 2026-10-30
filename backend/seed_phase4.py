"""Phase 4 demo data: approved questions so the pool check has something to count.

    python seed_phase4.py <institution admin email>

Adds (once) an Undergraduate field "Pre-Engineering" with Mathematics, Physics, Chemistry, English to that admin's
institution, then puts 15 approved Mathematics MCQs and only 4 approved Physics MCQs into the bank.
Demo: Maths x10 per candidate needs 15 -> sufficient · Physics x5 needs 8 -> short by 4 -> publish is blocked.
The questions are placeholders marked [demo]; real ones come from Generate -> Draft Review (Phase 3)."""
import sys

from app import create_app
from app.extensions import db
from app.models.department import Department, Subject
from app.models.question import GenerationAttempt, Question
from app.models.user import ROLE_INSTITUTION_ADMIN, User

DEPT_NAME, LEVEL = "Pre-Engineering", "Undergraduate"
SUBJECTS = ["Mathematics", "Physics", "Chemistry", "English"]
PLAN = {"Mathematics": 15, "Physics": 4}


def add_approved(user: User, dept: Department, subject: str, n: int) -> None:
    common = {"institution_id": dept.institution_id, "department_id": dept.id, "department_name": dept.name,
              "level": dept.level, "subject_name": subject, "question_type": "mcq", "difficulty": "medium"}
    attempt = GenerationAttempt(created_by_id=user.id, requested_count=n, source_kind="description",
                                source_filename="seed_phase4.py", source_sha256="0" * 64,
                                source_text="Phase 4 demo seed", status="completed", generated_count=n,
                                provider="seed", **common)
    db.session.add(attempt)
    db.session.flush()
    for i in range(n):
        db.session.add(Question(attempt_id=attempt.id, position=i, status="approved", text=f"[demo] {subject} question {i + 1}",
                                options=["Option A", "Option B", "Option C", "Option D"], correct_index=0,
                                reviewed_by_id=user.id, **common))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=sys.argv[1].strip().lower(), role=ROLE_INSTITUTION_ADMIN).first()
        if user is None:
            print("No institution admin with that email. Sign up and get approved first (Phase 1).")
            return 1
        dept = Department.query.filter_by(institution_id=user.institution_id, level=LEVEL, name=DEPT_NAME).first()
        if dept is None:
            dept = Department(institution_id=user.institution_id, name=DEPT_NAME, level=LEVEL, mode="field")
            dept.subjects = [Subject(name=s, position=i) for i, s in enumerate(SUBJECTS)]
            db.session.add(dept)
            db.session.flush()
        if GenerationAttempt.query.filter_by(department_id=dept.id, provider="seed").first():
            print(f"Demo questions already added to {DEPT_NAME} - nothing to do.")
            return 0
        for subject, n in PLAN.items():
            add_approved(user, dept, subject, n)
        db.session.commit()
        print(f"{DEPT_NAME}: added " + ", ".join(f"{n} approved {s} MCQs" for s, n in PLAN.items()) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
