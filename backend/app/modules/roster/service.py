"""Phase 5 business rules: the candidate roster of a published test, CSV import and access codes.

Every query is filtered by the signed-in admin's institution_id (from the login, never from the request), so another
institution's test or candidate id gives 404. A roster only exists for a PUBLISHED test (its fields are locked).

CSV import is "import what is valid, report the rest": good rows are saved in one transaction, every bad row comes
back with its row number and a reason, so nothing is dropped silently. dry_run=1 checks the file without saving.
"""
import csv
import difflib
import io
import secrets
from datetime import date, datetime

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.common.errors import ApiError
from app.common.utils import iso
from app.common.validation import EMAIL_RE, raise_if
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import (CODE_ALPHABET, CODE_GROUP, CODE_GROUPS, CODE_MAX_LEN, CODE_MIN_LEN, CSV_COLUMNS,
                                  CSV_REQUIRED, CSV_TEMPLATE_HEADER, DOB_FORMATS, MAX_CSV_BYTES, MAX_IMPORT_ROWS,
                                  Candidate)
from app.models.department import Department
from app.models.user import User

PER_PAGE_DEFAULT, PER_PAGE_MAX = 50, 200
_LABELS = {"full_name": "name", "email": "email", "roll_number": "roll number", "access_code": "access code",
           "date_of_birth": "date of birth", "department": "field"}


# ---------------------------------------------------------------- access codes
def canonical_code(raw) -> str:
    """'8k4q-2p1x ' -> '8K4Q2P1X'. Dashes and spaces are only for reading; the login accepts either form."""
    return "".join(ch for ch in str(raw or "").upper() if ch.isalnum())


def display_code(code: str) -> str:
    """'8K4Q2P1X' -> '8K4Q-2P1X' (groups of 4)."""
    return "-".join(code[i:i + CODE_GROUP] for i in range(0, len(code), CODE_GROUP))


def _code_taken(code: str) -> bool:
    return db.session.query(Candidate.id).filter_by(access_code=code).first() is not None


def new_code(reserved: set | None = None) -> str:
    """Random code from a cryptographic source, unique on the whole platform (31^8 ≈ 850 billion combinations)."""
    reserved = reserved if reserved is not None else set()
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUP * CODE_GROUPS))
        if code not in reserved and not _code_taken(code):
            return code


# ---------------------------------------------------------------- reading
def published_test(institution_id: int, test_id) -> AptitudeTest:
    try:
        test_id = int(test_id)
    except (TypeError, ValueError):
        raise ApiError("VALIDATION_ERROR", "Choose a test.", 422, {"test_id": "Choose a test."})
    test = AptitudeTest.query.filter_by(id=test_id, institution_id=institution_id).first()
    if test is None:
        raise ApiError("NOT_FOUND", "Test not found.", 404)
    if test.status != "published":
        raise ApiError("TEST_NOT_PUBLISHED", "Publish the test first. A roster can only be added to a published test, "
                       "because its fields / departments are locked then.", 409)
    return test


def get_candidate(institution_id: int, candidate_id: int) -> Candidate:
    c = Candidate.query.filter_by(id=candidate_id, institution_id=institution_id).first()
    if c is None:
        raise ApiError("NOT_FOUND", "Candidate not found.", 404)
    return c


def _page_args(args) -> tuple[int, int]:
    try:
        page = max(1, int(args.get("page", 1)))
        per_page = min(PER_PAGE_MAX, max(1, int(args.get("per_page", PER_PAGE_DEFAULT))))
    except (TypeError, ValueError):
        raise ApiError("BAD_REQUEST", "page and per_page must be whole numbers.", 400)
    return page, per_page


def list_roster(institution_id: int, args) -> dict:
    if not args.get("test_id"):
        raise ApiError("BAD_REQUEST", "test_id is required.", 400)
    test = published_test(institution_id, args.get("test_id"))
    q = Candidate.query.filter_by(test_id=test.id)
    if args.get("department_id"):
        try:
            q = q.filter(Candidate.department_id == int(args["department_id"]))
        except ValueError:
            raise ApiError("BAD_REQUEST", "department_id must be a number.", 400)
    search = (args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Candidate.full_name.ilike(like), Candidate.roll_number.ilike(like),
                         Candidate.email.ilike(like)))
    page, per_page = _page_args(args)
    p = q.order_by(Candidate.roll_number, Candidate.id).paginate(page=page, per_page=per_page, error_out=False)

    counts = dict(db.session.query(Candidate.department_id, func.count(Candidate.id))
                  .filter(Candidate.test_id == test.id).group_by(Candidate.department_id).all())
    total = sum(counts.values())
    logged_in = Candidate.query.filter(Candidate.test_id == test.id, Candidate.login_count > 0).count()
    return {"items": [serialise(c) for c in p.items], "page": p.page, "per_page": p.per_page, "total": p.total,
            "pages": p.pages,
            "summary": {"total": total, "logged_in": logged_in,
                        "by_department": [{"id": d.id, "name": d.name, "count": counts.get(d.id, 0)}
                                          for d in test.departments()]}}


