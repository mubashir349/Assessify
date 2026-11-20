"""Phase 5 business rules: the candidate roster of a published test, CSV import and access codes.

Every query is filtered by the signed-in admin's institution_id (from the login, never from the request), so another
institution's test or candidate id gives 404. A roster only exists for a PUBLISHED test (its fields are locked).

CSV import is "import what is valid, report the rest": good rows are saved in one transaction, every bad row comes
back with its row number and a reason, so nothing is dropped silently. dry_run=1 checks the file without saving.

Phase 9 makes the import lenient, because university lists are incomplete:
  * only a name column is required, plus at least one of email / phone / roll number (each row must fill one);
  * headers are matched loosely ("Student Name", "Gmail", "Mobile", "Reg No" ...) and unknown columns are ignored;
  * small mistakes are fixed (spaces, case, phone formats, Excel date numbers);
  * a row without a date of birth gets a 6-digit PIN as its second factor;
  * hard errors only where the result could be wrong: no name, no identifier, a blank roll number in a file that has
    a roll number column, a duplicate roll number / email / code, an unknown or missing field, a date that is not
    a date. Things worth a look (same name twice, a date that could be day/month or month/day) are warnings: the
    row is still imported;
  * a row that is already on the roster (same roll number, or same email / phone and same name) is skipped, so the
    same file can be uploaded again after fixing a few rows.
"""
import csv
import difflib
import io
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.common.errors import ApiError
from app.common.utils import iso
from app.common.validation import EMAIL_RE, raise_if
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import (CODE_ALPHABET, CODE_GROUP, CODE_GROUPS, CODE_MAX_LEN, CODE_MIN_LEN, CSV_COLUMNS,
                                  CSV_IDENTIFIERS, CSV_TEMPLATE_HEADER, DOB_FORMATS, MAX_CSV_BYTES, MAX_IMPORT_ROWS,
                                  PIN_LENGTH, Candidate)
from app.models.department import Department
from app.models.institution import Institution
from app.models.user import User

PER_PAGE_DEFAULT, PER_PAGE_MAX = 50, 200
_LABELS = {"full_name": "name", "email": "email", "phone": "phone", "roll_number": "roll number",
           "access_code": "access code", "date_of_birth": "date of birth", "department": "field"}
# Cells people type when they have no value. Treated as empty.
_PLACEHOLDERS = {"-", "--", "---", ".", "n/a", "na", "n.a", "n.a.", "none", "nil", "null", "not available", "#n/a", "?"}
CSV_RISKY_START = ("=", "+", "-", "@", "\t", "\r")


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


def new_pin() -> str:
    """6 random digits, never starting with 0 (Excel drops a leading 0 when it opens the CSV)."""
    return secrets.choice("123456789") + "".join(secrets.choice("0123456789") for _ in range(PIN_LENGTH - 1))


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


CANDIDATE_STATUSES = ("Active", "Inactive", "Pending")


def _candidate_status(raw, default="Active") -> str:
    value = default if raw is None else str(raw).strip()
    if value not in CANDIDATE_STATUSES:
        raise ApiError("VALIDATION_ERROR", "Choose Active, Inactive or Pending.", 422,
                       {"status": "Choose Active, Inactive or Pending."})
    return value


