# Assessify API — Phase 1 contract

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
