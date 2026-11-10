"""Phase 9 - lenient roster import: optional email / roll number / date of birth, phone, PIN login, Excel files,
warnings, skipping already-imported rows, the filled-in export and printable slips."""
import io
from datetime import date

import pytest
from openpyxl import Workbook

from app.extensions import db
from app.models.candidate import Candidate
from tests.test_phase2 import make_admin
from tests.test_phase5 import make_test, roster, upload
from tests.test_phase7 import finished, live  # noqa: F401  (pytest fixtures used below)


@pytest.fixture
def admin(app):
    c = make_admin(app)
    test_id, eng, med = make_test(app, c)
    return c, test_id, eng, med


def login(app, code, *, dob=None, pin=None):
    body = {"access_code": code}
    if dob is not None:
        body["date_of_birth"] = dob
    if pin is not None:
        body["pin"] = pin
    return app.test_client().post("/api/v1/candidate/login", json=body)


def by_name(c, test_id) -> dict:
    return {x["full_name"]: x for x in roster(c, test_id, per_page=200)["items"]}


def issues(rows: list, row_no: int) -> str:
    return " ".join(next(r for r in rows if r["row"] == row_no)["issues"])


# ---------------------------------------------------------------- what a row needs
def test_name_and_one_identifier_is_enough(app, admin):
    c, test_id, eng, _ = admin
    text = ("Student Name,Mobile,Program\n"
            "ali hassan,0300-1234567,Pre-Engineering\n"
            "SARA KHAN,+92 321 7654321,Pre-Medical\n"
            "Omar Farooq,3331234567,Pre-Engineering\n")       # Excel dropped the leading 0
    d = upload(c, test_id, text).get_json()["data"]
    assert (d["imported"], d["error_count"], d["pins_generated"]) == (3, 0, 3), d
    assert d["summary"] == {"login_with_dob": 0, "login_with_pin": 3, "missing_email": 3, "missing_phone": 0,
                            "missing_roll": 3}
    people = by_name(c, test_id)
    assert set(people) == {"Ali Hassan", "Sara Khan", "Omar Farooq"}           # ALL CAPS / lower case fixed
    assert people["Ali Hassan"]["phone"] == "03001234567"
    assert people["Sara Khan"]["phone"] == "03217654321"
    assert people["Omar Farooq"]["phone"] == "03331234567"
    ali = people["Ali Hassan"]
    assert ali["roll_number"] is None and ali["email"] is None and ali["date_of_birth"] is None
    assert ali["login_with"] == "pin"
    assert len(ali["pin"]) == 6 and ali["pin"].isdigit() and ali["pin"][0] != "0"


def test_row_without_any_identifier_or_name_is_an_error(app, admin):
    c, test_id, _, _ = admin
    text = ("name,email,phone,field\n"
            "Has Email,has@mail.com,,Pre-Medical\n"
            "Nothing Else,,,Pre-Medical\n"
            ",x@mail.com,,Pre-Medical\n"
            "Placeholder,N/A,-,Pre-Medical\n")
    d = upload(c, test_id, text).get_json()["data"]
    assert d["imported"] == 1
    assert "at least one of email, phone or roll number" in issues(d["errors"], 3)
    assert "Name is required" in issues(d["errors"], 4)
    assert "at least one of email, phone or roll number" in issues(d["errors"], 5)   # N/A and - are empty


def test_file_needs_a_name_and_an_identifier_column(app, admin):
    c, test_id, _, _ = admin
    r = upload(c, test_id, "name,date of birth,field\nA B,2008-01-01,Pre-Medical\n")
    assert r.get_json()["error"]["code"] == "CSV_MISSING_COLUMNS"
    assert "email, phone or roll number (at least one)" in r.get_json()["error"]["details"]["columns"]
    r = upload(c, test_id, "email,field\na@b.co,Pre-Medical\n")
    assert "name" in r.get_json()["error"]["details"]["columns"]


