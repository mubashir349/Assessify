"""Phase 8 "done when" check: a full mock exam, end to end, over HTTP against any running copy of Assessify.

    python loadtest/mock_exam.py https://assessify-xyz.azurewebsites.net admin@ned.edu.pk "<admin password>"
    python loadtest/mock_exam.py http://127.0.0.1:8000 admin@ned.edu.pk "<admin password>" --candidates 5 --lead 90

Needs: an approved institution admin whose "Pre-Engineering" (Undergraduate) field has approved Mathematics
questions (seed_phase4.py / seed_phase6.py add them). Only talks to the public API, the same as the pages do.

Steps: admin signs in -> creates "Mock Exam <time>" (fixed time, starts in --lead seconds, results immediate) ->
publishes it -> adds the candidates -> each candidate signs in and waits at the time gate -> the test opens ->
everyone starts and answers, candidate 1 leaves the window once (locked) and the admin unlocks them -> everyone
submits and reads the result -> the admin checks the live monitor, the report, the CSV export and sends the results.
Prints one line per step and ends with PASS (exit code 0) or FAIL (exit code 1).
"""
import argparse
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

DEPT_NAME, LEVEL, SUBJECT = "Pre-Engineering", "Undergraduate", "Mathematics"
DOB = "2006-05-05"


class Failed(Exception):
    pass


class Client:
    """A browser stand-in: keeps cookies and sends the CSRF header like api.js does."""

    def __init__(self, base: str, timeout: float):
        self.base, self.timeout, self.s = base.rstrip("/"), timeout, requests.Session()
        self.s.headers["User-Agent"] = "assessify-mock-exam/1.0"

    def call(self, method: str, path: str, expect=200, **kw):
        headers = kw.pop("headers", {})
        csrf = self.s.cookies.get("csrf_access_token")
        if method != "GET" and csrf:
            headers["X-CSRF-TOKEN"] = csrf
        r = self.s.request(method, self.base + "/api/v1" + path, headers=headers, timeout=self.timeout, **kw)
        if r.status_code != expect:
            raise Failed(f"{method} {path} answered {r.status_code} (wanted {expect}): {r.text[:300]}")
        if "json" not in r.headers.get("Content-Type", ""):
            return r
        body = r.json()
        return body.get("data", body.get("error"))