def get_candidate(institution_id: int, candidate_id: int) -> Candidate:
    c = Candidate.query.filter_by(id=candidate_id, institution_id=institution_id, is_deleted=False).first()
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
    q = Candidate.query.filter_by(test_id=test.id, is_deleted=False)
    status = (args.get("status") or "").strip()
    if status:
        if status not in CANDIDATE_STATUSES:
            raise ApiError("BAD_REQUEST", "status must be Active, Inactive or Pending.", 400)
        q = q.filter(Candidate.status == status)
    if args.get("department_id"):
        try:
            q = q.filter(Candidate.department_id == int(args["department_id"]))
        except ValueError:
            raise ApiError("BAD_REQUEST", "department_id must be a number.", 400)
    search = (args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Candidate.full_name.ilike(like), Candidate.roll_number.ilike(like),
                         Candidate.email.ilike(like), Candidate.phone.ilike(like)))
    page, per_page = _page_args(args)
    p = q.order_by(Candidate.roll_number, Candidate.full_name, Candidate.id).paginate(page=page, per_page=per_page, error_out=False)

    counts = dict(db.session.query(Candidate.department_id, func.count(Candidate.id))
                  .filter(Candidate.test_id == test.id, Candidate.is_deleted == False)
                  .group_by(Candidate.department_id).all())
    total = sum(counts.values())
    logged_in = Candidate.query.filter(Candidate.test_id == test.id, Candidate.is_deleted == False,
                                       Candidate.login_count > 0).count()
    status_counts = dict(db.session.query(Candidate.status, func.count(Candidate.id))
                         .filter(Candidate.test_id == test.id, Candidate.is_deleted == False)
                         .group_by(Candidate.status).all())
    return {"items": [serialise(c) for c in p.items], "page": p.page, "per_page": p.per_page, "total": p.total,
            "pages": p.pages,
            "summary": {"total": total, "logged_in": logged_in,
                        "status_counts": {status: status_counts.get(status, 0) for status in CANDIDATE_STATUSES},
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
            .filter(Candidate.institution_id == institution_id, Candidate.is_deleted == False)
            .group_by(Candidate.test_id).all())
    return {str(t): n for t, n in rows}


# ---------------------------------------------------------------- one candidate's fields
def _blank(raw) -> bool:
    return str(raw or "").strip().lower() in _PLACEHOLDERS or not str(raw or "").strip()


def _text(raw) -> str:
    """Trimmed cell text; placeholders such as "-" or "N/A" count as empty. A leading ' (added by our own export so
    Excel does not run the cell as a formula) is removed."""
    if _blank(raw):
        return ""
    value = " ".join(str(raw).split())
    if value.startswith("'") and value[1:2] in CSV_RISKY_START:
        value = value[1:]
    if value.startswith('="') and value.endswith('"'):        # Excel's ="0300..." trick to keep a leading zero
        value = value[2:-1]
    return value


def _excel_serial(value: str) -> date | None:
    """Excel shows a date column as numbers (39156) when the cell format is lost."""
    if value.isdigit() and 10000 <= int(value) <= 60000:
        return date(1899, 12, 30) + timedelta(days=int(value))
    return None


def parse_dob(raw) -> date | None:
    value = _text(raw)
    if not value:
        return None
    serial = _excel_serial(value)
    if serial:
        return serial
    if " " in value and ":" in value:             # "2007-07-02 00:00:00" from a spreadsheet date cell
        value = value.split(" ", 1)[0]
    for fmt in DOB_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


def _dob_is_ambiguous(raw) -> bool:
    """03/04/2007 could be 3 April or 4 March. We read day first (the Pakistani order) but say so."""
    m = _NUMERIC_DATE.match(_text(raw))
    return bool(m) and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2)


def _norm(s: str) -> str:
    return " ".join(str(s or "").split()).lower()


def _match_department(test: AptitudeTest, raw: str) -> tuple[Department | None, str | None]:
    depts = test.departments()
    if not _text(raw):
        if len(depts) == 1:                      # a one-field test (e.g. a general test) needs no field column
            return depts[0], None
        return None, f"{_term(test)} is required (this test has: " + ", ".join(d.name for d in depts) + ")."
    by_name = {_norm(d.name): d for d in depts}
    dept = by_name.get(_norm(raw)) or {_header_key(d.name): d for d in depts}.get(_header_key(raw))
    if dept:                                     # "pre engineering" / "PreEngineering" = "Pre-Engineering"
        return dept, None
    guess = difflib.get_close_matches(_norm(raw), list(by_name), n=1, cutoff=0.6)
    hint = f' (did you mean "{by_name[guess[0]].name}"?)' if guess else \
        " (this test has: " + ", ".join(d.name for d in depts) + ")"
    return None, f'{_term(test)} "{str(raw).strip()}" is not part of this test{hint}.'