def serialise(c: Candidate) -> dict:
    a = c.attempt          # Phase 6: has the candidate started / submitted?
    attempt = None if a is None else {"id": a.id, "reference": a.reference, "status": a.status,
                                      "started_at": iso(a.started_at), "submitted_at": iso(a.submitted_at),
                                      "lock_count": a.lock_count, "score": a.score, "max_score": a.max_score}
    return {**c.to_dict(), "access_code": display_code(c.access_code), "attempt": attempt}


def _refuse_if_started(c: Candidate, what: str) -> None:
    """A candidate who has started keeps their attempt and paper (Phase 6): no delete, no change of field."""
    if c.attempt is not None:
        raise ApiError("CANDIDATE_HAS_ATTEMPT", f"{c.full_name} has already started the test, so you can't {what}.", 409)


def counts_by_test(institution_id: int) -> dict:
    """{test_id: candidates} for the admin's tests - used by the Create Test page."""
    rows = (db.session.query(Candidate.test_id, func.count(Candidate.id))
            .filter(Candidate.institution_id == institution_id).group_by(Candidate.test_id).all())
    return {str(t): n for t, n in rows}


# ---------------------------------------------------------------- one candidate's fields
def parse_dob(raw) -> date | None:
    value = str(raw or "").strip()
    for fmt in DOB_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _norm(s: str) -> str:
    return " ".join(str(s or "").split()).lower()


def _match_department(test: AptitudeTest, raw: str) -> tuple[Department | None, str | None]:
    depts = test.departments()
    if not str(raw or "").strip():
        if len(depts) == 1:                      # a one-field test (e.g. a general test) needs no field column
            return depts[0], None
        return None, f"{_term(test)} is required."
    by_name = {_norm(d.name): d for d in depts}
    dept = by_name.get(_norm(raw))
    if dept:
        return dept, None
    guess = difflib.get_close_matches(_norm(raw), list(by_name), n=1, cutoff=0.6)
    hint = f' (did you mean "{by_name[guess[0]].name}"?)' if guess else \
        " (this test has: " + ", ".join(d.name for d in depts) + ")"
    return None, f'{_term(test)} "{str(raw).strip()}" is not part of this test{hint}.'


def _term(test: AptitudeTest) -> str:
    return "Field" if test.level == "Undergraduate" else "Department"


def clean_fields(test: AptitudeTest, raw: dict, *, department=None, candidate: Candidate | None = None) -> tuple[dict, dict]:
    """Validates one candidate. `department` is an already-matched Department or None (then raw["department"] is a
    name). Returns (clean, errors) with errors = {field: message}. Checks against the saved roster, not the file."""
    errors, clean = {}, {}

    name = " ".join(str(raw.get("full_name") or "").split())
    if not name:
        errors["full_name"] = "Name is required."
    elif not 2 <= len(name) <= 150:
        errors["full_name"] = "Name must be 2-150 characters."
    clean["full_name"] = name

    email = str(raw.get("email") or "").strip().lower()
    if not email:
        errors["email"] = "Email is required."
    elif len(email) > 255 or not EMAIL_RE.match(email):
        errors["email"] = f'Email "{email}" is not valid.'
    clean["email"] = email

    roll = str(raw.get("roll_number") or "").strip()
    if not roll:
        errors["roll_number"] = "Roll number is required."
    elif len(roll) > 50:
        errors["roll_number"] = "Roll number must be at most 50 characters."
    else:
        q = Candidate.query.filter(Candidate.test_id == test.id, func.lower(Candidate.roll_number) == roll.lower())
        if candidate is not None:
            q = q.filter(Candidate.id != candidate.id)
        if q.first() is not None:
            errors["roll_number"] = f"Roll number {roll} is already on this test's roster."
    clean["roll_number"] = roll

    dob_raw = str(raw.get("date_of_birth") or "").strip()
    dob = parse_dob(dob_raw)
    if not dob_raw:
        errors["date_of_birth"] = "Date of birth is required."
    elif dob is None:
        errors["date_of_birth"] = f'Date of birth "{dob_raw}" is not a date (use YYYY-MM-DD or DD/MM/YYYY).'
    elif dob.year < 1900 or dob >= date.today():
        errors["date_of_birth"] = f'Date of birth "{dob_raw}" is not realistic.'
    clean["date_of_birth"] = dob

    if department is None:
        department, msg = _match_department(test, raw.get("department"))
        if msg:
            errors["department"] = msg
    clean["department"] = department

    code_raw = raw.get("access_code")
    if code_raw is not None and str(code_raw).strip():
        code = canonical_code(code_raw)
        if not CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN:
            errors["access_code"] = f"Access code must be {CODE_MIN_LEN}-{CODE_MAX_LEN} letters or digits."
        elif _code_taken(code):
            errors["access_code"] = f"Access code {str(code_raw).strip()} is already in use. Leave it empty to get one generated."
        clean["access_code"] = code
    else:
        clean["access_code"] = None
    return clean, errors


