"""Phase 8 load test: a few hundred candidates take the "Load Test" at the same time while an admin watches.

    pip install locust
    python loadtest/seed_loadtest.py <admin email> 300
    locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless -u 301 -r 20 -t 6m \
           --csv loadtest/result
    (set the ADMIN_EMAIL and ADMIN_PASSWORD environment variables = the institution admin who watches the Live Monitor)

Each candidate: sign in -> time gate -> start (random paper) -> answers every question with 2-6 s "thinking" ->
resyncs every 30 s like the real page -> submits -> reads the result. One admin polls the monitor every 5 s.
"""
import itertools
import os
import secrets
import threading

from locust import HttpUser, between, events, task

_next = itertools.count(1)
_lock = threading.Lock()


def next_code() -> str:
    with _lock:
        return f"LOAD{next(_next):04d}"


THINK_MIN = float(os.getenv("THINK_MIN", "2"))     # seconds a candidate "thinks" before the next answer
THINK_MAX = float(os.getenv("THINK_MAX", "6"))     # 2-6 s is a stress test; real candidates take 20-60 s


class Candidate(HttpUser):
    weight = 300
    wait_time = between(THINK_MIN, THINK_MAX)

    def on_start(self):
        self.code, self.questions, self.n, self.done = next_code(), [], 0, False
        r = self.client.post("/api/v1/candidate/login", json={"access_code": self.code, "date_of_birth": "2007-01-01"},
                             name="candidate/login")
        if r.status_code != 200:
            self.done = True
            return
        self.client.get("/api/v1/exam", name="exam/gate")
        r = self.client.post("/api/v1/exam/start", name="exam/start")
        if r.status_code == 200:
            self.questions = r.json()["data"]["questions"]
        else:
            self.done = True

    @task(10)
    def answer(self):
        if self.done:
            return
        if self.n >= len(self.questions):
            self.client.post("/api/v1/exam/submit", name="exam/submit")
            self.client.get("/api/v1/exam/result", name="exam/result")
            self.done = True
            return
        q = self.questions[self.n]
        self.client.put(f"/api/v1/exam/answers/{q['number']}", json={"choice": secrets.randbelow(len(q["options"]))},
                        name="exam/answer")
        self.n += 1

    @task(1)
    def resync(self):
        if not self.done:
            self.client.get("/api/v1/exam/paper", name="exam/paper (resync)")


class Admin(HttpUser):
    weight = 1
    fixed_count = 1
    wait_time = between(5, 5)

    def on_start(self):
        # no default password in the code: both values must come from the environment
        credentials = {"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}
        self.client.post("/api/v1/auth/login", json=credentials, name="admin/login")
        tests = self.client.get("/api/v1/monitor/tests", name="monitor/tests").json()["data"]["tests"]
        self.test_id = next((t["id"] for t in tests if t["name"] == "Load Test"), None)

    @task
    def watch(self):
        if self.test_id:
            self.client.get(f"/api/v1/monitor?test_id={self.test_id}", name="monitor (5 s poll)")


@events.test_stop.add_listener
def _summary(environment, **_):
    s = environment.stats.total
    print(f"\nTOTAL requests={s.num_requests} failures={s.num_failures} "
          f"median={s.median_response_time}ms p95={s.get_response_time_percentile(0.95)}ms")
