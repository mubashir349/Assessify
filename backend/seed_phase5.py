"""Phase 5 demo data: a published test to put a roster on, plus a sample roster CSV.

    python seed_phase5.py <institution admin email>

1. Runs the Phase 4 seed if needed (field "Pre-Engineering" with approved Maths / Physics MCQs).
2. Publishes (once) "Phase 5 Demo Test": Pre-Engineering, Mathematics x4 per candidate, fixed time tomorrow
   2:00-4:00 pm Pakistan time (09:00-11:00 UTC).
3. Writes demo_roster.csv next to this file: 4 good candidates (one with its own access code) and 2 rows with
   mistakes, so the import shows both results. Import it on the Roster page.
Nothing here is needed in production."""
import os
import sys
from datetime import datetime, time, timedelta

from app import create_app
from app.common.utils import utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest, Composition, Schedule
from app.models.department import Department
from app.models.user import ROLE_INSTITUTION_ADMIN, User
import seed_phase4

TEST_NAME = "Phase 5 Demo Test"
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_roster.csv")
CSV_TEXT = """name,email,roll number,access code,date of birth,field
Ahmed Raza,ahmed.raza@example.com,PE-2026-001,,2008-03-14,Pre-Engineering
Sana Fatima,sana.fatima@example.com,PE-2026-002,DEMO-2026,02/07/2007,pre-engineering
Bilal Hussain,bilal.h@example.com,PE-2026-003,,19/11/2007,Pre-Engineering
Mehak Iqbal,mehak.iqbal@example.com,PE-2026-004,,2008-01-27,Pre-Engineering
Hassan Ali,hassan.ali@example.com,PE-2026-005,,2008-05-05,Pre-Eng
Areeba Khan,areeba.khan@example.com,PE-2026-001,,2007/13/40,Pre-Engineering
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    if seed_phase4.main() != 0:
        return 1
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=sys.argv[1].strip().lower(), role=ROLE_INSTITUTION_ADMIN).first()
        dept = Department.query.filter_by(institution_id=user.institution_id, level=seed_phase4.LEVEL,
                                          name=seed_phase4.DEPT_NAME).first()
        test = AptitudeTest.query.filter_by(institution_id=user.institution_id, name=TEST_NAME).first()
        if test is None:
            day = (utcnow() + timedelta(days=1)).date()
            test = AptitudeTest(institution_id=user.institution_id, created_by_id=user.id, name=TEST_NAME,
                                level=seed_phase4.LEVEL, status="published", published_at=utcnow())
            test.rows = [Composition(department_id=dept.id, subject_name="Mathematics", question_type="mcq",
                                     difficulty="any", question_count=4, position=0)]
            test.schedule = Schedule(timing_mode="fixed", starts_at=datetime.combine(day, time(9)),
                                     ends_at=datetime.combine(day, time(11)), duration_minutes=120,
                                     result_release="immediate")
            db.session.add(test)
            db.session.commit()
            print(f'Published "{TEST_NAME}" (fixed time, {day} 09:00-11:00 UTC = 2:00-4:00 pm Pakistan time).')
        else:
            print(f'"{TEST_NAME}" already exists - kept as it is.')
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(CSV_TEXT)
    print(f"Wrote {CSV_PATH}: import it on the Roster page (4 rows import, 2 are reported with the reason).")
    print("Then sign in at /aptitude/candidate-login.html with code DEMO-2026 and date of birth 2007-07-02.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