def test_blank_roll_number_is_an_error_only_when_the_file_has_a_roll_column(app, admin):
    c, test_id, _, _ = admin
    text = ("name,email,roll no,field\n"
            "With Roll,a@mail.com,R-1,Pre-Medical\n"
            "No Roll,b@mail.com,,Pre-Medical\n")
    d = upload(c, test_id, text).get_json()["data"]
    assert d["imported"] == 1
    assert "Roll number is missing" in issues(d["errors"], 3)
    # a roll column that is empty in every row counts as no roll column
    d = upload(c, test_id, "name,email,roll no,field\nC One,c@mail.com,,Pre-Medical\nD Two,d@mail.com,,Pre-Medical\n")
    d = d.get_json()["data"]
    assert d["imported"] == 2, d
    assert any("roll number column is empty" in w for w in d["file_warnings"])


def test_many_candidates_without_roll_number_fit_in_one_test(app, admin):
    """SQL Server allows one NULL in a plain unique constraint; the filtered index allows any number."""
    c, test_id, _, _ = admin
    lines = "".join(f"Person {i},p{i}@mail.com,Pre-Medical\n" for i in range(5))
    assert upload(c, test_id, "name,email,field\n" + lines).get_json()["data"]["imported"] == 5
    with app.app_context():
        assert Candidate.query.filter(Candidate.roll_number.is_(None)).count() == 5


# ---------------------------------------------------------------- headers, small fixes, warnings
def test_messy_headers_unknown_columns_and_small_fixes(app, admin):
    c, test_id, eng, med = admin
    text = ("Sr No,Name of Student,Father Name,Gmail,Contact No,Reg No,D.O.B,Group\n"
            "1,  Zainab   Ali ,Ali Raza, Zainab.Ali@Gmail.com ,0300 111 2222,REG-1,39156,Pre-Medical\n"
            "2,Hamza Tariq,Tariq M,mailto:hamza@mail.com,923001112223,REG-2,2007-05-20 00:00:00,pre-engineering\n")
    d = upload(c, test_id, text).get_json()["data"]
    assert d["imported"] == 2, d
    assert any('"Sr No"' in w and '"Father Name"' in w for w in d["file_warnings"])
    people = by_name(c, test_id)
    z, h = people["Zainab Ali"], people["Hamza Tariq"]
    assert z["email"] == "zainab.ali@gmail.com"
    assert z["phone"] == "03001112222"
    assert z["roll_number"] == "REG-1"
    assert z["date_of_birth"] == "2007-03-15"                                # Excel date number 39156
    assert z["department"]["id"] == med
    assert h["email"] == "hamza@mail.com"
    assert h["phone"] == "03001112223"
    assert h["date_of_birth"] == "2007-05-20"
    assert h["department"]["id"] == eng
    assert z["login_with"] == "dob" and z["pin"] is None


def test_warnings_do_not_block_the_row(app, admin):
    c, test_id, _, _ = admin
    text = ("name,email,phone,date of birth,field\n"
            "Ahmed Raza,a1@mail.com,03001234567,03/04/2007,Pre-Medical\n"
            "Ahmed Raza,a2@mail.com,03001234567,2007-01-01,Pre-Medical\n")
    d = upload(c, test_id, text).get_json()["data"]
    assert d["imported"] == 2 and d["error_count"] == 0
    assert d["warning_count"] == 2
    assert "read as 03 April 2007" in issues(d["warnings"], 2)
    w = issues(d["warnings"], 3)
    assert "Same phone 03001234567 as row #2" in w
    assert "Same name as row #2" in w


def test_hard_errors_for_duplicates_and_bad_values(app, admin):
    c, test_id, _, _ = admin
    text = ("name,email,phone,roll number,date of birth,field\n"
            "First,same@mail.com,,R-1,,Pre-Medical\n"
            "Second,same@mail.com,,R-2,,Pre-Medical\n"
            "Third,t@mail.com,,r-1,,Pre-Medical\n"
            "Fourth,f@mail.com,call me,R-4,,Pre-Medical\n"
            "Fifth,v@mail.com,,R-5,31/31/2007,Pre-Medical\n"
            "Sixth,s@mail.com,,R-6,,\n")
    d = upload(c, test_id, text).get_json()["data"]
    assert d["imported"] == 1
    assert "Duplicate email same@mail.com (also row #2)" in issues(d["errors"], 3)
    assert "Duplicate roll number r-1 (also row #2)" in issues(d["errors"], 4)
    assert "is not a phone number" in issues(d["errors"], 5)
    assert "is not a date" in issues(d["errors"], 6)
    assert "Field is required" in issues(d["errors"], 7)
    # the original cells come back so the page can offer an errors.csv to fix and upload again
    assert d["header"][:2] == ["name", "email"]
    assert next(e for e in d["errors"] if e["row"] == 5)["cells"][2] == "call me"