def step(text: str):
    print(f"  ok  {text}", flush=True)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(args) -> None:
    admin = Client(args.url, args.timeout)
    health = admin.call("GET", "/health/db")
    step(f"server and database answer ({health.get('status')})")

    admin.call("POST", "/auth/login", json={"email": args.email, "password": args.password})
    step(f"admin {args.email} signed in")

    depts = admin.call("GET", "/departments")["items"]
    dept = next((d for d in depts if d["name"] == DEPT_NAME and d["level"] == LEVEL), None)
    if not dept:
        raise Failed(f'No "{DEPT_NAME}" ({LEVEL}) field. Run seed_phase6.py {args.email} on the server first.')

    now = datetime.now(timezone.utc).replace(microsecond=0)
    starts, ends = now + timedelta(seconds=args.lead), now + timedelta(seconds=args.lead, minutes=args.minutes)
    name = f"Mock Exam {now:%Y-%m-%d %H:%M:%S}"
    rows = [{"subject": SUBJECT, "question_type": "mcq", "difficulty": "any", "count": args.questions}]
    body = {"name": name, "level": LEVEL, "compositions": [{"department_id": dept["id"], "rows": rows}],
            "schedule": {"timing_mode": "fixed", "starts_at": iso(starts), "ends_at": iso(ends),
                         "result_release": "immediate"}}
    test_id = admin.call("POST", "/tests", expect=201, json=body)["test"]["id"]
    admin.call("POST", f"/tests/{test_id}/publish")
    step(f'"{name}" created and published (id {test_id}), opens {iso(starts)}, {args.questions} questions')

    stamp = now.strftime("%H%M%S")
    codes = []
    for i in range(1, args.candidates + 1):
        code = f"M{stamp}{i:02d}"
        admin.call("POST", "/roster", expect=201, json={
            "test_id": test_id, "department_id": dept["id"], "full_name": f"Mock Candidate {i}",
            "email": f"mock{i}@example.com", "roll_number": f"MOCK-{stamp}-{i}", "date_of_birth": DOB,
            "access_code": code})
        codes.append(code)
    step(f"{len(codes)} candidates added to the roster")

    people = []
    for code in codes:
        c = Client(args.url, args.timeout)
        c.call("POST", "/candidate/login", json={"access_code": code, "date_of_birth": DOB})
        gate = c.call("GET", "/exam")["gate"]
        people.append(c)
    step(f"every candidate signed in; the gate says: {gate['state']} (opens in {gate['seconds_until_start']} s)")

    wait = (starts - datetime.now(timezone.utc)).total_seconds() + 2
    if wait > 0:
        print(f"  ..  waiting {int(wait)} s for the test to open", flush=True)
        time.sleep(wait)

    papers = [c.call("POST", "/exam/start")["questions"] for c in people]
    step(f"every candidate started and got {len(papers[0])} questions")

    first = people[0]
    first.call("POST", "/exam/lock", json={"reason": "tab_hidden"})
    first.call("PUT", f"/exam/answers/{papers[0][0]['number']}", expect=423, json={"choice": 0})
    attempt_id = first.call("GET", "/exam")["gate"]["attempt"]["id"]
    admin.call("POST", f"/attempts/{attempt_id}/unlock")
    step("candidate 1 left the window: locked, could not answer, then the admin unlocked them")

    for c, paper in zip(people, papers, strict=True):
        for q in paper:
            c.call("PUT", f"/exam/answers/{q['number']}", json={"choice": random.randrange(len(q["options"]))})
    step(f"{len(people) * len(papers[0])} answers saved")

    live = admin.call("GET", f"/monitor?test_id={test_id}")
    step(f"live monitor during the exam: {live['counts']}")

    scores = []
    for c in people:
        c.call("POST", "/exam/submit")
        res = c.call("GET", "/exam/result")
        scores.append(res.get("result", res))
    step("everyone submitted and can read their result")

    live = admin.call("GET", f"/monitor?test_id={test_id}")
    if live["counts"].get("completed") != len(people):
        raise Failed(f"monitor shows {live['counts']} instead of {len(people)} completed")
    step(f"monitor after the exam: {live['counts']['completed']} completed")

    report = admin.call("GET", f"/reports/tests/{test_id}")
    step(f"report ready: {report.get('summary', {})}")
    csv = admin.call("GET", f"/reports/tests/{test_id}/export.csv")
    lines = csv.text.strip().splitlines()
    if len(lines) != len(people) + 1:
        raise Failed(f"CSV has {len(lines)} lines, wanted {len(people) + 1}")
    step(f"CSV export has a header and {len(lines) - 1} candidates")

    r = admin.s.post(admin.base + f"/api/v1/reports/tests/{test_id}/send-results", json={}, timeout=args.timeout,
                     headers={"X-CSRF-TOKEN": admin.s.cookies.get("csrf_access_token") or ""})
    if r.status_code == 200:
        step(f"result emails: {r.json()['data']}")
    elif r.status_code == 503:
        step("result emails skipped: mail is not set up on this server (MAIL_* settings)")
    else:
        raise Failed(f"send-results answered {r.status_code}: {r.text[:300]}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url", help="where Assessify runs, e.g. https://assessify-xyz.azurewebsites.net")
    p.add_argument("email", help="institution admin email")
    p.add_argument("password", help="institution admin password")
    p.add_argument("--candidates", type=int, default=5)
    p.add_argument("--questions", type=int, default=5)
    p.add_argument("--lead", type=int, default=75, help="seconds until the test opens (at least 60)")
    p.add_argument("--minutes", type=int, default=20, help="length of the exam window")
    p.add_argument("--timeout", type=float, default=30)
    args = p.parse_args()
    args.lead = max(args.lead, 60)
    print(f"Mock exam against {args.url}", flush=True)
    started = time.time()
    try:
        run(args)
    except (Failed, requests.RequestException, KeyError) as exc:
        print(f"FAIL  {exc}")
        return 1
    print(f"PASS  full mock exam in {int(time.time() - started)} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