def _term(test: AptitudeTest) -> str:
    return "Field" if test.level == "Undergraduate" else "Department"


def _clean_name(raw) -> tuple:
    name = _text(raw)
    if name and (name.isupper() or name.islower()):
        name = " ".join(w[:1].upper() + w[1:].lower() for w in name.split())   # AHMED RAZA -> Ahmed Raza
    if not name:
        return name, "Name is required."
    if not 2 <= len(name) <= 150:
        return name, "Name must be 2-150 characters."
    return name, None


def _clean_email(raw) -> tuple:
    email = "".join(_text(raw).split()).lower()
    if email.startswith("mailto:"):
        email = email[7:]
    if not email:
        return None, None
    if len(email) > 255 or not EMAIL_RE.match(email):
        return email, f'Email "{email}" is not valid.'
    return email, None


_PHONE_CHARS = set("0123456789 +-().")


def normalize_phone(raw) -> tuple[str | None, str | None]:
    """0300-1234567, +92 300 1234567, 923001234567 and 3001234567 (Excel dropped the 0) -> 03001234567.
    Other countries keep their + and digits."""
    value = _text(raw)
    if not value:
        return None, None
    if value.endswith(".0") and value[:-2].isdigit():        # 3001234567.0 from a number cell
        value = value[:-2]
    if not set(value) <= _PHONE_CHARS:
        return value, f'Phone "{value}" is not a phone number.'
    plus = value.startswith("+") or value.startswith("00")
    digits = "".join(ch for ch in value if ch.isdigit())
    if value.startswith("00"):
        digits = digits[2:]
    if digits.startswith("92") and len(digits) == 12:          # Pakistan, written with the country code
        digits, plus = "0" + digits[2:], False
    elif not plus and len(digits) == 10 and digits.startswith("3"):
        digits = "0" + digits
    if not 7 <= len(digits) <= 15:
        return value, f'Phone "{value}" must have 7-15 digits.'
    return ("+" if plus else "") + digits, None


def _clean_roll(raw, required: bool) -> tuple:
    roll = _text(raw)
    if not roll:
        return None, ("Roll number is missing (the file has a roll number column)." if required else None)
    if len(roll) > 50:
        return roll, "Roll number must be at most 50 characters."
    return roll, None


def _clean_dob(raw) -> tuple:
    """(date or None, error, warning). Empty is fine: the candidate gets a PIN instead."""
    dob_raw = _text(raw)
    if not dob_raw:
        return None, None, None
    dob = parse_dob(dob_raw)
    if dob is None:
        return None, f'Date of birth "{dob_raw}" is not a date (use DD/MM/YYYY or YYYY-MM-DD, or leave it empty).', None
    if dob.year < 1900 or dob >= date.today():
        return None, f'Date of birth "{dob_raw}" is not realistic.', None
    warning = f'Date of birth "{dob_raw}" was read as {dob.strftime("%d %B %Y")} (day first).' \
        if _dob_is_ambiguous(dob_raw) else None
    return dob, None, warning


def _clean_code(code_raw) -> tuple:
    if _blank(code_raw):
        return None, None
    code = canonical_code(code_raw)
    if not CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN:
        return code, f"Access code must be {CODE_MIN_LEN}-{CODE_MAX_LEN} letters or digits."
    if _code_taken(code):
        return code, f"Access code {str(code_raw).strip()} is already in use. Leave it empty to get one generated."
    return code, None


