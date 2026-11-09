"""Phase 8 load test data: one live test with N candidates (default 300).

    python loadtest/seed_loadtest.py <institution admin email> [N]

Runs the Phase 6 seed first (field + 12 real Maths questions). Creates / resets "Load Test": fixed time, started 5
minutes ago, ends in 2 hours, 10 Maths questions per candidate. Candidates LOAD-0001 ... (date of birth 2007-01-01).
Run it again before every load test: it deletes the earlier attempts of this test only. Not for production data.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.common.utils import utcnow  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.exam import ExamAttempt  # noqa: E402
from app.models.user import ROLE_INSTITUTION_ADMIN, User  # noqa: E402
import seed_phase4  # noqa: E402
import seed_phase6  # noqa: E402

NAME = "Load Test"
DOB = date(2007, 1, 1)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 1
    n = int(sys.argv[2]) if len(sys.argv) == 3 else 300
    sys.argv = sys.argv[:2]
    if seed_phase6.main() != 0:
        return 1
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=sys.argv[1].strip().lower(), role=ROLE_INSTITUTION_ADMIN).first()
        dept = Department.query.filter_by(institution_id=user.institution_id, level=seed_phase4.LEVEL,
                                          name=seed_phase4.DEPT_NAME).first()
        now = utcnow().replace(microsecond=0)
        test = seed_phase6.upsert_test(user, dept, NAME, count=10, start=now - timedelta(minutes=5),
                                       end=now + timedelta(hours=2), release="immediate")
        db.session.commit()
        for a in ExamAttempt.query.filter_by(test_id=test.id).all():
            db.session.delete(a)
        have = {c.access_code for c in Candidate.query.filter_by(test_id=test.id).all()}
        for i in range(1, n + 1):
            code = f"LOAD{i:04d}"
            if code not in have:
                db.session.add(Candidate(institution_id=test.institution_id, test_id=test.id, department_id=dept.id,
                                         full_name=f"Load Candidate {i}", email=f"load{i}@example.com",
                                         roll_number=f"LT-{i:04d}", date_of_birth=DOB, access_code=code,
                                         code_generated=False))
        db.session.commit()
        print(f'"{NAME}" (test id {test.id}): {n} candidates LOAD-0001 ... LOAD-{n:04d}, date of birth 2007-01-01.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