def _new_candidate(test: AptitudeTest, clean: dict, code: str, generated: bool) -> Candidate:
    return Candidate(institution_id=test.institution_id, test_id=test.id, department_id=clean["department"].id,
                     full_name=clean["full_name"], email=clean["email"], roll_number=clean["roll_number"],
                     date_of_birth=clean["date_of_birth"], access_code=code, code_generated=generated)


def _commit() -> None:
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()   # two imports at the same moment picked the same roll number / code
        raise ApiError("CONFLICT", "Someone changed this roster at the same time. Please try again.", 409)


# ---------------------------------------------------------------- CSV import
def _header_key(h: str) -> str:
    return "".join(ch for ch in str(h or "").lower() if ch.isalnum())


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):          # Excel on Windows often saves "CSV" as cp1252
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_csv(file_storage, test: AptitudeTest) -> list[tuple[int, dict]]:
    """Uploaded CSV -> [(row number as Excel shows it, {column: value})]. Raises clear errors for a bad file."""
    if file_storage is None or not file_storage.filename:
        raise ApiError("VALIDATION_ERROR", "Choose a CSV file.", 422, {"file": "Choose a CSV file."})
    name = file_storage.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not name.lower().endswith((".csv", ".txt")):
        raise ApiError("UNSUPPORTED_FILE_TYPE", "Upload a .csv file (in Excel: File → Save As → CSV UTF-8).", 415,
                       {"file": "Upload a .csv file."})
    data = file_storage.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise ApiError("FILE_TOO_LARGE", f"The CSV is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB.", 413,
                       {"file": "File is too large."})
    text = _decode(data)
    if not text.strip():
        raise ApiError("EMPTY_FILE", "The CSV file is empty.", 422, {"file": "The file is empty."})
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])

    columns, aliases = {}, {alias: col for col, names in CSV_COLUMNS.items() for alias in names}
    for i, h in enumerate(header):
        col = aliases.get(_header_key(h))
        if col and col not in columns:
            columns[col] = i
    required = [c for c in CSV_REQUIRED if not (c == "department" and len(test.departments()) == 1)]
    missing = [c for c in required if c not in columns]
    if missing:
        names = ", ".join(_LABELS[c] for c in missing)
        raise ApiError("CSV_MISSING_COLUMNS", f"The first row of the CSV must name the columns. Missing: {names}. "
                       "Download the template to see the expected headings.", 422,
                       {"file": f"Missing columns: {names}.", "columns": [_LABELS[c] for c in missing]})

    rows = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(str(c).strip() for c in cells):
            continue                                   # blank line: skipped, not an error
        rows.append((line_no, {col: (cells[i].strip() if i < len(cells) else "") for col, i in columns.items()}))
        if len(rows) > MAX_IMPORT_ROWS:
            raise ApiError("TOO_MANY_ROWS", f"A CSV can have at most {MAX_IMPORT_ROWS} candidates. Split the file.", 422,
                           {"file": f"At most {MAX_IMPORT_ROWS} rows."})
    if not rows:
        raise ApiError("EMPTY_FILE", "The CSV has headings but no candidates.", 422, {"file": "No candidate rows."})
    return rows


