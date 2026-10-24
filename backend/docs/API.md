# Assessify API — Phase 1 + 2 + 3 contract

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