def clean_fields(test: AptitudeTest, raw: dict, *, department=None, roll_required: bool = False) -> tuple[dict, dict, list]:
    """Validates one candidate on its own (no roster or file checks). `department` is an already-matched Department
    or None (then raw["department"] is a name). Returns (clean, errors {field: message}, warnings [message])."""
    errors, clean, warnings = {}, {}, []

    def keep(field_name, value, error):
        clean[field_name] = value
        if error:
            errors[field_name] = error

    keep("full_name", *_clean_name(raw.get("full_name")))
    keep("email", *_clean_email(raw.get("email")))
    keep("phone", *normalize_phone(raw.get("phone")))
    keep("roll_number", *_clean_roll(raw.get("roll_number"), roll_required))
    dob, dob_error, dob_warning = _clean_dob(raw.get("date_of_birth"))
    keep("date_of_birth", dob, dob_error)
    if dob_warning:
        warnings.append(dob_warning)
    if department is None:
        department, msg = _match_department(test, raw.get("department"))
        if msg:
            errors["department"] = msg
    clean["department"] = department
    keep("access_code", *_clean_code(raw.get("access_code")))
    has_id = any(clean.get(k) for k in CSV_IDENTIFIERS) or any(k in errors for k in CSV_IDENTIFIERS)
    if not has_id:
        errors["identifier"] = "Give at least one of email, phone or roll number, so this person can be told apart."
    return clean, errors, warnings


def _new_candidate(test: AptitudeTest, clean: dict, code: str, generated: bool, pin: str | None,
                   status: str = "Active") -> Candidate:
    return Candidate(institution_id=test.institution_id, test_id=test.id, department_id=clean["department"].id,
                     full_name=clean["full_name"], email=clean["email"], phone=clean["phone"],
                     roll_number=clean["roll_number"], date_of_birth=clean["date_of_birth"], pin=pin,
                     status=status, access_code=code, code_generated=generated)


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


@dataclass
class ParsedCsv:
    header: list[str]
    columns: dict                                  # {column: index in the row}
    rows: list = field(default_factory=list)       # [(row number as Excel shows it, cells, {column: value})]
    file_warnings: list = field(default_factory=list)

    @property
    def roll_required(self) -> bool:
        return "roll_number" in self.columns


def read_csv(file_storage, test: AptitudeTest) -> ParsedCsv:
    """Uploaded CSV or Excel (.xlsx) file -> ParsedCsv. Raises clear errors for a bad file."""
    table = iter(_read_table(file_storage))
    header = [str(h).strip() for h in next(table, [])]
    parsed = ParsedCsv(header=header, columns={})
    _map_columns(parsed, test)

    for line_no, cells in enumerate(table, start=2):
        if not any(str(c).strip() for c in cells):
            continue                                   # blank line: skipped, not an error
        parsed.rows.append((line_no, cells, {col: (cells[i].strip() if i < len(cells) else "")
                                              for col, i in parsed.columns.items()}))
        if len(parsed.rows) > MAX_IMPORT_ROWS:
            raise ApiError("TOO_MANY_ROWS", f"A file can have at most {MAX_IMPORT_ROWS} candidates. Split the file.",
                           422, {"file": f"At most {MAX_IMPORT_ROWS} rows."})
    if not parsed.rows:
        raise ApiError("EMPTY_FILE", "The file has headings but no candidates.", 422, {"file": "No candidate rows."})
    _drop_empty_columns(parsed)
    return parsed


def _read_table(file_storage) -> list[list[str]]:
    """Rows of text cells from a .csv / .txt or .xlsx upload."""
    if file_storage is None or not file_storage.filename:
        raise ApiError("VALIDATION_ERROR", "Choose a CSV or Excel file.", 422, {"file": "Choose a CSV or Excel file."})
    name = file_storage.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if not name.endswith((".csv", ".txt", ".xlsx")):
        hint = " A PDF can't be read reliably: copy its table into Excel and save it as .xlsx or CSV." \
            if name.endswith(".pdf") else ""
        raise ApiError("UNSUPPORTED_FILE_TYPE", "Upload a .csv or .xlsx file." + hint, 415,
                       {"file": "Upload a .csv or .xlsx file." + hint})
    data = file_storage.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise ApiError("FILE_TOO_LARGE", f"The file is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB.", 413,
                       {"file": "File is too large."})
    if name.endswith(".xlsx"):
        return _xlsx_rows(data)
    text = _decode(data)
    if not text.strip():
        raise ApiError("EMPTY_FILE", "The CSV file is empty.", 422, {"file": "The file is empty."})
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _xlsx_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))                     # 3001234567.0 -> 3001234567
    return str(value).strip()


