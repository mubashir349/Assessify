# Assessify API — Phase 1–6 contract

Base URL (dev): `http://127.0.0.1:5000/api/v1`
All bodies are JSON. Login is an **httpOnly cookie**, so every browser call uses `credentials: 'include'` (the frontend's `api.js` does this).

Success → `{ "data": ... }`  ·  Error → `{ "error": { "code": "...", "message": "...", "details": { field: "message" } } }`

| Code | Meaning |
|---|---|
| 400 BAD_REQUEST | Body is not JSON / bad filter |
| 401 UNAUTHORIZED, SESSION_EXPIRED, INVALID_CREDENTIALS | Not signed in / wrong email or password |
| 403 FORBIDDEN | Signed in but wrong role |
| 403 INSTITUTION_PENDING / REJECTED / SUSPENDED / NOT_ACTIVE | Institution is not approved (login or an old session) |
| 404 NOT_FOUND | |
| 409 EMAIL_TAKEN, INVALID_TRANSITION | Duplicate email / status change not allowed |
| 413 FILE_TOO_LARGE | Upload bigger than `MAX_UPLOAD_MB` (Phase 3) |
| 415 UNSUPPORTED_FILE_TYPE | Not a `.pdf` file (Phase 3) |
| 422 VALIDATION_ERROR | `details` has one message per bad field |

## Auth
| Method | Path | Who | Body → Result |
|---|---|---|---|
| POST | `/auth/login` | public | `{email, password}` → `{user}` and sets the login cookie |
| POST | `/auth/logout` | anyone | clears the cookie |
| GET | `/auth/me` | signed in | `{user}` (re-checks the account and its institution on every call) |

`user` = `{id, full_name, email, role, created_at, institution: {id, name, type, status} | null}`
`role` = `super_admin` or `institution_admin`

## Institutions
| Method | Path | Who | Body → Result |
|---|---|---|---|
| POST | `/institutions/signup` | public | see below → `201 {institution, message}`; institution starts as `pending` |

```json
{ "institution_name": "NED University", "institution_type": "University|College|Institute|Training Center",
  "city": "Karachi", "website": "https://… (optional)", "admin_name": "Dr Ayesha",
  "admin_email": "a@ned.edu", "admin_phone": "0300 1234567", "admin_designation": "Registrar (optional)",
  "password": "min 8 chars" }
```

## Super Admin (role `super_admin` only)
| Method | Path | Body → Result |
|---|---|---|
| GET | `/super/institutions?status=&q=` | `{items: [institution…], counts: {pending, approved, rejected, suspended, total}}` — `q` searches name, city, admin email |
| PATCH | `/super/institutions/<id>` | `{status: "approved"|"rejected"|"suspended", note?}` → `{institution}` |

Allowed status changes: `pending → approved | rejected` · `approved → suspended` · `suspended → approved` · `rejected → approved`.
Suspending takes effect on the next request of every signed-in admin of that institution.

`institution` = `{id, name, type, city, website, status, created_at, reviewed_at, review_note, admin: {full_name, email, phone, designation}}`

## Health
`GET /health` · `GET /health/db`

## Meta (public) — Phase 2
`GET /meta` → `{institution_types, institution_statuses, levels: [{value, term, term_plural, name_placeholder}], modes: [{value, label, description}], defaults: {level, mode}}`
The frontend builds every dropdown from this; it hardcodes none of them.

## Fields / Departments (role `institution_admin` only, scoped to the caller's institution) — Phase 2
| Method | Path | Body → Result |
|---|---|---|
| GET | `/departments?level=&q=` | `{items: [department…]}` |
| POST | `/departments` | `{name, level, mode, subjects: [..]}` → `201 {department}` |
| GET | `/departments/<id>` | `{department}` |
| PUT | `/departments/<id>` | same body as POST → `{department}` |
| DELETE | `/departments/<id>` | `{deleted: id}` (its subjects are deleted too) |

`department` = `{id, name, level, term, mode, subjects: [names], subject_count, created_at, updated_at}`
Errors: `422 VALIDATION_ERROR` (name 2–150 chars, valid level/mode, 1–50 subjects), `409 DUPLICATE_NAME` (same name at the same level), `404 NOT_FOUND` (also returned for another institution's id).

## Dashboard — Phase 2
`GET /dashboard/summary` (institution_admin) → `{institution: {name}, departments: {total, by_level, general_tests, recent: [..]}, subjects: {total}}`

Phase 7 adds: `tests: {total, published, draft, live, upcoming, ended, next: [{id, name, starts_at}]}`,
`candidates: {total, in_progress, locked, submitted}`, `average_percent` (all submitted attempts, or `null`) and
`questions: {approved, waiting_review}`. Overdue attempts are auto-submitted first, so the numbers are current.


## Phase 3 — AI question generation, draft review, question bank
All routes: role **`institution_admin`** only (`401` not signed in / session expired · `403 FORBIDDEN` super admin ·
`403 INSTITUTION_NOT_ACTIVE` institution suspended). The institution always comes from the login cookie — an
`institution_id` sent by the browser is ignored. Another institution's attempt or question id → **`404 NOT_FOUND`**
(it does not reveal that the record exists).

`/meta` now also returns `question_types: [{value: "mcq"|"true_false", label}]`, `difficulties: [{value: "easy"|"medium"|"hard", label}]`,
`question_statuses`, and `generation_limits: {max_upload_mb, max_questions, max_files, description_min_words}`.

### Question lifecycle
| Status | Meaning | Allowed actions |
|---|---|---|
| `draft` | Written by the AI (or edited). Never in the bank. | edit, approve, reject, regenerate |
| `approved` | Checked by an admin. **Only status shown in the bank.** | none (final; cannot be overwritten by regeneration) |
| `rejected` | Turned down (optional reason). Not in the bank. | regenerate |
| `replaced` | Old version of a regenerated question, kept as history. `replaced_by_id` → new draft. | none |

Wrong action → `409 INVALID_TRANSITION` `{details: {status}}`. Attempt status: `processing` → `completed` (all requested
questions) · `partial` (some AI answers were unusable) · `failed` (none; `error` explains why).

### AI errors (the attempt is still saved; `details.attempt_id` points to it when one was created)
| HTTP | Code | When |
|---|---|---|
| 503 | `AI_NOT_CONFIGURED` | `AI_PROVIDER`/key missing in `.env` (no attempt is created) |
| 503 | `AI_AUTH_FAILED` | provider rejected the API key |
| 429 | `AI_RATE_LIMITED` | free-tier rate limit / daily quota reached |
| 504 | `AI_TIMEOUT` | provider too slow (`AI_TIMEOUT_SECONDS`) |
| 503 | `AI_UNAVAILABLE` | network error / provider outage (5xx) |
| 502 | `AI_REQUEST_REJECTED` | provider refused the request (usually a wrong `AI_MODEL`) |
| 502 | `AI_BAD_RESPONSE` / `AI_NO_VALID_QUESTIONS` | answer was not valid question JSON after the bounded retries |

### Objects
`question` = `{id, attempt_id, department_id, department_name, level, subject, topic, question_type, text, options: [..],
correct_index (0-based), explanation, difficulty, marks, status, is_edited, rejection_reason, reviewed_by, reviewed_at,
regenerated_from_id, replaced_by_id, created_at, updated_at}`

`attempt` = `{id, department_id, department_name, level, subject, question_type, difficulty, requested_count, marks, focus,
source: {kind: "pdf"|"description", files, filename (comma-separated names), pages, characters, truncated, ocr}, status, generated_count, discarded_count, error: {code, message}|null,
provider, model, counts: {draft, approved, rejected, replaced}, created_by, created_at, updated_at, questions?: [question…]}`

Paged lists = `{items: [...], page, per_page, total, pages}` (`page` from 1, `per_page` 1–100, default 20).

### Endpoints
| Method | Path | Body / query → Result |
|---|---|---|
| GET | `/questions/ai-status` | → `{provider, model, configured, message, reads_images}` (never the key) |
| POST | `/questions/check-pdf` | multipart `file` → `{filename, pages, characters (typed), truncated, typed_pages, needs_ocr, image_pages, skipped_photo_pages, headings: [chapter/section titles found]}` or the same PDF errors as generate. Pages are classified one by one: `image_pages` = photo/scan pages the AI (Gemini only) will read on generate; `skipped_photo_pages` = photo pages that will not be read (provider can't see images, or `OCR_MAX_PAGES` reached). No AI call, no quota, nothing saved — the Generate page calls it as soon as a file is picked |
| POST | `/questions/generate` | **multipart/form-data** (below) → `201 {attempt}` with its draft `questions` |
| GET | `/questions/attempts?status=&q=&page=&per_page=` | paged `attempt` list, newest first (`q` searches subject, field, PDF name) |
| GET | `/questions/attempts/<id>?include_replaced=1` | `{attempt}` with questions (replaced ones only if asked) |
| POST | `/questions/attempts/<id>/approve-all` | approves every valid draft → `{approved: [ids], skipped: [{id, errors}], attempt}` |
| POST | `/questions/attempts/<id>/regenerate` | `{include_drafts?: false}` → replaces rejected (and drafts if asked) and tops up to `requested_count` (also retries a failed attempt) → `{replaced, added, requested, attempt}` · `409 NOTHING_TO_REGENERATE` |
| GET | `/questions/bank?department_id=&level=&subject=&difficulty=&question_type=&topic=&q=&page=&per_page=` | **approved only**, paged, plus `summary: {total, by_difficulty, by_level, by_subject, by_type}` · bad filter → `400` |
| GET | `/questions/<id>` | `{question}` |
| PUT | `/questions/<id>` | draft only: `{text, options, correct_index, explanation?, topic?, difficulty?, marks?}` → `{question}` · `422 VALIDATION_ERROR` |
| POST | `/questions/<id>/approve` | draft only, re-validated → `{question}` · `422 QUESTION_INVALID` |
| POST | `/questions/<id>/reject` | draft only, `{reason?}` (≤500) → `{question}` |
| POST | `/questions/<id>/regenerate` | draft or rejected → `201 {question: new draft, replaced_id}`; if the AI fails nothing changes |

**`POST /questions/generate` fields**

| Field | Rules |
|---|---|
| `files` | 0–`MAX_PDFS_PER_GENERATION` (10) PDFs, repeat the field per file (`file` = one PDF, still accepted). All together ≤ `MAX_UPLOAD_MB` (200). Each: real PDF, not password-protected, typed text and/or photo pages. A failing file is named in the message: `"b.pdf": …` |
| `department_id` | required, one of **your** fields/departments (another institution's → 404) |
| `subject` | required, one of that department's subjects |
| `question_type` | `mcq` (4 options) or `true_false` |
| `difficulty` | `easy` · `medium` · `hard` |
| `count` | 1 – `MAX_QUESTIONS_PER_ATTEMPT` (100; default 10) |
| `marks` | 1 – 100 (default 1) |
| `focus` | ≤ 500 chars. With PDFs: optional instructions. **Without any PDF: required, at least `DESCRIPTION_MIN_WORDS` (8) words** describing the scope, else `422 VALIDATION_ERROR {file, focus}` |

PDF errors: `422 VALIDATION_ERROR {file}` (missing) · `415 UNSUPPORTED_FILE_TYPE` · `413 FILE_TOO_LARGE` · `422 EMPTY_FILE` ·
`422 INVALID_PDF` (not a PDF / damaged) · `422 PDF_ENCRYPTED` · `422 PDF_NO_TEXT` (no text and no page pictures; photos/scans with a provider that can't read images; or photos too unclear to read).
`409 GENERATION_IN_PROGRESS` if the same PDF + settings is already being generated.

Example (curl, after signing in with `-c cookies.txt`):
```bash
curl -b cookies.txt -F file=@chapter3.pdf -F department_id=1 -F subject=Biology \
     -F question_type=mcq -F difficulty=medium -F count=5 -F marks=1 \
     http://127.0.0.1:5000/api/v1/questions/generate
```
```json
{"data": {"attempt": {"id": 7, "status": "completed", "requested_count": 5, "generated_count": 5, "discarded_count": 0,
  "source": {"filename": "chapter3.pdf", "pages": 12, "characters": 31840, "truncated": true},
  "provider": "gemini", "model": "gemini-3.5-flash-lite", "counts": {"draft": 5, "approved": 0, "rejected": 0, "replaced": 0},
  "questions": [{"id": 31, "status": "draft", "text": "Where does photosynthesis take place?",
                 "options": ["Chloroplasts", "Mitochondria", "Nucleus", "Ribosomes"], "correct_index": 0,
                 "explanation": "The chapter states it happens in chloroplasts.", "topic": "Photosynthesis",
                 "difficulty": "medium", "marks": 1, "...": "..."}]}}}
```
Error example: `{"error": {"code": "AI_RATE_LIMITED", "message": "The free AI quota or rate limit was reached. ...", "details": {"attempt_id": 8}}}`

## Tests (role `institution_admin` only, scoped to the caller's institution) — Phase 4
| Method | Path | Body → Result |
|---|---|---|
| GET | `/tests?status=&level=&q=` | `{items: [test_summary…]}` · bad filter → `400` |
| POST | `/tests/availability` | `{level, compositions}` → `{availability}` — the live 1.5× check, nothing is saved |
| POST | `/tests` | test body → `201 {test}` (status `draft`) |
| GET | `/tests/<id>` | `{test}` with a fresh `availability` |
| PUT | `/tests/<id>` | test body → `{test}` · draft only |
| DELETE | `/tests/<id>` | `{deleted: id}` · draft only |
| POST | `/tests/<id>/publish` | no body → `{test}` with `status: "published"` |

**Test body**
```json
{ "name": "Undergraduate Admission Test", "level": "Undergraduate",
  "compositions": [ { "department_id": 3, "rows": [
      { "subject": "Mathematics", "question_type": "mcq", "difficulty": "any", "count": 10 },
      { "subject": "Physics",     "question_type": "mcq", "difficulty": "easy", "count": 5 } ] } ],
  "schedule": { "timing_mode": "fixed", "starts_at": "2026-11-05T09:00:00Z", "ends_at": "2026-11-05T11:00:00Z",
                "duration_minutes": null, "result_release": "scheduled", "release_on": "2026-11-12" } }
```
| Field | Rules |
|---|---|
| `name` | 3–200 chars |
| `level` | `Undergraduate` · `Masters` · `PhD`; every department must be at this level |
| `compositions` | ≥ 1 of **your** departments (another institution's → `404`), each once, each with ≥ 1 row |
| row `subject` | one of that department's subjects (case-insensitive) |
| row `question_type` | `mcq` · `true_false` |
| row `difficulty` | `any` · `easy` · `medium` · `hard`; the same subject + type + difficulty twice → `422` (merge the rows) |
| row `count` | questions per candidate, 1–200 |
| `schedule.starts_at` / `ends_at` | ISO date-time **with a timezone** (the browser sends UTC: `new Date('2026-11-05T14:00').toISOString()`); end after start |
| `schedule.timing_mode` | `flexible`: window + `duration_minutes` (5–600, not longer than the window) · `fixed`: everyone starts at `starts_at` and stops at `ends_at`; `duration_minutes` is computed (5–600) and whatever you send is ignored |
| `schedule.result_release` | `immediate` · `scheduled` (then `release_on` `YYYY-MM-DD`, not before the test ends) |

**The 1.5× pool rule:** for every row `needed = ceil(count × 1.5)` and `pool` = **approved** questions of your institution with
the same department, subject, type and difficulty (`any` = all three difficulties), at the test's level.
Rows that share a subject + type (e.g. Maths·MCQ·Any and Maths·MCQ·Easy) are also checked together, because they draw
from the same questions.

`availability` = `{pool_factor: 1.5, all_sufficient, rows: [{department_id, department, subject, question_type, difficulty, count, needed, pool, short, sufficient}], shortfalls: [row… + label]}`
(a "rows together" shortfall has `difficulty: "combined"`).

`test` = `{id, name, level, term, status, departments: [{id, name, mode}], questions_per_candidate: {"<department_id>": n},
compositions: [{department_id, rows: [{id, subject, question_type, difficulty, count}]}],
schedule: {timing_mode, starts_at, ends_at, duration_minutes, result_release, release_on}, availability, published_at, created_at, updated_at}`
`test_summary` = the same without `compositions` and `availability`.

Errors: `422 VALIDATION_ERROR` (`details` keys: `name`, `level`, `compositions`, `schedule.starts_at`, `schedule.ends_at`,
`schedule.duration_minutes`, `schedule.timing_mode`, `schedule.result_release`, `schedule.release_on`) ·
`409 POOL_TOO_SMALL` on publish with any shortfall, `details: {shortfalls: [...]}`, the test stays `draft` ·
`422 SCHEDULE_IN_PAST` publish after the start time · `409 INVALID_TRANSITION` already published ·
`409 TEST_LOCKED` PUT / DELETE on a published test · `404 NOT_FOUND` (also for another institution's test).

Phase 2 routes gain two refusals so a test never loses part of its paper:
`DELETE /departments/<id>` → `409 DEPARTMENT_IN_USE` while any test uses it;
`PUT /departments/<id>` → `409 DEPARTMENT_IN_USE` (level change) or `409 SUBJECT_IN_USE` (removing / renaming a subject a test uses).

`GET /meta` gains `row_difficulties` (with `any`), `timing_modes`, `result_releases`, `pool_factor`, `test_limits: {max_per_row, min_duration, max_duration}`.


## Candidate roster (role `institution_admin` only, scoped to the caller's institution) — Phase 5
A roster belongs to **one published test** (its fields / departments are locked then, so a candidate's field can't
disappear). A draft test → `409 TEST_NOT_PUBLISHED`; another institution's test or candidate → `404 NOT_FOUND`.

| Method | Path | Body / query → Result |
|---|---|---|
| GET | `/roster?test_id=&department_id=&q=&page=&per_page=` | paged `candidate` list (by roll number; `per_page` 1–200, default 50; `q` searches name, roll number, email) + `summary: {total, logged_in, by_department: [{id, name, count}]}` · no `test_id` → `400` |
| POST | `/roster/import` | **multipart/form-data**: `file` (CSV), `test_id`, `dry_run` (`1` = check only, save nothing) → see below |
| GET | `/roster/template.csv` | CSV with the expected headings + 2 example rows |
| GET | `/roster/export.csv?test_id=` | the roster with access codes and dates of birth, for printing test slips |
| GET | `/roster/counts` | `{counts: {"<test_id>": n}}` for all of the institution's tests |
| POST | `/roster` | `{test_id, full_name, email, roll_number, date_of_birth, department_id, access_code?}` → `201 {candidate}` |
| PUT | `/roster/<id>` | `{full_name, email, roll_number, date_of_birth, department_id}` → `{candidate}` (the access code is **not** changed here) |
| POST | `/roster/<id>/new-code` | → `{candidate}` with a new generated code; the old code and any session signed in with it stop working at once |
| DELETE | `/roster/<id>` | → `{deleted: id}`; the candidate's session stops working |

`candidate` = `{id, test_id, full_name, email, roll_number, date_of_birth: "YYYY-MM-DD", access_code: "8K4Q-2P1X", code_generated,
department: {id, name}, last_login_at, login_count, created_at, updated_at}`

### CSV import
First row = headings, any order, case and spacing don't matter. Accepted spellings:

| Column | Headings | Rules |
|---|---|---|
| name | `name`, `full name`, `candidate name` | 2–150 characters |
| email | `email`, `e-mail` | valid address (stored lower-case) |
| roll number | `roll number`, `roll no`, `roll` | ≤ 50 chars, unique within the test (case-insensitive) |
| access code | `access code`, `code` — **optional column / optional value** | empty → generated. Given → 6–20 letters/digits (dashes and spaces ignored), unique on the whole platform |
| date of birth | `date of birth`, `dob` | `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `DD.MM.YYYY`, `14-Mar-2008`; day comes **before** month; not in the future |
| field | `field`, `department`, `field / department` | name of one of the test's fields / departments (case-insensitive). Not needed when the test has only one |

Comma, semicolon or tab separated; UTF-8 (with or without BOM) or Windows-1252 (old Excel "CSV"). Blank lines are
skipped. At most 5,000 rows and 2 MB per file.

Result → `{test_id, dry_run, total_rows, imported (or would_import when dry_run), codes_generated, error_count,
errors: [{row, full_name, roll_number, issues: ["…"]}], roster_total}`. **Valid rows are saved, invalid rows are reported**
with the row number Excel shows (headings = row 1) — e.g. `Field "Pre-Eng" is not part of this test (did you mean
"Pre-Engineering"?)`, `Duplicate roll number PE-001 (also row #57)`, `Roll number PE-001 is already on this test's roster`.
Importing the same file again therefore adds nothing twice.

File errors: `422 VALIDATION_ERROR {file}` (no file) · `415 UNSUPPORTED_FILE_TYPE` (not .csv / .txt) · `413 FILE_TOO_LARGE` ·
`422 EMPTY_FILE` · `422 CSV_MISSING_COLUMNS {file, columns: [...]}` · `422 TOO_MANY_ROWS`.

### Access codes
Generated codes are 8 characters from `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (no 0/O/1/I/L), shown as `XXXX-XXXX`, made with
Python's `secrets` module and unique on the whole platform. They are stored readable (the admin must print / email them);
they only work together with the date of birth, for one test, until it ends.

## Candidate sign-in (public) — Phase 5
| Method | Path | Body → Result |
|---|---|---|
| POST | `/candidate/login` | `{access_code, date_of_birth: "YYYY-MM-DD"}` → `{candidate}` and sets the `candidate_token` cookie |
| POST | `/candidate/logout` | clears it |
| GET | `/candidate/me` | signed-in candidate → `{candidate}` (still works after the test ended, for the result page) |

`candidate` (session) = `{id, full_name, roll_number, department: {id, name}, institution: {id, name},
test: {id, name, level, schedule, subjects: [names for this candidate's field], question_count}}` — never the access code or date of birth.

The code is matched without case, dashes or spaces (`8k4q 2p1x` = `8K4Q-2P1X`).

| HTTP | Code | When |
|---|---|---|
| 422 | `VALIDATION_ERROR` | code or date missing / date not a date |
| 401 | `INVALID_ACCESS_CODE` | wrong code **or** wrong date of birth (one message for both) |
| 429 | `TOO_MANY_ATTEMPTS` | 5 wrong tries for one code, or 50 from one network address, within 15 minutes (`details.retry_after` seconds). Limits in `.env` |
| 403 | `INSTITUTION_NOT_ACTIVE` | the institution is suspended |
| 403 | `TEST_CLOSED` | the test's end time has passed |
| 401 | `UNAUTHORIZED` / `SESSION_EXPIRED` | on `/candidate/me`: no cookie, removed from the roster, a new code was issued, or expired |

Signing in **before** the start time works (the start page shows the countdown); Phase 6 refuses starting the paper early.
The candidate cookie is separate from the admin login cookie: both can be used in one browser, and a candidate token is
never accepted on admin routes (`401`). It lasts until 1 hour after the test ends, at most `CANDIDATE_SESSION_HOURS` (12).
Phase 6 routes use the `candidate_required` decorator in `app/common/candidate.py` (sets `g.current_candidate`).

The roster `candidate` gains (Phase 6) `attempt: {id, reference, status, started_at, submitted_at, lock_count, score, max_score} | null`.
A candidate who has started can't be removed or moved to another field: `409 CANDIDATE_HAS_ATTEMPT`.

## Taking the test (candidate cookie) — Phase 6
All routes need the candidate cookie from `/candidate/login`. They still answer after the end time (so the result page
works and late requests get a clear `TIME_UP`), until the cookie expires 1 hour after the test ends.

| Method | Path | Body → Result |
|---|---|---|
| GET | `/exam` | → `{gate}` — the start page's time gate, decided by the **server** clock |
| POST | `/exam/start` | → `{attempt, questions}`. Builds the random paper the first time; again (reload, lost connection) → the same attempt and paper |
| GET | `/exam/paper` | → `{attempt, questions}` (submitted → `questions: []`) |
| PUT | `/exam/answers/<n>` | `{choice: 0-based index as shown \| null (clear), flagged?: true\|false}` (either key) → `{attempt, question}` |
| POST | `/exam/lock` | `{reason: "fullscreen_exit" \| "tab_hidden"}` → `{attempt}` with `status: "locked"` (locking twice = one event) |
| POST | `/exam/submit` | → `{attempt}` with `status: "submitted"`, scored on the server (twice → the same result) |
| GET | `/exam/result` | → `{attempt, release, release_on, email, score}` — `score` only when `result_release = immediate`, else `null` |

**Institution Admin:** `POST /attempts/<id>/unlock` → `{attempt}` (admin view with `score`, `events`). Another
institution's attempt → `404`; not locked → `409 INVALID_TRANSITION`. The roster page and the Phase 7 monitor show
an *Unlock* button. `POST /attempts/<id>/end` (Phase 7) → `{attempt}` submitted with `submit_reason: "admin"`, scored
with the answers saved so far; already submitted → `409 ALREADY_SUBMITTED`.

`gate` = `{state: "not_started"|"open"|"resume"|"submitted"|"closed", can_start, server_now, starts_at, ends_at,
seconds_until_start, timing_mode, duration_minutes, minutes_if_started_now, attempt|null}`

`attempt` = `{id, reference: "APT-2026-00012", status: "in_progress"|"locked"|"submitted", timing_mode, started_at, deadline_at,
remaining_seconds, server_now, locked_at, lock_count, submitted_at, submit_reason: "candidate"|"time_up"|null,
question_count, answered_count}`

`question` (as the candidate sees it) = `{number (1-based), subject, question_type, text, options: [..shuffled..], marks,
choice: 0-based|null, flagged}` — **never** `correct_index`, `explanation`, `difficulty` or the bank's question id.

`score` = `{score, max_score, percent, correct, answered, questions, by_subject: [{subject, score, max_score, correct, questions}]}`
(totals only — which questions were right is never sent, because others may still be taking a flexible test).

### Rules
| Rule | How |
|---|---|
| Time gate | start before `starts_at` → `403 TEST_NOT_STARTED` (`details: {starts_at, seconds_left}`); at / after `ends_at` → `403 TEST_CLOSED` |
| Fixed time | `deadline_at` = the test's `ends_at` for everyone, so a late starter gets less time |
| Flexible | `deadline_at` = start + `duration_minutes`, never after the window's end |
| Random paper | for each composition row of the candidate's field: random approved questions of that department + subject + type + difficulty (`any` = all). Specific-difficulty rows draw first; a question is never on one paper twice. Subjects in the test's order, questions shuffled inside each subject, MCQ options shuffled (True/False keeps its order). Pool short at start → `409 PAPER_UNAVAILABLE` |
| Saving answers | one request per click. After `deadline_at` → `409 TIME_UP` (the attempt is submitted with the answers saved before the end, nothing changes); after submit → `409 ALREADY_SUBMITTED`; locked → `423 ATTEMPT_LOCKED`; not started → `409 ATTEMPT_NOT_STARTED`; bad `choice` / `flagged` → `422`; no such number → `404` |
| Lock | the page reports leaving fullscreen or hiding the tab. Locked: answers and submit → `423`. Fixed time keeps running; a flexible timer is frozen (the frozen minutes are given back on unlock, never past the window's end). A locked attempt is still submitted at the end of the window |
| Auto-submit | no background job: every request that touches an attempt past its deadline submits it first (`submit_reason: "time_up"`). The test page also calls `/exam/submit` when its timer reaches 0 |
| Scoring | on submit, on the server: correct when the chosen option is the question's `correct_index`; `score` = sum of `marks` of correct answers; unanswered = 0 |

| HTTP | Code | When |
|---|---|---|
| 403 | `TEST_NOT_STARTED` | start before the start time |
| 403 | `TEST_CLOSED` | start after the end time |
| 409 | `ATTEMPT_NOT_STARTED` | answer / lock / submit / result before starting |
| 409 | `TIME_UP` | an answer after the deadline (the attempt is submitted by this request) |
| 409 | `ALREADY_SUBMITTED` | start / answer after submitting |
| 409 | `NOT_SUBMITTED` | result before submitting |
| 409 | `PAPER_UNAVAILABLE` | not enough approved questions left for a row (should not happen: approved questions stay approved) |
| 423 | `ATTEMPT_LOCKED` | answer / submit while locked |


## Live monitor (role `institution_admin` only) — Phase 7
| Method | Path | Result |
|---|---|---|
| GET | `/monitor/tests` | `{tests: [{id, name, level, state: "live"\|"upcoming"\|"ended", starts_at, ends_at, timing_mode, candidates}]}` — published tests, live first |
| GET | `/monitor?test_id=&status=&department_id=&q=` | `{test, server_now, disconnected_after_seconds, counts, items}` |
| POST | `/attempts/<id>/unlock` | see Phase 6 |
| POST | `/attempts/<id>/end` | ends one candidate's test now (`submit_reason: "admin"`) |

The page polls `/monitor` every 5 seconds. Overdue attempts are auto-submitted before the snapshot is built.
`counts` = `{all, not_started, in_progress, disconnected, locked, auto_submitted, completed}` for the **whole** test
(filters only change `items`). Monitor status of a candidate:

| status | when |
|---|---|
| `not_started` | no attempt yet |
| `in_progress` | answering, and the test page reached the server in the last `MONITOR_DISCONNECTED_SECONDS` (default 75) |
| `disconnected` | in progress, but nothing arrived for longer. Every candidate `/exam/...` request updates `last_seen_at` (the test page resyncs every 30 s) |
| `locked` | waits for *Unlock* |
| `auto_submitted` | submitted because the time ran out |
| `completed` | submitted by the candidate, or ended by the admin |

`item` = `{candidate_id, full_name, roll_number, email, department: {id, name}, status, attempt|null}` with
`attempt` = `{id, reference, status, started_at, deadline_at, remaining_seconds, answered_count, question_count,
lock_count, locked_at, lock_reason, submitted_at, submit_reason, score, max_score, last_seen_at, seconds_since_seen}`.
Never the access code, date of birth or answers. Another institution's test → `404`; a draft test → `409 TEST_NOT_PUBLISHED`;
unknown `status` → `400`.


## Reports, insights and result emails (role `institution_admin` only) — Phase 7
| Method | Path | Body → Result |
|---|---|---|
| GET | `/reports/tests?q=&level=&year=` | `{tests: [{id, name, level, state, starts_at, ends_at, result_release, candidates, submitted, average_percent}]}` (`year` = year of the start time) |
| GET | `/reports/tests/<id>?department_id=&q=&status=&email=` | the report (below) |
| GET | `/reports/tests/<id>/export.csv?(same filters)` | CSV of the candidate list (UTF-8 with BOM, opens in Excel) |
| POST | `/reports/tests/<id>/send-results` | `{candidate_ids?: [..], resend?: false}` → `{sent, logged, failed, tried, remaining}` |
| GET | `/reports/bank-insights` | `{subjects: [{field, subject, approved, waiting_review}], draft_tests_short_of_questions: [..], tips: [..]}` |
| POST | `/reports/ai-summary` | `{scope: "test", test_id}` or `{scope: "bank"}` → `{scope, insights: [..3-6 strings..], provider, model}` |

Report = `{test, summary, by_department, by_subject, hardest_questions, insights, email, candidates}`:
- `summary` = `{candidates, submitted, in_progress, not_attempted, absent (only after the end), auto_submitted,
  average_percent, median_percent, highest_percent, lowest_percent, distribution: [{label: "0-20%", count} x5]}`.
  Percent = score / max score × 100 of one attempt; only submitted attempts count.
- `by_department` = `[{id, name, candidates, submitted, average_percent, highest_percent}]`;
  `by_subject` = `[{subject, questions, correct, unanswered, accuracy_percent}]` (weakest first);
  `hardest_questions` = up to 5 `{question_id, subject, text, difficulty, asked, correct, accuracy_percent}` asked at least twice.
- `insights` = plain-English tips worked out by rules (no AI needed).
- `email` = `{ready, message, backend, counts: {sent, failed, logged, not_sent}}`.
- `candidates` (filtered) = `[{candidate_id, full_name, roll_number, email, department, status: "submitted"|"in_progress"|"not_attempted",
  attempt_id, score, max_score, percent, answered, questions, submitted_at, submit_reason, lock_count, rank, result_email|null}]`,
  best first. `rank` = competition rank (90, 90, 80 → 1, 1, 3). Filters: `status` as above, `email` = `sent|logged|failed|not_sent`
  (submitted candidates only), `q` = name / roll number / email.

CSV cells that start with `= + - @` get a leading `'` so Excel never runs them as formulas.

**Result emails.** One plain-text email per submitted candidate (score, correct answers, marks by subject, roll number).
Candidates already sent are skipped unless `resend: true`; failed ones are tried again. Each try is stored in
`result_emails` (one row per attempt: `status sent|failed|logged`, `error`, `attempts`, `sent_at`) — the email log.
`MAIL_BACKEND=console` (default) sends nothing and writes the email to the server terminal (`logged`);
`MAIL_BACKEND=smtp` sends through `MAIL_SERVER` (Gmail: an *app password*). Not set up → `503 MAIL_NOT_CONFIGURED`.
The password is never stored or returned; errors are short safe messages.

**AI summary.** The AI gets only numbers (averages, subjects, departments, hardest question texts; never names,
emails, roll numbers or answer keys). Same errors as question generation (`AI_NOT_CONFIGURED`, `AI_RATE_LIMITED`, ...).
Unknown `scope` → `422`.

## Hardening — Phase 8

**Every answer** carries `X-Request-ID` (16 characters, or the caller's own `X-Request-ID` when it is up to 64 letters,
digits and dashes), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` and a
`Content-Security-Policy`. API answers are also `Cache-Control: no-store`. On https (`JWT_COOKIE_SECURE=true`) the
site sends `Strict-Transport-Security`.

**Admin login limits.** 5 wrong passwords for one email (also for emails that do not exist) or 30 failed logins from
one network address within 15 minutes → `429 TOO_MANY_ATTEMPTS` with `details.retry_after` (seconds), even for the
right password. A successful login clears that email's count. Settings: `ADMIN_LOGIN_MAX_FAILS`,
`ADMIN_LOGIN_MAX_FAILS_PER_IP`, `ADMIN_LOGIN_WINDOW_SECONDS`. Candidate sign-in limits are unchanged (Phase 5).

**Errors.**
| Status | Code | When |
|---|---|---|
| 503 | `DB_UNAVAILABLE` | the database cannot be reached; `details.request_id` |
| 500 | `SERVER_ERROR` | anything unexpected; the message includes the request id to report. No stack trace is ever sent. |
| 404 | `NOT_FOUND` | unknown `/api/...` path |
| 405 | `METHOD_NOT_ALLOWED` | wrong method on a known path |

`GET /api/v1/health/db` works on SQL Server (`{status, database, server}`) and any other database (`SELECT 1`);
`503` when the database is down.

**Production start check.** With `FLASK_ENV=production` the server refuses to start when `SECRET_KEY` is the default,
the `.env.example` value or shorter than 32 characters, and logs warnings for SQLite, `JWT_COOKIE_SECURE=false`,
`JWT_COOKIE_CSRF=false` and `MAIL_BACKEND=console`.
