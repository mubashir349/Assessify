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
    models/              database tables (institution.py, user.py, department.py, question.py, aptitude_test.py, candidate.py)
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