def _xlsx_rows(data: bytes) -> list[list[str]]:
    """The first sheet of an Excel workbook. Dates come out as YYYY-MM-DD, whole numbers without .0."""
    from openpyxl import load_workbook          # imported here: only the import route needs it
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:                            # openpyxl raises many kinds (zip, xml, key) for a broken file
        raise ApiError("UNSUPPORTED_FILE_TYPE", "This Excel file can't be opened. Save it again as .xlsx or CSV.", 415,
                       {"file": "The Excel file can't be opened."})
    try:
        sheet = book.worksheets[0]
        rows = []
        for values in sheet.iter_rows(values_only=True):
            rows.append([_xlsx_cell(v) for v in values])
            if len(rows) > MAX_IMPORT_ROWS + 2:
                break
    finally:
        book.close()
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise ApiError("EMPTY_FILE", "The Excel file is empty.", 422, {"file": "The file is empty."})
    return rows


def _map_columns(parsed: ParsedCsv, test: AptitudeTest) -> None:
    """Fills parsed.columns from the heading row. Only a name column and one identifier column are required."""
    aliases = {alias: col for col, names in CSV_COLUMNS.items() for alias in names}
    ignored = []
    for i, h in enumerate(parsed.header):
        col = aliases.get(_header_key(h))
        if col and col not in parsed.columns:
            parsed.columns[col] = i
        elif h:
            ignored.append(h)
    missing = []
    if "full_name" not in parsed.columns:
        missing.append("name")
    if not any(c in parsed.columns for c in CSV_IDENTIFIERS):
        missing.append("email, phone or roll number (at least one)")
    if "department" not in parsed.columns and len(test.departments()) > 1:
        missing.append(_LABELS["department"])
    if missing:
        names = "; ".join(missing)
        raise ApiError("CSV_MISSING_COLUMNS", f"The first row of the CSV must name the columns. Missing: {names}. "
                       "Download the template to see the expected headings.", 422,
                       {"file": f"Missing columns: {names}.", "columns": missing})
    if ignored:
        parsed.file_warnings.append("These columns were ignored: " + ", ".join(f'"{h}"' for h in ignored) + ".")


def _drop_empty_columns(parsed: ParsedCsv) -> None:
    """A roll number (or other optional) column that is empty in every row is treated as not there at all."""
    for col in ("roll_number", "email", "phone", "date_of_birth", "access_code"):
        if col in parsed.columns and all(_blank(values.get(col)) for _, _, values in parsed.rows):
            del parsed.columns[col]
            for _, _, values in parsed.rows:
                values.pop(col, None)
            if col == "roll_number":
                parsed.file_warnings.append("The roll number column is empty in every row, so it was ignored.")
    if not any(c in parsed.columns for c in CSV_IDENTIFIERS):
        raise ApiError("CSV_MISSING_COLUMNS", "The email, phone and roll number columns are all empty. Fill at least "
                       "one of them so candidates can be told apart.", 422,
                       {"file": "No email, phone or roll number in any row.",
                        "columns": ["email, phone or roll number (at least one)"]})


