"""Phase 7 demo data: a live test with candidates in every monitor status, and a finished test for Reports.

    python seed_phase7.py <institution admin email>

Run it again whenever you want a fresh demo (it resets only the two Phase 7 demo tests' attempts and emails).

1. Runs the Phase 6 seed (field, 12 real Maths MCQs, the Phase 6 demo tests).
2. "Phase 7 Live Test"  fixed time, started 20 min ago, ends in 40 min, Maths x6. Candidates MON-0001 ... MON-0006:
       MON-0001 answering           MON-0002 locked (left fullscreen)    MON-0003 disconnected (quiet for 3 min)
       MON-0004 submitted           MON-0005 not started yet             MON-0006 answering
   Date of birth for all of them: 2007-01-01. Open Live Monitor to see them; MON-0002 can be unlocked there.
3. "Phase 7 Past Test"  ended yesterday, results by email. Eight candidates (PAST-0001 ... 0008) submitted with
   different scores, one was absent. Open Reports to see numbers, export the CSV and send the result emails.
Nothing here is needed in production."""
import sys
from datetime import date, timedelta

from app import create_app
from app.common.utils import utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import Candidate
from app.models.department import Department
from app.models.exam import ExamAttempt
from app.models.report import ResultEmail
from app.models.user import ROLE_INSTITUTION_ADMIN, User
from app.modules.exam import service
import seed_phase4
import seed_phase6

LIVE, PAST = "Phase 7 Live Test", "Phase 7 Past Test"
LIVE_PEOPLE = ["Ayesha Siddiqui", "Hamza Ali", "Fatima Noor", "Saad Qureshi", "Mariam Javed", "Omer Farooq"]
PAST_PEOPLE = ["Bilal Hussain", "Sana Fatima", "Ahmed Raza", "Hira Shahid", "Usman Ghani", "Iqra Aziz",
               "Taha Khan", "Noor Ul Ain", "Kashif Mehmood"]
PAST_RIGHT = [6, 5, 5, 4, 3, 3, 2, 1, None]      # correct answers out of 6; None = absent
DOB = date(2007, 1, 1)


def people(prefix: str, names: list[str], roll: str) -> list[tuple]:
    return [(n, n.lower().replace(" ", ".") + "@example.com", f"{roll}-{i:03d}", f"{prefix}{i:04d}", DOB)
            for i, n in enumerate(names, start=1)]


def answer(c: Candidate, right: int, now) -> None:
    for item in service.attempt_of(c).items:
        correct = item.question.correct_index
        wrong = (correct + 1) % len(item.option_order)
        pick = correct if item.position <= right else wrong
        service.save_answer(c, item.position, {"choice": list(item.option_order).index(pick)}, now)


def candidates_of(test: AptitudeTest) -> list[Candidate]:
    return Candidate.query.filter_by(test_id=test.id).order_by(Candidate.roll_number).all()


def clear(test: AptitudeTest) -> None:
    ResultEmail.query.filter_by(test_id=test.id).delete()
    for a in ExamAttempt.query.filter_by(test_id=test.id).all():
        db.session.delete(a)
    db.session.commit()


def live_demo(test: AptitudeTest, now) -> None:
    c = candidates_of(test)
    for i in (0, 1, 2, 3, 5):
        service.start(c[i], now - timedelta(minutes=15 - i))
    answer(c[0], 3, now - timedelta(minutes=1))
    answer(c[1], 2, now - timedelta(minutes=2))
    service.lock(c[1], "fullscreen_exit", now - timedelta(minutes=1))
    answer(c[2], 1, now - timedelta(minutes=4))
    answer(c[3], 5, now - timedelta(minutes=3))
    service.submit(c[3], now - timedelta(minutes=2))
    answer(c[5], 2, now)
    seen = {0: 0, 1: 1, 2: 3, 5: 0}
    for i, minutes in seen.items():
        service.attempt_of(c[i]).last_seen_at = now - timedelta(minutes=minutes)
    db.session.commit()


def past_demo(test: AptitudeTest) -> None:
    start = test.schedule.starts_at + timedelta(minutes=5)
    for i, (c, right) in enumerate(zip(candidates_of(test), PAST_RIGHT)):
        if right is None:
            continue
        t = start + timedelta(minutes=i)
        service.start(c, t)
        answer(c, right, t + timedelta(minutes=20))
        service.submit(c, t + timedelta(minutes=30))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    if seed_phase6.main() != 0:
        return 1
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=sys.argv[1].strip().lower(), role=ROLE_INSTITUTION_ADMIN).first()
        dept = Department.query.filter_by(institution_id=user.institution_id, level=seed_phase4.LEVEL,
                                          name=seed_phase4.DEPT_NAME).first()
        now = utcnow().replace(microsecond=0)
        live = seed_phase6.upsert_test(user, dept, LIVE, count=6, start=now - timedelta(minutes=20),
                                       end=now + timedelta(minutes=40), release="immediate")
        day = now - timedelta(days=1)
        past = seed_phase6.upsert_test(user, dept, PAST, count=6, start=day - timedelta(hours=2),
                                       end=day - timedelta(hours=1), release="scheduled")
        seed_phase6.reset_roster(live, dept, people("MON", LIVE_PEOPLE, "P7L"))
        seed_phase6.reset_roster(past, dept, people("PAST", PAST_PEOPLE, "P7P"))
        db.session.commit()
        clear(live)
        clear(past)
        live_demo(live, now)
        past_demo(past)
        print(f'"{LIVE}": 6 candidates in every monitor status (codes MON-0001 ... MON-0006, DOB 2007-01-01).')
        print(f'"{PAST}": ended yesterday, 8 submitted + 1 absent. Open Reports to export and send results.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
