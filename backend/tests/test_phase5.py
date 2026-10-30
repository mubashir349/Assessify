"""Phase 5 - candidate roster (CSV import, access codes) and candidate login."""
import io
from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.candidate import Candidate
from app.models.institution import Institution
from tests.test_phase2 import DEPT, make_admin
from tests.test_phase4 import FIXED, add_questions, row

PREMED = {"name": "Pre-Medical", "level": "Undergraduate", "mode": "field", "subjects": ["Biology", "Chemistry"]}
HEADER = "name,email,roll number,access code,date of birth,field\n"
GOOD = HEADER + (
    "Ahmed Raza,ahmed@mail.com,PE-001,,2008-03-14,Pre-Engineering\n"
    "Sana Fatima,sana@mail.com,PM-001,NED7Q4K2,02/07/2007,pre-medical\n"
)


def make_test(app, c, *, publish=True, name="Undergraduate Admission Test"):
    """Pre-Engineering + Pre-Medical test with enough approved questions, published by default."""
    eng = c.post("/api/v1/departments", json=DEPT).get_json()["data"]["department"]["id"]
    med = c.post("/api/v1/departments", json=PREMED).get_json()["data"]["department"]["id"]
    add_questions(app, eng, "Mathematics", 3)
    add_questions(app, med, "Biology", 3)
    body = {"name": name, "level": "Undergraduate", "schedule": FIXED,
            "compositions": [{"department_id": eng, "rows": [row(count=2)]},
                             {"department_id": med, "rows": [row(subject="Biology", count=2)]}]}
    test = c.post("/api/v1/tests", json=body).get_json()["data"]["test"]
    if publish:
        assert c.post(f"/api/v1/tests/{test['id']}/publish").status_code == 200
    return test["id"], eng, med


@pytest.fixture()
def admin(app):
    c = make_admin(app)
    test_id, eng, med = make_test(app, c)
    return c, test_id, eng, med


def upload(c, test_id, text, *, filename="roster.csv", dry_run=False, encoding="utf-8"):
    data = {"test_id": str(test_id), "file": (io.BytesIO(text.encode(encoding)), filename)}
    if dry_run:
        data["dry_run"] = "1"
    return c.post("/api/v1/roster/import", data=data, content_type="multipart/form-data")


def roster(c, test_id, **params):
    r = c.get("/api/v1/roster", query_string={"test_id": test_id, **params})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def cand_login(app, code, dob):
    return app.test_client().post("/api/v1/candidate/login", json={"access_code": code, "date_of_birth": dob})


# ---------------------------------------------------------------- access + roster belongs to a published test
def test_roster_requires_institution_admin(client, app):
    assert client.get("/api/v1/roster?test_id=1").status_code == 401
    client.post("/api/v1/auth/login", json={"email": "root@assessai.com", "password": "SuperSecret123"})
    assert client.get("/api/v1/roster?test_id=1").status_code == 403


def test_roster_needs_a_published_test(app):
    c = make_admin(app)
    test_id, _, _ = make_test(app, c, publish=False)
    r = upload(c, test_id, GOOD)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "TEST_NOT_PUBLISHED"
    assert c.get("/api/v1/roster").status_code == 400                     # test_id is required