class _RosterIndex:
    """The test's saved roster, looked up by roll number, email, phone and name (one query, not one per row)."""

    def __init__(self, test: AptitudeTest):
        self.by_roll, self.by_email, self.by_phone, self.names = {}, {}, {}, set()
        for c in Candidate.query.filter_by(test_id=test.id, is_deleted=False).all():
            if c.roll_number:
                self.by_roll[c.roll_number.lower()] = c
            if c.email:
                self.by_email[c.email] = c
            if c.phone:
                self.by_phone.setdefault(c.phone, c)
            self.names.add(_norm(c.full_name))

    def match(self, clean: dict) -> tuple[str, str | None]:
        """("skip", reason) when the row is already on the roster, ("error", message) when it clashes with someone
        else, ("new", None) otherwise."""
        name = _norm(clean["full_name"])
        roll = (clean["roll_number"] or "").lower()
        if roll and roll in self.by_roll:
            other = self.by_roll[roll]
            if _norm(other.full_name) == name:
                return "skip", f"Already on the roster (roll number {other.roll_number})."
            return "error", f"Roll number {clean['roll_number']} already belongs to {other.full_name} on this roster."
        email = clean["email"]
        if email and email in self.by_email:
            other = self.by_email[email]
            if _norm(other.full_name) == name and not roll:
                return "skip", f"Already on the roster (email {email})."
            return "error", f"Email {email} is already used by {other.full_name} on this roster."
        phone = clean["phone"]
        if phone and not roll and not email and phone in self.by_phone and \
                _norm(self.by_phone[phone].full_name) == name:
            return "skip", f"Already on the roster (phone {phone})."
        return "new", None


def _file_duplicates(seen: dict, clean: dict, line_no: int) -> tuple[list, list]:
    """Checks the row against earlier rows of the same file. Returns (errors, warnings).
    The same roll number, email or code twice is an error; the same phone (siblings share one) or name is a warning."""
    errors, warnings = [], []
    checks = (("roll", (clean["roll_number"] or "").lower(), f"Duplicate roll number {clean['roll_number']}", True),
              ("email", clean["email"], f"Duplicate email {clean['email']}", True),
              ("code", clean["access_code"], "Duplicate access code", True),
              ("phone", clean["phone"], f"Same phone {clean['phone']}", False),
              ("name", _norm(clean["full_name"]), "Same name", False))
    for kind, key, message, is_error in checks:
        if not key:
            continue
        bucket = seen.setdefault(kind, {})
        if key not in bucket:
            bucket[key] = line_no
        elif is_error:
            errors.append(f"{message} (also row #{bucket[key]}).")
        else:
            warnings.append(f"{message} as row #{bucket[key]} (check it is a different person).")
    return errors, warnings


def _row_label(clean: dict, raw: dict) -> dict:
    return {"full_name": clean.get("full_name") or raw.get("full_name", ""), "roll_number": clean.get("roll_number")}


def import_csv(user: User, test_id, file_storage, dry_run: bool = False) -> dict:
    test = published_test(user.institution_id, test_id)
    parsed = read_csv(file_storage, test)
    index = _RosterIndex(test)

    seen = {}
    to_add, problems, warned, skipped = [], [], [], []
    for line_no, cells, raw in parsed.rows:
        clean, errors, warnings = clean_fields(test, raw, roll_required=parsed.roll_required)
        if not errors.get("full_name"):
            verdict, message = index.match(clean)
            if verdict == "skip":
                skipped.append({"row": line_no, **_row_label(clean, raw), "reason": message})
                continue
            if verdict == "error":
                errors["roster"] = message
        dup_errors, dup_warnings = _file_duplicates(seen, clean, line_no)
        issues = list(errors.values()) + dup_errors
        if not issues and _norm(clean["full_name"]) in index.names:
            dup_warnings.append("Someone with the same name is already on the roster (check it is a different person).")
        if issues:
            problems.append({"row": line_no, **_row_label(clean, raw), "issues": issues, "cells": cells})
            continue
        if warnings or dup_warnings:
            warned.append({"row": line_no, **_row_label(clean, raw), "issues": warnings + dup_warnings})
        to_add.append(clean)

    generated, pins = _add_candidates(test, to_add, set(seen.get("code", {})), dry_run)
    return {"test_id": test.id, "dry_run": dry_run, "total_rows": len(parsed.rows),
            ("would_import" if dry_run else "imported"): len(to_add), "codes_generated": generated,
            "pins_generated": pins, "error_count": len(problems), "errors": problems,
            "warning_count": len(warned), "warnings": warned, "skipped_count": len(skipped), "skipped": skipped,
            "file_warnings": parsed.file_warnings, "header": parsed.header,
            "columns": sorted(_LABELS[c] for c in parsed.columns),
            "summary": {"login_with_dob": sum(1 for c in to_add if c["date_of_birth"]),
                        "login_with_pin": sum(1 for c in to_add if not c["date_of_birth"]),
                        "missing_email": sum(1 for c in to_add if not c["email"]),
                        "missing_phone": sum(1 for c in to_add if not c["phone"]),
                        "missing_roll": sum(1 for c in to_add if not c["roll_number"])},
            "roster_total": Candidate.query.filter_by(test_id=test.id, is_deleted=False).count()}


