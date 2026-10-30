"""Phase 6 demo data: tests that are running RIGHT NOW, so the done-when demo works at any time of day.

    python seed_phase6.py <institution admin email>

Run it again whenever you want a fresh demo: it moves the demo tests' times to "now" again and deletes the demo
tests' attempts (only those three tests - nothing else is touched).

1. Runs the Phase 5 seed (Pre-Engineering field, demo questions, "Phase 5 Demo Test" tomorrow 2-4 pm PKT).
2. Adds (once) 12 approved, real Mathematics MCQs (easy) so the paper and the score make sense.
3. Creates / resets:
   - "Phase 6 Live Test"   fixed time, started 15 min ago, ends 45 min from now, Maths x6 (easy) per candidate,
                           score shown immediately.      Codes LIVE-0001 / LIVE-0002, date of birth 2007-05-01 / 2007-08-15
   - "Phase 6 Short Test"  fixed time, ends 3 minutes after this script runs, Maths x4, result emailed later.
                           Codes SHRT-0001 / SHRT-0002, date of birth 2007-09-09 / 2007-10-10
                           (shows auto-submit + answers refused after the end)
   - "Phase 5 Demo Test"   (tomorrow) gets candidate EARL-Y001, date of birth 2007-03-03 (shows: can't start early)
Nothing here is needed in production."""
import sys
from datetime import date, datetime, time, timedelta

from app import create_app
from app.common.utils import utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest, Composition, Schedule
from app.models.candidate import Candidate
from app.models.department import Department
from app.models.exam import ExamAttempt
from app.models.question import GenerationAttempt, Question
from app.models.user import ROLE_INSTITUTION_ADMIN, User
import seed_phase4
import seed_phase5

MATHS = [   # (question, options, correct index)
    ("What is 15% of 200?", ["20", "30", "35", "15"], 1),
    ("If 3x + 7 = 25, what is x?", ["5", "6", "7", "8"], 1),
    ("What is the derivative of x² ?", ["x", "2x", "x²", "2"], 1),
    ("The sum of the first 10 natural numbers is:", ["45", "50", "55", "60"], 2),
    ("Simplify (a² − b²) / (a − b).", ["a − b", "a + b", "a² + b", "ab"], 1),
    ("What is √144?", ["11", "12", "14", "13"], 1),
    ("A triangle's angles add up to:", ["90°", "180°", "270°", "360°"], 1),
    ("What is 2⁵?", ["10", "16", "32", "25"], 2),
    ("Solve: 12 ÷ (2 + 4) × 3", ["2", "6", "18", "0.67"], 1),
    ("The slope of y = 4x − 3 is:", ["−3", "3", "4", "1/4"], 2),
    ("log₁₀ 1000 = ?", ["2", "3", "10", "100"], 1),
    ("Area of a circle with radius 7 (π ≈ 22/7):", ["44", "154", "49", "144"], 1),
]
LIVE, SHORT = "Phase 6 Live Test", "Phase 6 Short Test"
CANDIDATES = {
    LIVE: [("Ali Khan", "ali.khan@example.com", "P6-001", "LIVE0001", date(2007, 5, 1)),
           ("Zara Ahmed", "zara.ahmed@example.com", "P6-002", "LIVE0002", date(2007, 8, 15))],
    SHORT: [("Usman Tariq", "usman.t@example.com", "P6-101", "SHRT0001", date(2007, 9, 9)),
            ("Hira Shah", "hira.shah@example.com", "P6-102", "SHRT0002", date(2007, 10, 10))],
    seed_phase5.TEST_NAME: [("Early Bird", "early.bird@example.com", "P5-EARLY", "EARLY001", date(2007, 3, 3))],
}


def add_real_maths(user: User, dept: Department) -> None:
    if GenerationAttempt.query.filter_by(department_id=dept.id, provider="seed6").first():
        return
    common = {"institution_id": dept.institution_id, "department_id": dept.id, "department_name": dept.name,
              "level": dept.level, "subject_name": "Mathematics", "question_type": "mcq", "difficulty": "easy"}
    att = GenerationAttempt(created_by_id=user.id, requested_count=len(MATHS), source_kind="description",
                            source_filename="seed_phase6.py", source_sha256="0" * 64, source_text="Phase 6 demo seed",
                            status="completed", generated_count=len(MATHS), provider="seed6", **common)
    db.session.add(att)
    db.session.flush()
    for i, (text, options, correct) in enumerate(MATHS):
        db.session.add(Question(attempt_id=att.id, position=i, status="approved", text=text, options=options,
                                correct_index=correct, reviewed_by_id=user.id, **common))
    print(f"Added {len(MATHS)} approved Mathematics MCQs (easy).")