def test_reupload_skips_rows_already_on_the_roster_and_imports_the_fixed_ones(app, admin):
    c, test_id, _, _ = admin
    first = ("name,email,roll number,field\n"
             "Ayesha Noor,ayesha@mail.com,R-1,Pre-Medical\n"
             "Usman Ghani,usman@mail.com,,Pre-Medical\n")
    d = upload(c, test_id, first).get_json()["data"]
    assert (d["imported"], d["error_count"]) == (1, 1)
    fixed = first.replace("usman@mail.com,,", "usman@mail.com,R-2,")
    d = upload(c, test_id, fixed).get_json()["data"]
    assert (d["imported"], d["skipped_count"], d["error_count"]) == (1, 1, 0), d
    assert d["skipped"][0]["row"] == 2
    # same roll number but a different person is not skipped: it is an error
    d = upload(c, test_id, "name,email,roll number,field\nSomeone Else,else@mail.com,R-1,Pre-Medical\n").get_json()["data"]
    assert "already belongs to Ayesha Noor" in issues(d["errors"], 2)
    assert roster(c, test_id)["total"] == 2


def test_dry_run_counts_match_the_real_import(app, admin):
    c, test_id, _, _ = admin
    text = ("name,phone,date of birth,field\n"
            "One Person,03001111111,2008-01-01,Pre-Medical\n"
            "Two Person,03002222222,,Pre-Medical\n"
            "Bad Person,,,Pre-Medical\n")
    pre = upload(c, test_id, text, dry_run=True).get_json()["data"]
    assert (pre["would_import"], pre["error_count"], pre["pins_generated"]) == (2, 1, 1)
    assert roster(c, test_id)["total"] == 0
    done = upload(c, test_id, text).get_json()["data"]
    assert (done["imported"], done["error_count"], done["pins_generated"]) == (2, 1, 1)


# ---------------------------------------------------------------- Excel and other files
def _xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_excel_file_imports(app, admin):
    c, test_id, _, _ = admin
    data = _xlsx([["Student Name", "Mobile", "DOB", "Field"],
                  ["Excel Kid", 3001234567, date(2008, 3, 14), "Pre-Medical"],
                  ["Second Kid", "0321-0000000", None, "Pre-Medical"],
                  [None, None, None, None]])
    r = c.post("/api/v1/roster/import", data={"test_id": str(test_id), "file": (io.BytesIO(data), "list.xlsx")},
               content_type="multipart/form-data")
    d = r.get_json()["data"]
    assert d["imported"] == 2, d
    people = by_name(c, test_id)
    assert people["Excel Kid"]["phone"] == "03001234567"
    assert people["Excel Kid"]["date_of_birth"] == "2008-03-14"
    assert people["Second Kid"]["login_with"] == "pin"


def test_pdf_and_broken_excel_are_refused_with_advice(app, admin):
    c, test_id, _, _ = admin
    r = upload(c, test_id, "%PDF-1.4", filename="list.pdf")
    assert r.status_code == 415
    assert "copy its table into Excel" in r.get_json()["error"]["message"]
    r = upload(c, test_id, "not a zip", filename="list.xlsx")
    assert r.status_code == 415


# ---------------------------------------------------------------- login with date of birth or PIN
def _two_candidates(c, test_id):
    upload(c, test_id, "name,email,date of birth,field\n"
                       "Dob Person,dob@mail.com,2007-07-02,Pre-Medical\n"
                       "Pin Person,pin@mail.com,,Pre-Medical\n")
    return by_name(c, test_id)