def _add_candidates(test: AptitudeTest, to_add: list[dict], reserved: set, dry_run: bool) -> tuple[int, int]:
    """Adds the clean rows (unless dry_run), generating missing codes and PINs. Returns (codes, PINs) generated."""
    generated = pins = 0
    for clean in to_add:
        if clean["access_code"]:
            code, was_generated = clean["access_code"], False
        else:
            code, was_generated = new_code(reserved), True
            reserved.add(code)
            generated += 1
        pin = None if clean["date_of_birth"] else new_pin()
        pins += pin is not None
        if not dry_run:
            db.session.add(_new_candidate(test, clean, code, was_generated, pin))
    if not dry_run:
        _commit()
    return generated, pins


def template_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_TEMPLATE_HEADER)
    w.writerow(["Ahmed Raza", "ahmed.raza@example.com", "0300-1234567", "PE-2026-014", "14/03/2008", "Pre-Engineering"])
    w.writerow(["Sana Fatima", "", "0321-7654321", "PM-2026-091", "", "Pre-Medical"])
    w.writerow(["Bilal Khan", "bilal.khan@example.com", "", "PE-2026-015", "2007-11-02", "Pre-Engineering"])
    return out.getvalue()


def _cell(value) -> str:
    """Spreadsheet-safe text: a cell starting with = + - @ would run as a formula in Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(CSV_RISKY_START) else text


def _ordered(test: AptitudeTest) -> list[Candidate]:
    return (Candidate.query.filter_by(test_id=test.id, is_deleted=False)
            .order_by(Candidate.roll_number, Candidate.full_name, Candidate.id).all())


EXPORT_HEADER = ["name", "roll number", "access code", "login with", "pin", "date of birth", "email", "phone"]


def export_csv(institution_id: int, test_id) -> tuple[str, str]:
    """The whole roster, filled in: access codes, PINs, dates of birth. For the admin and the university.
    Uploading this file again changes nothing (every row is already on the roster)."""
    test = published_test(institution_id, test_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(EXPORT_HEADER + [_term(test).lower()])
    for c in _ordered(test):
        w.writerow([_cell(v) for v in (
            c.full_name, c.roll_number, display_code(c.access_code),
            "date of birth" if c.login_with == "dob" else "PIN", c.pin,
            c.date_of_birth.isoformat() if c.date_of_birth else "", c.email, c.phone, c.department.name)])
    safe = "".join(ch if ch.isalnum() else "-" for ch in test.name).strip("-")[:60] or "test"
    return f"roster-{safe}.csv", out.getvalue()


def slips(institution_id: int, test_id) -> dict:
    """GET /roster/slips - one printable slip per candidate. The date of birth is never printed: it is the part of
    the login that only the candidate knows. A PIN is printed, because the candidate has no other way to learn it."""
    test = published_test(institution_id, test_id)
    sched, inst = test.schedule, db.session.get(Institution, test.institution_id)
    return {"test": {"id": test.id, "name": test.name, "level": test.level, "term": _term(test),
                     "institution": inst.name if inst else "",
                     "schedule": sched.to_dict() if sched else None},
            "slips": [{"id": c.id, "full_name": c.full_name, "roll_number": c.roll_number,
                       "department": c.department.name, "access_code": display_code(c.access_code),
                       "login_with": c.login_with, "pin": c.pin} for c in _ordered(test)]}


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


def _roster_clashes(test: AptitudeTest, clean: dict, errors: dict, candidate: Candidate | None) -> None:
    """Roll number and email must not belong to someone else on this test's roster."""
    def taken(column, value):
        q = Candidate.query.filter(Candidate.test_id == test.id, Candidate.is_deleted == False,
                                   func.lower(column) == value.lower())
        if candidate is not None:
            q = q.filter(Candidate.id != candidate.id)
        return q.first()

    if clean["roll_number"] and "roll_number" not in errors:
        other = taken(Candidate.roll_number, clean["roll_number"])
        if other:
            errors["roll_number"] = f"Roll number {clean['roll_number']} is already on this test's roster ({other.full_name})."
    if clean["email"] and "email" not in errors:
        other = taken(Candidate.email, clean["email"])
        if other:
            errors["email"] = f"Email {clean['email']} is already used by {other.full_name} on this roster."


