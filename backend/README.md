# Assessify Backend (Flask + SQL Server)

## Phase 0 checklist — every teammate does this on their own PC

### 1. Install once
- **Python 3.10+** (tick "Add python.exe to PATH" in the installer)
- **SQL Server Express** (or Developer) + **SSMS**
- **ODBC Driver 18 for SQL Server** (Microsoft download)

### 2. Create your own database (in SSMS)
Connect to your server, then run:
```sql
CREATE DATABASE AssessifyDB;
```

### 3. Set up the project (PowerShell, inside `backend/`)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
If PowerShell blocks the activate script, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4. Edit `.env`
- `DB_SERVER` — the server name shown in SSMS's connect box (e.g. `localhost\SQLEXPRESS` or `.\SQLEXPRESS`)
- Windows login: keep `DB_TRUSTED=yes`
- SQL login: set `DB_TRUSTED=no` and fill `DB_USER` / `DB_PASSWORD`

### 5. Check everything
```powershell
python check_setup.py
```
It prints exactly what is missing (driver, `.env`, database, connection).

### 6. Run the API
```powershell
python run.py
```
Open in a browser:
- http://127.0.0.1:5000/api/v1/health → `{"data": {"status": "ok", ...}}`
- http://127.0.0.1:5000/api/v1/health/db → shows your SQL Server version

**Phase 0 is done when all four of you see the second URL succeed.**

## Common problems
| Message | Fix |
|---|---|
| `Data source name not found` | ODBC Driver 18 not installed, or `DB_DRIVER` name differs. `check_setup.py` lists installed drivers. |
| `Login failed` | Wrong SQL login, or use `DB_TRUSTED=yes` |
| `Cannot open database "AssessifyDB"` | Create it in SSMS (step 2) |
| `Named Pipes / server not found` | Wrong `DB_SERVER`, or SQL Server service is stopped (open *SQL Server Configuration Manager*) |
| Certificate error | Already handled by `TrustServerCertificate=yes` for local dev |

## Phase 1 — accounts, login, institution approval

### One-time setup after pulling Phase 1
```powershell
pip install -r requirements.txt        # new: Flask-JWT-Extended
flask --app run db upgrade             # creates the tables in YOUR AssessifyDB
python seed.py                         # creates the Super Admin (asks for a password, min 10 chars)
python run.py
```
Check in SSMS: Databases → AssessifyDB → Tables → `institutions`, `users`, `alembic_version`.

Set a long random `SECRET_KEY` in `.env` (generate one: `python -c "import secrets; print(secrets.token_hex(32))"`).