def test_pin_and_dob_logins(app, admin):
    c, test_id, _, _ = admin
    people = _two_candidates(c, test_id)
    dob_p, pin_p = people["Dob Person"], people["Pin Person"]
    assert login(app, dob_p["access_code"], dob="2007-07-02").status_code == 200
    r = login(app, pin_p["access_code"], pin=pin_p["pin"])
    assert r.status_code == 200, r.get_json()
    assert "pin" not in r.get_json()["data"]["candidate"]
    # the wrong switch gets the same refusal as a wrong value, so it doesn't reveal which factor a code uses
    wrong_pin = "123456" if pin_p["pin"] != "123456" else "654321"
    for r in (login(app, dob_p["access_code"], pin="123456"),
              login(app, pin_p["access_code"], dob="2007-07-02"),
              login(app, pin_p["access_code"], pin=wrong_pin)):
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "INVALID_ACCESS_CODE"


def test_pin_validation_and_lockout(app, admin):
    c, test_id, _, _ = admin
    pin_p = _two_candidates(c, test_id)["Pin Person"]
    r = login(app, pin_p["access_code"], pin="12")
    assert r.status_code == 422 and "pin" in r.get_json()["error"]["details"]
    r = login(app, pin_p["access_code"])
    assert r.status_code == 422 and "date_of_birth" in r.get_json()["error"]["details"]
    wrong = "111111" if pin_p["pin"] != "111111" else "222222"
    for _ in range(app.config["CANDIDATE_LOGIN_MAX_FAILS"]):
        assert login(app, pin_p["access_code"], pin=wrong).status_code == 401
    assert login(app, pin_p["access_code"], pin=pin_p["pin"]).status_code == 429


def test_new_code_also_replaces_the_pin(app, admin):
    c, test_id, _, _ = admin
    pin_p = _two_candidates(c, test_id)["Pin Person"]
    new = c.post(f"/api/v1/roster/{pin_p['id']}/new-code").get_json()["data"]["candidate"]
    assert new["access_code"] != pin_p["access_code"]
    assert new["pin"] and len(new["pin"]) == 6
    assert login(app, new["access_code"], pin=new["pin"]).status_code == 200


# ---------------------------------------------------------------- add / correct by hand
def test_add_without_dob_gets_a_pin_and_adding_a_dob_switches_to_it(app, admin):
    c, test_id, eng, _ = admin
    r = c.post("/api/v1/roster", json={"test_id": test_id, "full_name": "Walk In", "phone": "0300 9999999",
                                       "department_id": eng})
    assert r.status_code == 201, r.get_json()
    cand = r.get_json()["data"]["candidate"]
    assert cand["login_with"] == "pin" and cand["pin"]
    assert cand["phone"] == "03009999999"
    r = c.put(f"/api/v1/roster/{cand['id']}", json={"full_name": "Walk In", "phone": "03009999999",
                                                     "date_of_birth": "01/02/2008", "department_id": eng})
    fixed = r.get_json()["data"]["candidate"]
    assert fixed["login_with"] == "dob" and fixed["pin"] is None
    r = c.put(f"/api/v1/roster/{cand['id']}", json={"full_name": "Walk In", "phone": "03009999999",
                                                     "date_of_birth": "", "department_id": eng})
    assert r.get_json()["data"]["candidate"]["login_with"] == "pin"
    # nothing to tell them apart -> refused; the message sits under email
    r = c.post("/api/v1/roster", json={"test_id": test_id, "full_name": "Nobody", "department_id": eng})
    assert r.status_code == 422 and "email" in r.get_json()["error"]["details"]
    # email already used by someone else on this test
    c.post("/api/v1/roster", json={"test_id": test_id, "full_name": "Has Mail", "email": "m@mail.com",
                                   "department_id": eng})
    r = c.post("/api/v1/roster", json={"test_id": test_id, "full_name": "Other", "email": "M@mail.com",
                                       "department_id": eng})
    assert r.status_code == 422 and "already used by Has Mail" in r.get_json()["error"]["details"]["email"]


# ---------------------------------------------------------------- export and slips
def test_export_is_the_filled_in_list_and_reuploading_it_changes_nothing(app, admin):
    c, test_id, _, _ = admin
    people = _two_candidates(c, test_id)
    body = c.get(f"/api/v1/roster/export.csv?test_id={test_id}").get_data(as_text=True).lstrip("﻿")
    lines = body.splitlines()
    assert lines[0] == "name,roll number,access code,login with,pin,date of birth,email,phone,field"
    assert any(people["Pin Person"]["pin"] in ln and ",PIN," in ln for ln in lines)
    assert any("2007-07-02" in ln and "date of birth" in ln for ln in lines[1:])
    d = upload(c, test_id, body).get_json()["data"]
    assert (d["imported"], d["skipped_count"], d["error_count"]) == (0, 2, 0), d