def _form_errors(test: AptitudeTest, data: dict, dept, candidate: Candidate | None) -> tuple[dict, dict]:
    clean, errors, _ = clean_fields(test, data, department=dept or test.departments()[0])
    _roster_clashes(test, clean, errors, candidate)
    if "identifier" in errors:
        errors["email"] = errors.pop("identifier")      # the form shows it under the first identifier box
    return clean, _json_errors(errors)


def add_candidate(user: User, test_id, data: dict) -> Candidate:
    test = published_test(user.institution_id, test_id)
    pre = {}
    dept = _department_by_id(test, data.get("department_id"), pre)
    clean, errors = _form_errors(test, data, dept, None)
    errors.update(pre)
    try:
        status = _candidate_status(data.get("status"), "Active")
    except ApiError as exc:
        errors.update(exc.details or {"status": exc.message})
        status = "Active"
    raise_if(errors)
    code = clean["access_code"] or new_code()
    c = _new_candidate(test, clean, code, generated=not clean["access_code"],
                       pin=None if clean["date_of_birth"] else new_pin(), status=status)
    db.session.add(c)
    _commit()
    return c


def update_candidate(institution_id: int, candidate_id: int, data: dict) -> Candidate:
    """Correct a candidate's details. The access code is changed only with new-code (so it can't be typed by mistake).
    Adding a date of birth switches the login to it (the PIN is dropped); removing it gives the candidate a PIN."""
    c = get_candidate(institution_id, candidate_id)
    test = c.test
    pre = {}
    dept = _department_by_id(test, data.get("department_id", c.department_id), pre)
    clean, errors = _form_errors(test, {**data, "access_code": None}, dept or c.department, c)
    errors.update(pre)
    raise_if(errors)
    if clean["department"].id != c.department_id:
        _refuse_if_started(c, "change their field / department (their paper is already built)")
    c.full_name, c.email, c.phone, c.roll_number = clean["full_name"], clean["email"], clean["phone"], clean["roll_number"]
    c.date_of_birth, c.department_id = clean["date_of_birth"], clean["department"].id
    c.status = _candidate_status(data.get("status"), c.status)
    if c.date_of_birth:
        c.pin = None
    elif not c.pin:
        c.pin = new_pin()
    _commit()
    return c


def regenerate_code(institution_id: int, candidate_id: int) -> Candidate:
    """A lost or leaked slip: the old code stops working immediately. A PIN was on the same slip, so it is
    replaced too."""
    c = get_candidate(institution_id, candidate_id)
    c.access_code, c.code_generated = new_code(), True
    if c.pin:
        c.pin = new_pin()
    _commit()
    return c


def delete_candidate(institution_id: int, candidate_id: int) -> None:
    """Soft-delete from the active roster. Attempts, answers and result history remain linked and untouched."""
    c = get_candidate(institution_id, candidate_id)
    c.is_deleted = True
    c.status = "Inactive"
    from app.common.utils import utcnow
    c.deleted_at = utcnow()
    _commit()