def upsert_test(user, dept, name, *, count, start, end, release) -> AptitudeTest:
    test = AptitudeTest.query.filter_by(institution_id=user.institution_id, name=name).first()
    if test is None:
        test = AptitudeTest(institution_id=user.institution_id, created_by_id=user.id, name=name,
                            level=seed_phase4.LEVEL, status="published", published_at=utcnow())
        test.rows = [Composition(department_id=dept.id, subject_name="Mathematics", question_type="mcq",
                                 difficulty="easy", question_count=count, position=0)]
        test.schedule = Schedule(timing_mode="fixed", starts_at=start, ends_at=end, duration_minutes=1,
                                 result_release=release)
        db.session.add(test)
    sc = test.schedule
    sc.starts_at, sc.ends_at = start, end
    sc.duration_minutes = max(1, int((end - start).total_seconds() // 60))
    sc.release_on = (end + timedelta(days=1)).date() if release == "scheduled" else None
    db.session.flush()
    return test


def reset_roster(test: AptitudeTest, dept: Department, people) -> None:
    for full_name, email, roll, code, dob in people:
        c = Candidate.query.filter_by(access_code=code).first()
        if c is None:
            c = Candidate(institution_id=test.institution_id, test_id=test.id, department_id=dept.id, full_name=full_name,
                          email=email, roll_number=roll, date_of_birth=dob, access_code=code, code_generated=False)
            db.session.add(c)
            db.session.flush()
        for a in ExamAttempt.query.filter_by(candidate_id=c.id).all():
            db.session.delete(a)                       # a fresh demo every run


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    if seed_phase5.main() != 0:
        return 1
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=sys.argv[1].strip().lower(), role=ROLE_INSTITUTION_ADMIN).first()
        dept = Department.query.filter_by(institution_id=user.institution_id, level=seed_phase4.LEVEL,
                                          name=seed_phase4.DEPT_NAME).first()
        add_real_maths(user, dept)
        now = utcnow().replace(microsecond=0)
        live = upsert_test(user, dept, LIVE, count=6, start=now - timedelta(minutes=15),
                           end=now + timedelta(minutes=45), release="immediate")
        short = upsert_test(user, dept, SHORT, count=4, start=now - timedelta(minutes=1),
                            end=now + timedelta(minutes=3), release="scheduled")
        early = AptitudeTest.query.filter_by(institution_id=user.institution_id, name=seed_phase5.TEST_NAME).first()
        if early.schedule.starts_at <= now:        # seeded on an earlier day: move it to tomorrow 2-4 pm PKT again
            day = (now + timedelta(days=1)).date()
            early.schedule.starts_at = datetime.combine(day, time(9))
            early.schedule.ends_at = datetime.combine(day, time(11))
        for test in (live, short, early):
            reset_roster(test, dept, CANDIDATES[test.name])
        db.session.commit()

        def pk(d):   # Pakistan time, for the printout
            return (d + timedelta(hours=5)).strftime("%H:%M")

        print(f'"{LIVE}": fixed, {pk(live.schedule.starts_at)}-{pk(live.schedule.ends_at)} Pakistan time '
              f"(started 15 min ago). Codes LIVE-0001 (DOB 2007-05-01), LIVE-0002 (DOB 2007-08-15).")
        print(f'"{SHORT}": ends at {pk(short.schedule.ends_at)} Pakistan time (3 minutes). Codes SHRT-0001 (DOB 2007-09-09), '
              "SHRT-0002 (DOB 2007-10-10).")
        print(f'"{seed_phase5.TEST_NAME}" (tomorrow): code EARL-Y001 (DOB 2007-03-03) -> start is refused.')
        print("Sign in at http://127.0.0.1:5000/aptitude/candidate-login.html - run this script again for a fresh demo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