def test_slips_never_show_the_date_of_birth(app, admin):
    c, test_id, _, _ = admin
    _two_candidates(c, test_id)
    d = c.get(f"/api/v1/roster/slips?test_id={test_id}").get_json()["data"]
    assert d["test"]["id"] == test_id and d["test"]["institution"]
    slips = {s["full_name"]: s for s in d["slips"]}
    assert slips["Pin Person"]["login_with"] == "pin" and slips["Pin Person"]["pin"]
    assert slips["Dob Person"]["login_with"] == "dob" and slips["Dob Person"]["pin"] is None
    assert all("date_of_birth" not in s for s in d["slips"])
    other = make_admin(app, email="admin@fast.edu.pk", name="FAST")
    assert other.get(f"/api/v1/roster/slips?test_id={test_id}").status_code == 404


# ---------------------------------------------------------------- the done-when demo
def test_done_when_a_messy_50_row_list_imports(app, admin):
    c, test_id, _, _ = admin
    rows = ["Student Name,Gmail,Mobile,Roll No,DOB,Group,Remarks"]
    for i in range(50):
        email = f"s{i}@mail.com" if i % 3 else ""
        phone = f"0300-{1000000 + i}" if i % 2 else ""
        dob = "" if i % 4 == 0 else f"{(i % 28) + 1:02d}/0{(i % 9) + 1}/2007"
        field = "Pre-Medical" if i % 2 else "pre engineering"
        rows.append(f"student {i},{email},{phone},R-{i:03d},{dob},{field},ok")
    rows[10] = rows[10].replace("R-009", "")                  # roll missing -> error
    rows[21] = "Student 20 Copy,x19@mail.com,,R-019,,Pre-Medical,dup"   # duplicate roll -> error
    text = "\n".join(rows) + "\n"
    pre = upload(c, test_id, text, dry_run=True).get_json()["data"]
    assert (pre["would_import"], pre["error_count"]) == (48, 2), pre["errors"]
    done = upload(c, test_id, text).get_json()["data"]
    assert done["imported"] == 48
    assert done["pins_generated"] == pre["pins_generated"] > 0
    assert sorted(e["row"] for e in done["errors"]) == [11, 22]
    with app.app_context():
        rolls = [x.roll_number for x in Candidate.query.filter_by(test_id=test_id).all()]
        assert len(rolls) == len(set(rolls)) == 48
    people = by_name(c, test_id)
    pin_p = next(p for p in people.values() if p["login_with"] == "pin")
    dob_p = next(p for p in people.values() if p["login_with"] == "dob")
    assert login(app, pin_p["access_code"], pin=pin_p["pin"]).status_code == 200
    assert login(app, dob_p["access_code"], dob=dob_p["date_of_birth"]).status_code == 200


# ---------------------------------------------------------------- reports and result emails without an email

def test_candidate_without_email_or_roll_is_shown_as_no_email_and_skipped(app, finished):
    admin, test_id, _ = finished
    with app.app_context():
        c2 = Candidate.query.filter_by(test_id=test_id, roll_number="R-2").one()
        c2.email, c2.roll_number = None, None
        db.session.commit()
    rep = admin.get(f"/api/v1/reports/tests/{test_id}").get_json()["data"]
    assert rep["email"]["counts"]["no_email"] == 1
    no_mail = admin.get(f"/api/v1/reports/tests/{test_id}?email=no_email").get_json()["data"]["candidates"]
    assert [r["full_name"] for r in no_mail] == ["Candidate 2"]
    sent = admin.post(f"/api/v1/reports/tests/{test_id}/send-results", json={}).get_json()["data"]
    assert sent["logged"] == 2 and sent["remaining"] == 0
    assert admin.get(f"/api/v1/reports/tests/{test_id}/export.csv").status_code == 200
    assert admin.get("/api/v1/monitor", query_string={"test_id": test_id, "q": "cand"}).status_code == 200