### Run the tests (no SQL Server needed — they use an in-memory database)
```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

### Try it with the frontend
1. Open the `frontend` folder with VS Code **Live Server** (port 5500) and open `aptitude/institution-login.html` via `http://127.0.0.1:5500/...`
2. Use `127.0.0.1` for BOTH the site and the API (don't mix with `localhost`) — the login cookie only travels between the same host.
3. Register an institution -> sign in as the Super Admin (the email you seeded) -> approve it -> sign in as the institution.

### Changing tables later (the team rule)
Edit the model -> ONE person runs `flask --app run db migrate -m "what changed"` -> commit the new file in `migrations/versions/` -> everyone else runs `flask --app run db upgrade`. Never edit tables by hand in SSMS.

Full route list and error codes: `docs/API.md`

## Phase 3 — AI question generation, draft review, question bank

**Flow:** Institution Admin signs in → *Generate Questions* (upload 1–10 PDFs **or** describe the topic, choose
field/department, subject, type, difficulty, count) → server extracts the text → a **free** AI service writes draft
questions spread over all the material → drafts are saved →
*Draft Review* (edit / approve / reject / regenerate) → *Question Bank* shows **approved questions only**.

### One-time setup after pulling Phase 3 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt        # new: pypdf (PDF text) + requests (AI HTTP calls)
flask --app run db upgrade             # adds the tables generation_attempts + questions (nothing is deleted)
```
Then add the Phase 3 block from `.env.example` to your `.env` and set up ONE free AI option:

**Option A — Google Gemini API free tier (recommended)**
1. Open https://aistudio.google.com/app/apikey, sign in with a Google account, click *Create API key*. No card / billing needed.
2. In `.env`: `AI_PROVIDER=gemini` and `GEMINI_API_KEY=<your key>` (leave `AI_MODEL` empty → `gemini-3.5-flash-lite`).
3. Test it: `python check_ai.py` (uses 1 request of your free quota and prints a sample question).

Free-tier facts (checked on Google's official pricing page, Oct 2026): `gemini-3.5-flash-lite` is listed as
"Free of charge" on the free tier, and Pakistan is in the supported-regions list. Limits are per Google Cloud project
(not per key), are shown on your AI Studio "rate limits" page, and daily quotas reset at midnight Pacific time. Google
states free-tier prompts **may be used to improve Google's products** — do not upload confidential PDFs.

**Option B — Groq free plan:** key from https://console.groq.com/keys, then `AI_PROVIDER=groq`, `GROQ_API_KEY=...`
(default model `openai/gpt-oss-20b`). Groq's docs list about 30 requests/min and 8K tokens/min for it, so also set
`AI_MAX_SOURCE_CHARS=6000` and `AI_BATCH_SIZE=5` to stay under the per-minute token limit.

**Option C — Ollama (completely local, no key, no quota):** install from https://ollama.com, then
`ollama pull qwen2.5:7b` (4.7 GB download; roughly 8 GB+ RAM recommended — `qwen2.5:3b` is 1.9 GB for weaker PCs but
gives lower-quality questions). In `.env`: `AI_PROVIDER=ollama` (and `AI_MODEL=qwen2.5:3b` if you chose that).
Generation is slower on a CPU-only laptop; raise `AI_TIMEOUT_SECONDS` to 300 if needed.

**No AI configured?** (`AI_PROVIDER=none` or the key is missing) — the Generate page shows a clear warning and the API
returns `503 AI_NOT_CONFIGURED`. Draft Review and the Question Bank keep working. Nothing ever falls back to a paid service,
and no fake questions are produced.

### Upload size, several PDFs, and how much of a long PDF is used
- **200 MB in total** per generation (`MAX_UPLOAD_MB`), up to **10 PDFs** (`MAX_PDFS_PER_GENERATION`), up to **100
  questions** (`MAX_QUESTIONS_PER_ATTEMPT`), up to 300 pages read per PDF (`PDF_MAX_PAGES`). The server holds the uploads
  in memory while reading them, so 200 MB is kept as a safe ceiling for a normal laptop.
- Up to `SOURCE_MAX_CHARS` (300,000 ≈ 120 typed pages) of text is kept, shared fairly between the PDFs so one big book
  can't crowd out a short handout. Each PDF is labelled `=== Document N: name ===` in the stored text.
- That text is split into parts of `AI_MAX_SOURCE_CHARS` (12,000). One generation sends up to
  `AI_MAX_REQUESTS_PER_GENERATION` (10) parts **spread from the beginning to the end**, with the questions divided
  between them (100 questions = 10 parts × 10) — so questions cover the whole material, not just the first pages.
  Regenerating picks a random part.
- Time: roughly 25 questions a minute, so 100 questions take about 3–5 minutes (more with photo pages). If a free-tier
  limit is hit halfway, the questions made so far are kept (status *partial*) and "Regenerate rejected" tops it up later.
- Each request stays small, which keeps within free-tier per-minute limits.

### No PDF? Generate from a description
If no PDF is uploaded, the description becomes the scope and must have at least `DESCRIPTION_MIN_WORDS` (8) words —
otherwise the page (and API, `422 VALIDATION_ERROR` with `details.focus`) asks for more detail, e.g. *"Photosynthesis:
light reactions, Calvin cycle and factors affecting the rate, first-year biology"*. These questions come from the
AI's general knowledge, so Draft Review marks the attempt *"No PDF"* and asks you to check every answer.
With PDFs, the description is optional instructions; the page offers one-click suggestions ("Make the test based on
these PDFs", "Cover all chapters evenly", …) plus "Focus on: <chapter>" for chapter / section headings found in the PDFs.

### Using VS Code Live Server?
Live Server reloads the page whenever ANY file in the folder changes — including Python cache files written inside
`backend/` while the server runs, which used to reload the Generate page in the middle of generating. The project now
includes `.vscode/settings.json` telling Live Server to ignore `backend/**`. (Simplest option: skip Live Server and open
http://127.0.0.1:5000/aptitude/institution-login.html — `python run.py` serves the frontend too.) If a reload still
happens, the Generate page waits for the running generation and then opens it in Draft Review.

### What happens to the uploaded PDF
It is read in memory and **never saved to disk**. Only its name, page count, extracted-text length and the extracted
text (cut to `AI_MAX_SOURCE_CHARS`, used for "Regenerate") are stored. Checks run as soon as you pick the file
(`/questions/check-pdf`, no AI quota used) and again on generate: `.pdf` extension, real PDF signature,
size ≤ `MAX_UPLOAD_MB`, not password-protected, and either typed text or page pictures.

### Photos / scans of pages (e.g. phone pictures of a book or handwritten notes) — and mixed PDFs
Every page is checked on its own:
- **Typed page** (has a real text layer, at least ~80 letters) → its text is used. Pictures on it (diagrams, figures)
  are ignored, so normal textbooks never spend extra quota.
- **Photo page** (almost no typed text + a big picture) → with `AI_PROVIDER=gemini` the picture (shrunk to
  `OCR_IMAGE_MAX_SIDE` px) is sent to Gemini, which copies the text exactly. Neighbouring photo pages go together,
  up to `OCR_PAGES_PER_REQUEST` per request; at most `OCR_MAX_PAGES` (60) photo pages per generation.
- Typed text and Gemini's transcriptions are joined back **in the original page order**, and that becomes the source
  text — so generating, regenerating and review work exactly as for a typed PDF. Pictures are not stored; the attempt
  is marked 📷 in Draft Review.
- Pages after the AI text limit (`AI_MAX_SOURCE_CHARS`) is surely full are not read at all (saves quota).
- The upload box says exactly what will be used, e.g. "5 pages: 2 typed + 3 photo/scan".

Limits: costs more free quota and time (1–3 minutes); blurry, dark, tilted or messy handwriting can be misread —
check numbers, formulas and spellings before approving. Groq / Ollama text models cannot see pictures: photo pages are
then **skipped** (the upload box warns "3 pages of photos will be skipped"), and a PDF made only of photos is rejected
with a message to use Gemini. If almost nothing could be read, you get `PDF_NO_TEXT` asking for clearer photos.

After pulling these updates run `pip install -r requirements.txt` (adds Pillow) and `flask --app run db upgrade`
(adds `generation_attempts.source_ocr`, `source_kind`, `source_files`; existing rows get `0` / `'pdf'` / `1`).

### Question lifecycle
`draft` → `approved` (final, shown in the bank) · `draft` → `rejected` (optional reason) · `draft`/`rejected` →
*Regenerate* → old one becomes `replaced` (kept as history), a new `draft` takes its place. Approved questions are never
edited or overwritten by regeneration. AI questions are **not guaranteed correct** — the admin checks each answer before approving.

### Tests (no SQL Server, no internet, no AI quota — the AI is mocked in tests only)
```powershell
pip install -r requirements-dev.txt
python -m pytest -q                     # Phase 1 + 2 + 3
python -m pytest tests/test_phase3.py -v
```
Full Phase 3 API (every route, field and error code): `docs/API.md`

## Folder layout
```
backend/
  run.py                 start the server
  check_setup.py         setup diagnostics (now also says whether AI is configured)
  check_ai.py            Phase 3: one real test call to your free AI provider
  app/
    __init__.py          create_app(): registers every module
    config.py            reads .env
    extensions.py        db, migrate, cors
    common/              responses.py (JSON shape), errors.py (ApiError)
    models/              database tables (institution.py, user.py, department.py, question.py, aptitude_test.py, candidate.py, exam.py)
    ai/                  Phase 3: provider-independent AI layer (providers.py = gemini / groq / ollama presets)
    modules/
      health/            routes.py  <- pattern every future module follows
      auth/              login, logout, me
      institutions/      public signup
      super_admin/       list / approve / reject / suspend institutions
      departments/       Phase 2: fields / departments + subjects
      questions/         Phase 3: routes, service (lifecycle), pdf.py, generator.py (prompt + retries), validation.py
      aptitude_tests/    Phase 4: tests, the 1.5x pool check, schedules, publish
      roster/            Phase 5: candidate roster, CSV import, access codes
      candidate_auth/    Phase 5: candidate login (access code + date of birth); app/common/candidate.py = candidate_required
      exam/              Phase 6: time gate, random paper, answers, lock, auto-submit, scoring (+ admin unlock / end)
      monitor/           Phase 7: live monitor snapshot (statuses, counts, filters)
      reports/           Phase 7: reports + CSV export (service.py), result emails (emails.py), AI insights (ai_summary.py)
  migrations/            database versions (Alembic)
  seed.py                creates the Super Admin
  tests/                 pytest suite
  docs/API.md            the API contract
```

## Rules for the team
- `.env` is never committed. `.env.example` is.
- Responses always go through `ok()` / `fail()` / `raise ApiError(...)`.
- New module = new folder in `app/modules/` with `routes.py` (HTTP only) and `service.py` (rules), then one `register_blueprint` line in `app/__init__.py`.
- Tables are changed only through migrations (`flask db migrate`, `flask db upgrade`) — never by hand in SSMS.

## Phase 4 — creating tests

**Flow:** *Aptitude Tests → Create* → pick a level and fields/departments → build each paper (subject, type, difficulty,
questions per candidate) → the server counts approved questions and needs **1.5× per row** → set a flexible window or a
fixed start/end → *Save as draft* or *Publish*. Publishing is refused on the server (`409 POOL_TOO_SMALL`) while any row is
short, so the disabled button can't be bypassed.

### One-time setup after pulling Phase 4 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
flask --app run db upgrade                    # adds tests, test_compositions, test_schedules (nothing is deleted)
python seed_phase4.py <your institution admin email>   # demo: 15 approved Maths + 4 approved Physics MCQs
```

### Done-when demo (each of the four, on your own machine)
1. Sign in as the institution admin and open *Aptitude Tests*.
2. Select **Pre-Engineering**, keep Mathematics (MCQ, Any, 10 per candidate → needs 15, bank 15 ✓), set Physics to 5
   (needs 8, bank 4 ✗) and remove Chemistry and English.
3. Step 3: *Fixed time*, 2:00 pm – 4:00 pm. Step 4 shows **Publish is blocked**. *Save as draft*, then in Postman
   `POST /api/v1/tests/<id>/publish` → `409 POOL_TOO_SMALL`.
4. Go back, set Physics to 2 (needs 3) → *Publish* works.
5. In SSMS: `SELECT starts_at, ends_at, duration_minutes FROM test_schedules;` → `09:00`, `11:00` (UTC; Pakistan is
   UTC+5) and `120`.

Times are stored in UTC. The browser converts the admin's local date and time before sending, so the server needs no
timezone library.

## Phase 5 — candidate roster and candidate login

**Flow:** publish a test (Phase 4) → *Candidate Roster* → choose the test → drop the roster CSV → the server checks every
row and shows "N ready · M need fixing" (nothing saved yet) → *Import* saves the good rows and lists each bad row with
its row number and the reason → missing access codes are generated → *Export codes* gives a CSV for printing test slips.
A candidate opens *Candidate Login*, types the access code + date of birth from the slip → the start page shows their
name, field, subjects and the countdown. A wrong code or date is refused.

A roster belongs to one **published** test, because a published test is locked: the fields candidates are assigned to
can't change any more (Phase 6 builds each candidate's paper from their field).

### One-time setup after pulling Phase 5 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
flask --app run db upgrade                     # adds the candidates table (nothing is deleted)
python seed_phase5.py <your institution admin email>   # demo: a published test + demo_roster.csv
python run.py
```
No new packages. Optional `.env` lines are in `.env.example` (Phase 5 block: login lockout limits, session length).

### CSV format
`name, email, roll number, access code, date of birth, field` — *Download template CSV* on the Roster page gives a
ready file. Access code may be empty (one is generated). Dates as `2008-03-14` or `14/03/2008` (day first). In Excel:
*File → Save As → CSV UTF-8*. Full rules and every error: `docs/API.md` → "Candidate roster".

### Done-when demo (each of the four, on your own machine)
1. Sign in as the institution admin, open *Candidate Roster*, choose **Phase 5 Demo Test**.
2. Drop `backend/demo_roster.csv` → preview says **6 rows · 4 ready · 2 need fixing** (`"Pre-Eng"` with a
   "did you mean Pre-Engineering?" hint, and a bad date + duplicate roll number). Click *Import 4 candidates*.
3. Open http://127.0.0.1:5000/aptitude/candidate-login.html (a private window is not needed — the candidate cookie
   is separate from the admin one). Code **WRNG-CODE**, date 2007-07-02 → *"Access code or date of birth is incorrect"*.
4. Code **DEMO-2026** (or `demo2026`), date of birth **2007-07-02** → the start page says *Welcome, Sana Fatima ·
   PE-2026-002* with the countdown to tomorrow 2:00 pm.
5. Back on the Roster page, Sana's *Signed in* column shows the time. Postman: `POST /api/v1/candidate/login` with a
   wrong code → `401 INVALID_ACCESS_CODE`; 5 wrong dates for one code → `429 TOO_MANY_ATTEMPTS`.

### Tests
```powershell
python -m pytest -q                       # 155 tests: Phase 1-5
python -m pytest tests/test_phase5.py -v
```
The migration was generated and checked (upgrade → downgrade → upgrade) on SQLite only. Run `flask --app run db upgrade`
on your SQL Server and check SSMS shows the `candidates` table.

## Phase 6 — taking the test

**Flow:** the candidate signs in (Phase 5) → the start page asks the **server** whether the test is open (a wrong clock
on the candidate's PC changes nothing) → *Start test* builds their own random paper → the test page asks for fullscreen →
every click is saved on the server at once ("All answers saved" in the top bar) → leaving fullscreen or switching tab
**locks** the test until the admin presses *Unlock* on the Roster page → *Submit*, or the timer reaches 0 → the server
scores it → the result page shows the score (tests with "Show score immediately") or the email date (scheduled release).

What the server guarantees (the page can't bypass any of it): no start before the start time; a fixed-time test ends
for everyone at its end time (a late starter gets less time); a flexible test gives each candidate their own duration
but never past the window; answers after the end are refused (`409 TIME_UP`) and the test is submitted with what was
saved before; the correct answers are never sent to the candidate's browser. Full rules and errors: `docs/API.md` →
"Taking the test".

### One-time setup after pulling Phase 6 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
flask --app run db upgrade                     # adds exam_attempts, exam_paper_items, exam_lock_events (nothing is deleted)
python seed_phase6.py <your institution admin email>
python run.py
```
No new packages, no new `.env` lines. `seed_phase6.py` makes demo tests that are running **now**; run it again for a
fresh demo (it resets only its own demo tests and their attempts).

### Done-when demo (each of the four, on your own machine)
Open http://127.0.0.1:5000/aptitude/candidate-login.html. Use a second browser profile (or a private window) for the
second candidate, because one browser holds one candidate cookie.
1. **Can't start early:** code **EARL-Y001**, date of birth **2007-03-03** (Phase 5 Demo Test, tomorrow) → the start page
   counts down and *Start* stays disabled. Postman `POST /api/v1/exam/start` with that cookie → `403 TEST_NOT_STARTED`.
2. **Late starter ends at the fixed end:** code **LIVE-0001**, 2007-05-01 (Phase 6 Live Test, started 15 minutes ago,
   1 hour long) → the start page says ~45 min, and after *Start* the timer shows ~45:00, not 1:00:00.
3. **Different papers:** in the other window code **LIVE-0002**, 2007-08-15 → different questions and option order.
   Answer a few questions, press Esc → the test locks. On the admin's *Candidate Roster* (Phase 6 Live Test) the row
   says 🔒 Locked → *Unlock* → the candidate's page asks for fullscreen again within 10 seconds. Submit → score.
4. **Answers after the end are refused:** run `python seed_phase6.py <email>` again (the Short Test ends 3 minutes later).
   In Postman, before the end: `POST /api/v1/candidate/login {"access_code": "SHRT-0001", "date_of_birth": "2007-09-09"}`,
   `POST /api/v1/exam/start`, `PUT /api/v1/exam/answers/1 {"choice": 0}` → `200`. After the end time:
   `PUT /api/v1/exam/answers/2 {"choice": 0}` → **`409 TIME_UP`**, and the attempt is submitted with answer 1 only
   (a second late answer → `409 ALREADY_SUBMITTED`). In the browser, **SHRT-0002** (2007-10-10) shows the other path:
   keep the test page open and it submits itself at 00:00 → "Time is up — test submitted".
5. **No correct answers sent:** in DevTools → Network, open any `/exam/...` response: questions have `text`, `options`,
   `choice`, `flagged` — never `correct_index`, `explanation` or `difficulty`.

### Tests
```powershell
python -m pytest -q                       # 177 tests: Phase 1-6
python -m pytest tests/test_phase6.py -v
```
The migration was generated and checked (upgrade → downgrade → upgrade) on SQLite only. Run `flask --app run db upgrade`
on your SQL Server and check SSMS shows `exam_attempts`, `exam_paper_items` and `exam_lock_events`.

## Phase 7 — live monitor, reports, insights, result emails

**Live Monitor** (admin menu): pick a test → every candidate with their status (Not started, In progress,
Disconnected, Locked, Auto-submitted, Completed), answered count, time left and when the page was last seen. It
refreshes every 5 seconds. Click a status box to filter; *Unlock* frees a locked candidate, *End* ends one candidate's
test and scores it. **Reports**: search / filter tests by name, level and year → average, median, highest, lowest,
score bands, averages by field, subjects, the hardest questions, rule-based insights and *Ask AI for a summary* →
candidate list with rank, filters and *Export CSV* → *Send results* emails every submitted candidate their score
(email log in the same table). **Dashboard** now shows live tests, candidates, average score and approved questions.
**Question Bank** shows tips for your draft tests and an *Ask AI about the bank* button.

### One-time setup after pulling Phase 7 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
flask --app run db upgrade                     # adds result_emails + exam_attempts.last_seen_at (nothing is deleted)
python seed_phase7.py <your institution admin email>
python run.py
```
No new packages. New optional `.env` lines (see `.env.example`): `MAIL_BACKEND=console` (default: emails are only
printed in the server terminal) or `smtp` with `MAIL_SERVER`, `MAIL_PORT` (587 or 465, always encrypted), `MAIL_USERNAME`,
`MAIL_PASSWORD` (Gmail: an app password), `MAIL_FROM`; and `MONITOR_DISCONNECTED_SECONDS` (default 75).

### Done-when demo
1. Log in as the institution admin → **Live Monitor** → *Phase 7 Live Test*: 6 candidates, one in each status
   (Hamza Ali is 🔒 Locked, Fatima Noor is ⚠ Disconnected, Mariam Javed not started, Saad Qureshi completed).
2. Press **Unlock** on Hamza Ali → the toast says unlocked and the Locked count drops to 0. (Live too: sign in as
   **LIVE-0002 / 2007-08-15** in another window, press Esc to lock, watch the row turn Locked within 5 s, Unlock it.)
3. **Reports** → *Phase 7 Past Test* (8 submitted, 1 absent) → **Export CSV** downloads the ranked list →
   **Send results** → the email column shows *Logged (test mode)* for all 8 (with `MAIL_BACKEND=smtp` they are really sent).

### Tests
```powershell
python -m pytest -q                       # 200 tests: Phase 1-7
python -m pytest tests/test_phase7.py -v
```
The migration was checked (upgrade → downgrade → upgrade) on SQLite only. Run `flask --app run db upgrade` on your
SQL Server and check SSMS shows `result_emails` and the new `last_seen_at` column in `exam_attempts`.

## Phase 8 — security, load test, error handling, deployment

**Security.** Admin logins lock for 15 minutes after 5 wrong passwords (per email) or 30 failures from one address.
Every answer has security headers and a request id. A test visits every API route and checks it refuses visitors
without a login, candidates on admin routes, and another institution's admin. With `FLASK_ENV=production` the server
will not start with a weak `SECRET_KEY` (including the one in `.env.example`).
**Errors.** Database down → `503 DB_UNAVAILABLE`; anything unexpected → `500` with a request id to report, never a
stack trace. Unknown API paths answer JSON 404/405.
**Speed.** An answer save went from 25 database queries to 4; 300 candidates at once finish with no errors
([docs/LOAD-TEST.md](docs/LOAD-TEST.md)).
**Deployment.** Azure for Students, a Windows PC on the lab network, or Docker: [docs/DEPLOY.md](docs/DEPLOY.md).
The pages now call the API on their own address when Flask serves them (Live Server on port 5500 still uses port 5000).

### One-time setup after pulling Phase 8 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt               # nothing new on Windows (gunicorn is Linux only)
python run.py                                  # development, as before
```
No database changes. Optional new `.env` lines: see the Phase 8 block of `.env.example`.

### Production server on your PC
```powershell
# .env: FLASK_ENV=production, your own SECRET_KEY, JWT_COOKIE_CSRF=true, FRONTEND_URL=http://<PC IP>:8000
python serve.py                                # waitress on port 8000, serves the pages too
```

### Done-when demo: a full mock exam
```powershell
python seed_phase6.py <institution admin email>        # approved Maths questions in Pre-Engineering
python loadtest/mock_exam.py http://127.0.0.1:8000 <institution admin email> "<password>"
```
Works the same against the deployed address. It creates and publishes a test, adds 5 candidates who wait at the
gate, start, answer (one is locked and unlocked by the admin) and submit, then checks the monitor, report, CSV and
result emails, and prints `PASS`.

### Tests
```powershell
python -m pytest -q                       # 218 tests: Phase 1-8
python -m pytest tests/test_phase8.py -v
```
To run the tests on SQL Server instead of SQLite, set `TEST_DATABASE_URL` to an **empty test database** (the tests
delete everything in it), e.g.
`mssql+pyodbc://sa:<password>@localhost/AssessifyTest?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes`.
All Phase 1-8 tests also pass on SQL Server 2022.

## Phase 9 — lenient roster import (incomplete university lists)

Universities send incomplete lists, so the roster import no longer stops on missing data.
**Needed:** a name plus at least one of email / phone / roll number (and the field, when the test has more than one).
**Optional:** email, phone, roll number, date of birth. A candidate without a date of birth gets a random **6-digit PIN**
and signs in with *access code + PIN*. The login page has a **Date of birth | PIN** switch; the server accepts only
that candidate's factor and gives one error for everything, so it never tells which factor a code uses.
**Files:** CSV or **Excel (.xlsx)**. PDF is refused with advice (copy the table into Excel). Headings are matched
loosely ("Student Name", "Gmail", "Mobile", "Reg No", "D.O.B" ...); other columns are ignored.
**Rows:** errors (not imported) only when the result could be wrong: no name, no identifier, a blank roll number in a
file that has a roll column, duplicate roll number / email / code, unknown or missing field, a date that is not a date.
Warnings (imported): same name or phone as another row, a date like 03/04/2007 read day first. Rows already on the
roster (same roll number, or same email / phone and name) are **skipped**, so the same file can be uploaded again.
**Roster page:** an upload guide, a preview (ready / need fixing / warnings / already on roster), then after import
*Download updated list* (codes, PINs, dates of birth), *Download rows to fix* (errors.csv: the bad rows + a problem
column, ready to fix and upload) and *Print slips* (code + PIN, never the date of birth).

### One-time setup after pulling Phase 9 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt               # adds openpyxl (reads .xlsx)
flask --app run db upgrade                     # email / roll number / date of birth optional, + phone, pin (nothing deleted)
python seed_phase9.py <your institution admin email>
python run.py
```
The roll number stays unique inside a test through a *filtered* unique index (`WHERE roll_number IS NOT NULL`), because
SQL Server allows only one NULL in a normal unique constraint. In `sqlcmd` use `-I` (QUOTED_IDENTIFIER ON) when you
change the `candidates` table by hand; SSMS and the app already have it on.

### Done-when demo
1. **Candidate Roster** → *Phase 5 Demo Test* → read the guide → drop `demo_roster_messy.csv`. Preview:
   6 ready, 4 need fixing (rows 7, 8, 9, 11), 3 warnings, the "Sr No" / "Father Name" columns ignored.
2. **Import 6 candidates** → *Download updated list* (Sana Fatima has a PIN, the others a date of birth) and
   *Download rows to fix* (errors.csv with the 4 rows). Upload the same file again: 6 skipped, nothing doubled.
3. **Print slips** → Sana's slip shows her PIN; the others say "Your date of birth".
4. Candidate login → Sana's code → **PIN** → a wrong PIN is refused, her PIN signs her in.

### Tests
```powershell
python -m pytest -q                       # 238 tests: Phase 1-9
python -m pytest tests/test_phase9.py -v
```
Checked on SQL Server 2022: migration upgrade → downgrade → upgrade, `flask db check` clean, the Phase 5/6/7/9 tests,
and `loadtest/mock_exam.py` PASS.

## Phase 10 — Aptitude-only homepage, institution directory, work-email code

**Homepage:** only the Aptitude Test platform (the Course Platform door and the "one engine, two modes" section are
gone). The name is **Assessify** on every page.

**Signup — finding the institution.** The name box is a search over the institution directory
(`directory_institutions` + `directory_campuses`): type "NED", "FAST Lahore", "Punjab College"… and pick the campus.
Type, city and website fill in from the directory. Each **campus** is its own account with its own admin and data
(NED City Campus and NED Thar Campus register separately); a campus that is pending / approved / suspended cannot
register again (a rejected one can). Not listed? "My institution isn't in the list" (type everything) or
"Add a new campus of …" (institution listed, campus not). When the Super Admin **approves** such a signup it is added
to the directory, so the next person finds it.
The list comes from `data/institution_directory.csv` (one row per campus; universities with their official email
domains, plus some college and school networks). It is typed from memory: **check it and add your own rows**, then
run `python seed_directory.py` again (it only adds / updates). Leave `email_domain` empty when unsure: a wrong domain
blocks that institution's real admins.

**Signup — the admin.** No phone and no designation any more (the `users.phone` / `users.designation` columns are
dropped). The **work email** gets a 6-digit code (10 minutes, 5 wrong tries, 60 s before *Resend*, 5 codes per hour);
the signup is refused without a fresh verification. Rules:
- Gmail / Yahoo / Outlook and other personal providers are refused…
- …unless the admin ticks **"We don't have an official email"** and uploads a **proof** (PDF / JPG / PNG, max 5 MB:
  authorisation letter or registration certificate). Not allowed when the directory knows the institution's domain.
- A directory institution with a known domain: the email must be on it (sub-domains like `cs.neduet.edu.pk` are fine).
- Any other domain must have a mail server in DNS (MX). If DNS can't be reached the check is skipped.

**Super Admin:** each row shows *From list* / *Not in list (typed)*, *Email verified*, *Domain matches* /
*Domain not confirmed*, and a red *Free email: check proof* with a **View proof** button.

### One-time setup after pulling Phase 10 (PowerShell, inside `backend/`)
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt               # adds dnspython (email domain check)
flask --app run db upgrade                     # directory, email codes, proof; drops users.phone + users.designation
python seed_directory.py                       # loads data/institution_directory.csv (safe to run again)
python run.py
```
With `MAIL_BACKEND=console` (the default) the signup code is **printed in this terminal** instead of emailed. To send
real emails set the `MAIL_*` lines in `.env` (Gmail + App Password, see `.env.example`).

### Done-when demo
1. Homepage: only Aptitude Test, "Assessify" everywhere.
2. Signup → type `ned` → pick **Thar Campus, Mithi** → type, city and website are filled in.
3. Email `you@gmail.com` → refused. `admissions@neduet.edu.pk` → *Send code* → the code appears in the backend
   terminal → a wrong code says "4 tries left" → the right code shows **✓ Verified** → submit.
4. Signup again → `ned` → Thar Campus shows **Already registered**; City Campus is still free.
5. A school without official email: pick *Beaconhouse School System · Lahore Branch*, tick "no official email",
   Gmail + code + a PDF → submitted. Super Admin sees the red tag and downloads the proof.
6. "My institution isn't in the list" → Bright Future College, Latifabad Campus, Hyderabad → Super Admin approves →
   searching `bright` on the signup page now finds it (already registered).

### Tests
```powershell
python -m pytest -q                       # 258 tests: Phase 1-10
python -m pytest tests/test_phase10.py -v
```