def import_csv(user: User, test_id, file_storage, dry_run: bool = False) -> dict:
    test = published_test(user.institution_id, test_id)
    rows = read_csv(file_storage, test)

    seen_rolls, seen_codes, reserved = {}, {}, set()
    to_add, problems, generated = [], [], 0
    for line_no, raw in rows:
        clean, errors = clean_fields(test, raw)
        issues = list(errors.values())
        roll_key = clean["roll_number"].lower()
        if roll_key and "roll_number" not in errors:
            if roll_key in seen_rolls:
                issues.append(f"Duplicate roll number {clean['roll_number']} (also row #{seen_rolls[roll_key]}).")
            else:
                seen_rolls[roll_key] = line_no
        code = clean["access_code"]
        if code and "access_code" not in errors:
            if code in seen_codes:
                issues.append(f"Duplicate access code (also row #{seen_codes[code]}).")
            else:
                seen_codes[code] = line_no
        if issues:
            problems.append({"row": line_no, "full_name": clean["full_name"] or raw.get("full_name", ""),
                             "roll_number": clean["roll_number"], "issues": issues})
            continue
        to_add.append(clean)

    reserved.update(seen_codes)
    for clean in to_add:
        if clean["access_code"]:
            code, was_generated = clean["access_code"], False
        else:
            code, was_generated = new_code(reserved), True
            reserved.add(code)
            generated += 1
        if not dry_run:
            db.session.add(_new_candidate(test, clean, code, was_generated))
    if not dry_run:
        _commit()

    return {"test_id": test.id, "dry_run": dry_run, "total_rows": len(rows),
            ("would_import" if dry_run else "imported"): len(to_add), "codes_generated": generated,
            "error_count": len(problems), "errors": problems,
            "roster_total": Candidate.query.filter_by(test_id=test.id).count()}


def template_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_TEMPLATE_HEADER)
    w.writerow(["Ahmed Raza", "ahmed.raza@example.com", "PE-2026-014", "", "2008-03-14", "Pre-Engineering"])
    w.writerow(["Sana Fatima", "sana.fatima@example.com", "PM-2026-091", "NED7Q4K2", "02/07/2007", "Pre-Medical"])
    return out.getvalue()


def export_csv(institution_id: int, test_id) -> tuple[str, str]:
    """The roster with access codes, for printing test slips. Returns (filename, csv text)."""
    test = published_test(institution_id, test_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["name", "email", "roll number", _term(test).lower(), "access code", "date of birth"])
    for c in Candidate.query.filter_by(test_id=test.id).order_by(Candidate.roll_number).all():
        w.writerow([c.full_name, c.email, c.roll_number, c.department.name, display_code(c.access_code),
                    c.date_of_birth.isoformat()])
    safe = "".join(ch if ch.isalnum() else "-" for ch in test.name).strip("-")[:60] or "test"
    return f"roster-{safe}.csv", out.getvalue()


# ---------------------------------------------------------------- add / correct / new code / remove
def _department_by_id(test: AptitudeTest, raw, errors: dict):
    try:
        dept_id = int(raw)
    except (TypeError, ValueError):
        errors["department_id"] = f"Choose a {_term(test).lower()}."
        return None
    dept = next((d for d in test.departments() if d.id == dept_id), None)
    if dept is None:
        errors["department_id"] = f"That {_term(test).lower()} is not part of this test."
    return dept


def _json_errors(errors: dict) -> dict:
    return {("department_id" if k == "department" else k): v for k, v in errors.items()}


def add_candidate(user: User, test_id, data: dict) -> Candidate:
    test = published_test(user.institution_id, test_id)
    pre = {}
    dept = _department_by_id(test, data.get("department_id"), pre)
    clean, errors = clean_fields(test, data, department=dept or test.departments()[0])
    errors.update(pre)
    raise_if(_json_errors(errors))
    code = clean["access_code"] or new_code()
    c = _new_candidate(test, clean, code, generated=not clean["access_code"])
    db.session.add(c)
    _commit()
    return c


def update_candidate(institution_id: int, candidate_id: int, data: dict) -> Candidate:
    """Correct a candidate's details. The access code is changed only with new-code (so it can't be typed by mistake)."""
    c = get_candidate(institution_id, candidate_id)
    test = c.test
    pre = {}
    dept = _department_by_id(test, data.get("department_id", c.department_id), pre)
    clean, errors = clean_fields(test, {**data, "access_code": None}, department=dept or c.department, candidate=c)
    errors.update(pre)
    raise_if(_json_errors(errors))
    if clean["department"].id != c.department_id:
        _refuse_if_started(c, "change their field / department (their paper is already built)")
    c.full_name, c.email, c.roll_number = clean["full_name"], clean["email"], clean["roll_number"]
    c.date_of_birth, c.department_id = clean["date_of_birth"], clean["department"].id
    _commit()
    return c


def regenerate_code(institution_id: int, candidate_id: int) -> Candidate:
    """A lost or leaked slip: the old code stops working immediately."""
    c = get_candidate(institution_id, candidate_id)
    c.access_code, c.code_generated = new_code(), True
    _commit()
    return c


def delete_candidate(institution_id: int, candidate_id: int) -> None:
    c = get_candidate(institution_id, candidate_id)
    _refuse_if_started(c, "remove them (their answers are kept)")
    db.session.delete(c)
    db.session.commit()
