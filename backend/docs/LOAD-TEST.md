# Load test (Phase 8)

**Setup:** SQL Server 2022 (Docker) and the app in production mode (`FLASK_ENV=production`, CSRF on) on one 4-core
Linux machine. [Locust](https://locust.io) simulates 300 candidates and 1 admin
([loadtest/locustfile.py](../loadtest/locustfile.py)).

Each candidate signs in, opens the time gate, starts (gets a random 10-question paper), answers every question,
re-reads the paper every so often like the real page does, submits and reads the result. The admin watches the
Live Monitor, which refreshes every 5 seconds. All 300 candidates join within 10 seconds (30 a second).

## Results

| Run | Server | Think time per answer | Requests | Failures | Answer save, median / 95% | Start test, median |
|---|---|---|---|---|---|---|
| 1. before the fixes | waitress, 1 process | 2-6 s (stress) | 3,024 in 4 min | 0 | 24 s / 26 s | 15 s |
| 2. after the fixes | waitress, 1 process | 2-6 s (stress) | 4,809 | 0 | 2.4 s / 8.9 s | 8.2 s |
| 3. production | gunicorn, 4 processes x 8 threads | 2-6 s (stress) | 4,862 | **0** | **54 ms / 870 ms** | 570 ms |
| 4. real exam pace | waitress, 1 process | 20-40 s | 4,837 in 7 min | **0** | **36 ms** / 6.6 s | 7 s |

All 300 candidates finished in runs 2 and 3 (300 submitted, every result readable). Run 4 stopped after 7 minutes,
while 22 candidates were still answering at the slow pace; nothing failed.

## What was slow, and what changed

Profiling showed one answer save ran **25 database queries**, and the candidate's whole paper, including every
question's text, was loaded again on each request.

- The candidate is loaded once, together with the test, schedule, field and attempt, in 2 queries (`candidate_query`).
  The answer save now runs **4 queries**.
- Question texts (long `NVARCHAR(MAX)` columns) are only read when a page needs the paper (`load_question_texts`).
- After saving, objects are not reloaded from the database (`commit_keep`).
- The "last seen" time for the Live Monitor is written at most every 15 seconds per candidate, not on every request.
- gunicorn keeps connections open for 30 s (`--keep-alive 30`), which stops rare connection-reset errors under load.

## How many candidates?

- **gunicorn with 2 to 4 processes** (Azure, Docker, any Linux server): 300 candidates at stress pace with a median of
  about 70 ms. This is the setup to use for real exams.
- **waitress, one process** (`python serve.py` on Windows): answers save quickly at a real exam pace, but Python runs
  one request at a time per process. When all 300 sign in and start in the same minute, they wait 4 to 7 s. Let
  candidates sign in during the 10 minutes before the start, or use gunicorn for groups over about 150.

## Run it yourself

```bash
pip install locust                                    # not in requirements.txt: only needed for this test
python loadtest/seed_loadtest.py admin@ned.edu.pk 300 # "Load Test": live now, 300 candidates LOAD0001...
# start the server in production mode (python serve.py, or gunicorn on Linux), then:
locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless -u 301 -r 30 -t 5m --csv loadtest/result
THINK_MIN=20 THINK_MAX=40 locust ...                  # real exam pace
```
Run the seed again before every run: it deletes the earlier attempts of the Load Test (only that test).
Never point the load test at a database with real exam data.