def test_other_institutions_test_and_candidates_are_hidden(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    other = make_admin(app, email="admin@fast.edu.pk", name="FAST")
    assert upload(other, test_id, GOOD).status_code == 404
    assert other.get(f"/api/v1/roster?test_id={test_id}").status_code == 404
    cid = roster(c, test_id)["items"][0]["id"]
    assert other.put(f"/api/v1/roster/{cid}", json={"full_name": "X"}).status_code == 404
    assert other.delete(f"/api/v1/roster/{cid}").status_code == 404
    assert other.post(f"/api/v1/roster/{cid}/new-code").status_code == 404


# ---------------------------------------------------------------- CSV import
def test_import_good_csv_generates_missing_codes(app, admin):
    c, test_id, eng, med = admin
    r = upload(c, test_id, GOOD)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()["data"]
    assert (d["imported"], d["error_count"], d["codes_generated"], d["roster_total"]) == (2, 0, 1, 2)
    items = {x["roll_number"]: x for x in roster(c, test_id)["items"]}
    ahmed, sana = items["PE-001"], items["PM-001"]
    assert ahmed["department"]["id"] == eng and sana["department"]["id"] == med   # field matched case-insensitively
    assert ahmed["code_generated"] is True and len(ahmed["access_code"]) == 9 and ahmed["access_code"][4] == "-"
    assert sana["access_code"] == "NED7-Q4K2" and sana["code_generated"] is False
    assert sana["date_of_birth"] == "2007-07-02"                                    # DD/MM/YYYY (Pakistani order)
    assert ahmed["email"] == "ahmed@mail.com"


def test_bad_rows_are_reported_one_by_one_and_good_rows_still_import(app, admin):
    c, test_id, _, _ = admin
    csv_text = HEADER + (
        "Good One,good@mail.com,R-1,,2008-01-01,Pre-Engineering\n"
        "Hassan Ali,hassan@mail.com,R-2,,2008-01-01,Pre-Eng\n"
        "Areeba Khan,areeba@mail.com,R-3,,2007/13/40,Pre-Medical\n"
        "M. Bilal,bilal@mail.com,R-1,,2008-01-01,Pre-Medical\n"
        ",nomail,,,,\n"
        "\n"
        "Future Kid,kid@mail.com,R-5,,2099-01-01,Pre-Medical\n"
    )
    d = upload(c, test_id, csv_text).get_json()["data"]
    assert d["imported"] == 1 and d["total_rows"] == 6 and d["error_count"] == 5
    errs = {e["row"]: " ".join(e["issues"]) for e in d["errors"]}
    assert 'did you mean "Pre-Engineering"' in errs[3]
    assert "2007/13/40" in errs[4]
    assert "Duplicate roll number R-1 (also row #2)" in errs[5]
    assert "Name is required" in errs[6] and "Email" in errs[6] and "Roll number is required" in errs[6]
    assert "not realistic" in errs[8]                                              # blank line 7 was skipped
    assert roster(c, test_id)["total"] == 1


def test_reimporting_the_same_file_does_not_duplicate(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    d = upload(c, test_id, GOOD).get_json()["data"]
    assert d["imported"] == 0 and d["error_count"] == 2
    assert all("already on this test's roster" in " ".join(e["issues"]) or "already in use" in " ".join(e["issues"])
               for e in d["errors"])
    assert roster(c, test_id)["total"] == 2


def test_dry_run_saves_nothing(app, admin):
    c, test_id, _, _ = admin
    d = upload(c, test_id, GOOD, dry_run=True).get_json()["data"]
    assert d["dry_run"] is True and d["would_import"] == 2 and d["roster_total"] == 0
    assert roster(c, test_id)["total"] == 0


def test_supplied_codes_must_be_unique_everywhere(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    other = make_admin(app, email="admin@fast.edu.pk", name="FAST")
    other_test, _, _ = make_test(app, other)
    text = HEADER + ("A Person,a@mail.com,X-1,ned7-q4k2,2008-01-01,Pre-Engineering\n"
                     "B Person,b@mail.com,X-2,ZZZZ1111,2008-01-01,Pre-Engineering\n"
                     "C Person,c@mail.com,X-3,zzzz-1111,2008-01-01,Pre-Engineering\n"
                     "D Person,d@mail.com,X-4,AB1,2008-01-01,Pre-Engineering\n")
    d = upload(other, other_test, text).get_json()["data"]
    errs = {e["row"]: " ".join(e["issues"]) for e in d["errors"]}
    assert "already in use" in errs[2]                       # another institution already has NED7Q4K2
    assert "Duplicate access code (also row #3)" in errs[4]  # same code written differently in one file
    assert "6-20 letters or digits" in errs[5]
    assert d["imported"] == 1


def test_headers_are_flexible_and_excel_files_work(app, admin):
    c, test_id, _, _ = admin
    text = "Full Name;E-mail;Roll No.;DOB;Field / Department\nZoë Ali;zoe@mail.com;R-9;14-Mar-2008;Pre-Medical\n"
    d = upload(c, test_id, "﻿" + text, encoding="utf-8").get_json()["data"]    # BOM + semicolons (Excel)
    assert d["imported"] == 1, d
    d = upload(c, test_id, HEADER + "José Pérez,jose@mail.com,R-10,,2008-01-01,Pre-Medical\n",
               encoding="cp1252").get_json()["data"]
    assert d["imported"] == 1
    names = {x["full_name"] for x in roster(c, test_id)["items"]}
    assert {"Zoë Ali", "José Pérez"} <= names


def test_bad_files_are_refused_clearly(app, admin):
    c, test_id, _, _ = admin
    r = upload(c, test_id, "x", filename="roster.xlsx")
    assert r.status_code == 415
    r = upload(c, test_id, "   ")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "EMPTY_FILE"
    r = upload(c, test_id, "name,email\nA,a@b.co\n")
    assert r.get_json()["error"]["code"] == "CSV_MISSING_COLUMNS"
    assert "roll number" in r.get_json()["error"]["details"]["columns"]
    r = upload(c, test_id, HEADER)
    assert r.get_json()["error"]["code"] == "EMPTY_FILE"
    r = c.post("/api/v1/roster/import", data={"test_id": str(test_id)}, content_type="multipart/form-data")
    assert r.status_code == 422 and "file" in r.get_json()["error"]["details"]


def test_one_field_test_needs_no_field_column(app):
    c = make_admin(app)
    eng = c.post("/api/v1/departments", json=DEPT).get_json()["data"]["department"]["id"]
    add_questions(app, eng, "Mathematics", 3)
    t = c.post("/api/v1/tests", json={"name": "Entry Test", "level": "Undergraduate", "schedule": FIXED,
                                      "compositions": [{"department_id": eng, "rows": [row(count=2)]}]}).get_json()
    tid = t["data"]["test"]["id"]
    c.post(f"/api/v1/tests/{tid}/publish")
    d = upload(c, tid, "name,email,roll number,date of birth\nA B,a@b.co,1,2008-01-01\n").get_json()["data"]
    assert d["imported"] == 1


def test_template_and_export_csv(app, admin):
    c, test_id, _, _ = admin
    r = c.get("/api/v1/roster/template.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert r.get_data(as_text=True).lstrip("﻿").startswith("name,email,roll number,access code,date of birth,field")
    upload(c, test_id, GOOD)
    r = c.get(f"/api/v1/roster/export.csv?test_id={test_id}")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    assert "NED7-Q4K2" in body and "Sana Fatima" in body


# ---------------------------------------------------------------- list, add, correct, new code, delete
def test_list_search_filter_and_summary(app, admin):
    c, test_id, eng, med = admin
    upload(c, test_id, GOOD)
    d = roster(c, test_id)
    assert d["summary"]["total"] == 2 and d["summary"]["logged_in"] == 0
    assert {x["name"]: x["count"] for x in d["summary"]["by_department"]} == {"Pre-Engineering": 1, "Pre-Medical": 1}
    assert [x["full_name"] for x in roster(c, test_id, q="sana")["items"]] == ["Sana Fatima"]
    assert [x["full_name"] for x in roster(c, test_id, q="PE-0")["items"]] == ["Ahmed Raza"]
    assert [x["full_name"] for x in roster(c, test_id, department_id=med)["items"]] == ["Sana Fatima"]
    assert c.get("/api/v1/roster/counts").get_json()["data"]["counts"] == {str(test_id): 2}


def test_add_and_correct_a_candidate(app, admin):
    c, test_id, eng, med = admin
    r = c.post("/api/v1/roster", json={"test_id": test_id, "full_name": "Late Entry", "email": "late@mail.com",
                                       "roll_number": "PE-050", "date_of_birth": "2008-05-05", "department_id": eng})
    assert r.status_code == 201, r.get_json()
    cand = r.get_json()["data"]["candidate"]
    r = c.post("/api/v1/roster", json={"test_id": test_id, "full_name": "Dup", "email": "d@mail.com",
                                       "roll_number": "pe-050", "date_of_birth": "2008-05-05", "department_id": 99999})
    assert r.status_code == 422 and {"roll_number", "department_id"} <= set(r.get_json()["error"]["details"])

    r = c.put(f"/api/v1/roster/{cand['id']}", json={"full_name": "Late Entry Fixed", "email": "late@mail.com",
                                                     "roll_number": "PE-050", "date_of_birth": "14/03/2008",
                                                     "department_id": med, "access_code": "HACKED99"})
    assert r.status_code == 200, r.get_json()
    fixed = r.get_json()["data"]["candidate"]
    assert fixed["full_name"] == "Late Entry Fixed" and fixed["department"]["id"] == med
    assert fixed["date_of_birth"] == "2008-03-14" and fixed["access_code"] == cand["access_code"]  # code not editable here


def test_delete_candidate(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    cid = roster(c, test_id)["items"][0]["id"]
    assert c.delete(f"/api/v1/roster/{cid}").get_json()["data"] == {"deleted": cid}
    assert roster(c, test_id)["total"] == 1


# ---------------------------------------------------------------- candidate login (the done-when demo)
def test_imported_candidate_can_log_in_and_a_wrong_code_is_refused(app, admin):
    c, test_id, _, med = admin
    upload(c, test_id, GOOD)
    r = cand_login(app, "ned7-q4k2", "2007-07-02")          # lower case, with the dash: same code
    assert r.status_code == 200, r.get_json()
    cand = r.get_json()["data"]["candidate"]
    assert cand["full_name"] == "Sana Fatima" and cand["department"]["id"] == med
    assert cand["test"]["id"] == test_id and cand["test"]["schedule"]["timing_mode"] == "fixed"
    assert cand["test"]["subjects"] == ["Biology"] and cand["test"]["question_count"] == 2
    assert "access_code" not in cand and "date_of_birth" not in cand

    r = cand_login(app, "WRNG-CODE", "2007-07-02")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "INVALID_ACCESS_CODE"
    r = cand_login(app, "NED7Q4K2", "2007-02-07")            # right code, wrong date of birth: same message
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "INVALID_ACCESS_CODE"
    assert roster(c, test_id, q="Sana")["items"][0]["login_count"] == 1


def test_candidate_session_and_logout(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    cc = app.test_client()
    assert cc.get("/api/v1/candidate/me").status_code == 401
    assert cc.post("/api/v1/candidate/login", json={"access_code": "NED7Q4K2", "date_of_birth": "2007-07-02"}).status_code == 200
    me = cc.get("/api/v1/candidate/me")
    assert me.status_code == 200 and me.get_json()["data"]["candidate"]["roll_number"] == "PM-001"
    cc.post("/api/v1/candidate/logout")
    assert cc.get("/api/v1/candidate/me").status_code == 401


def test_candidate_and_admin_cookies_never_mix(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    # Same browser: the admin stays signed in after a candidate signs in
    assert c.post("/api/v1/candidate/login", json={"access_code": "NED7Q4K2", "date_of_birth": "2007-07-02"}).status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 200
    assert c.get("/api/v1/candidate/me").status_code == 200
    # A candidate token copied into the admin cookie is refused (not a 500, not someone else's account)
    token = next(ck.value for ck in c._cookies.values() if ck.key == "candidate_token")
    other = app.test_client()
    other.set_cookie("access_token_cookie", token)
    assert other.get("/api/v1/auth/me").status_code == 401
    assert other.get("/api/v1/roster?test_id=1").status_code == 401


def test_validation_and_lockout_after_too_many_wrong_tries(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    r = cand_login(app, "", "")
    assert r.status_code == 422 and {"access_code", "date_of_birth"} <= set(r.get_json()["error"]["details"])
    for _ in range(app.config["CANDIDATE_LOGIN_MAX_FAILS"]):
        assert cand_login(app, "NED7Q4K2", "2000-01-01").status_code == 401
    r = cand_login(app, "NED7Q4K2", "2007-07-02")           # even the right date is refused while locked
    assert r.status_code == 429 and r.get_json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    # other candidates in the same hall (same address) are not locked out by one person's typos
    ahmed = roster(c, test_id, q="Ahmed")["items"][0]
    assert cand_login(app, ahmed["access_code"], "2008-03-14").status_code == 200


def test_new_code_replaces_the_old_one_and_ends_its_session(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    cc = app.test_client()
    cc.post("/api/v1/candidate/login", json={"access_code": "NED7Q4K2", "date_of_birth": "2007-07-02"})
    cid = roster(c, test_id, q="Sana")["items"][0]["id"]
    new = c.post(f"/api/v1/roster/{cid}/new-code").get_json()["data"]["candidate"]["access_code"]
    assert new != "NED7-Q4K2"
    assert cc.get("/api/v1/candidate/me").status_code == 401                # leaked slip's session is over
    assert cand_login(app, "NED7Q4K2", "2007-07-02").status_code == 401
    assert cand_login(app, new, "2007-07-02").status_code == 200


def test_removed_candidate_cannot_continue(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    cc = app.test_client()
    cc.post("/api/v1/candidate/login", json={"access_code": "NED7Q4K2", "date_of_birth": "2007-07-02"})
    cid = roster(c, test_id, q="Sana")["items"][0]["id"]
    c.delete(f"/api/v1/roster/{cid}")
    assert cc.get("/api/v1/candidate/me").status_code == 401


def test_suspended_institution_and_ended_test_refuse_login(app, admin):
    c, test_id, _, _ = admin
    upload(c, test_id, GOOD)
    with app.app_context():
        inst = db.session.get(AptitudeTest, test_id).institution_id
        db.session.get(Institution, inst).status = "suspended"
        db.session.commit()
    r = cand_login(app, "NED7Q4K2", "2007-07-02")
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "INSTITUTION_NOT_ACTIVE"
    with app.app_context():
        db.session.get(Institution, inst).status = "approved"
        sched = db.session.get(AptitudeTest, test_id).schedule
        sched.starts_at, sched.ends_at = datetime(2020, 1, 1, 9), datetime(2020, 1, 1, 11)
        db.session.commit()
    r = cand_login(app, "NED7Q4K2", "2007-07-02")
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "TEST_CLOSED"


def test_access_codes_are_random_and_readable(app, admin):
    c, test_id, _, _ = admin
    lines = "".join(f"P{i},p{i}@mail.com,G-{i},,2008-01-01,Pre-Engineering\n" for i in range(200))
    assert upload(c, test_id, HEADER + lines).get_json()["data"]["codes_generated"] == 200
    with app.app_context():
        codes = [x.access_code for x in Candidate.query.all()]
    assert len(set(codes)) == 200
    assert not any(ch in code for code in codes for ch in "01OIL")
