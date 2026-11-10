"""Phase 10: institution directory search, email codes (OTP), work-email rules, proof upload, approve -> directory."""
import io
from datetime import timedelta

from app.common import email_rules
from app.extensions import db
from app.models.directory import DirectoryCampus, DirectoryInstitution, EmailOtp
from app.models.institution import Institution
from app.models.user import User
from tests.conftest import SENT_MAIL, SIGNUP, do_signup, email_token, last_code, login

SEND, VERIFY, SIGNUP_URL, SEARCH = "/api/v1/auth/otp/send", "/api/v1/auth/otp/verify", "/api/v1/institutions/signup", "/api/v1/directory/search"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def seed(app):
    with app.app_context():
        ned = DirectoryInstitution(name="NED University of Engineering & Technology", short_name="NED", type="University",
                                   website="https://www.neduet.edu.pk", email_domain="neduet.edu.pk")
        ned.campuses = [DirectoryCampus(campus_name="City Campus", city="Karachi"),
                        DirectoryCampus(campus_name="Thar Campus", city="Mithi")]
        school = DirectoryInstitution(name="Sunrise Grammar School", type="School")     # no known email domain
        school.campuses = [DirectoryCampus(campus_name="Gulshan Campus", city="Karachi")]
        db.session.add_all([ned, school])
        db.session.commit()
        return {c.campus_name: c.id for c in DirectoryCampus.query}, ned.id


def campus_signup(client, campus_id, email="admissions@neduet.edu.pk", **over):
    return do_signup(client, directory_campus_id=campus_id, admin_email=email, institution_name="", institution_type="",
                     city="", website="", **over)


def err(r):
    return r.get_json()["error"]


# ---------- directory search ----------
def test_search_finds_campuses_by_name_short_name_and_city(app, client):
    seed(app)
    items = client.get(SEARCH + "?q=ned").get_json()["data"]["items"]
    assert [i["label"] for i in items] == ["NED University of Engineering & Technology · City Campus, Karachi",
                                           "NED University of Engineering & Technology · Thar Campus, Mithi"]
    assert items[0]["type"] == "University" and items[0]["website"] == "https://www.neduet.edu.pk"
    assert items[0]["email_domain"] == "neduet.edu.pk" and items[0]["registered"] is False
    assert [i["campus_name"] for i in client.get(SEARCH + "?q=ned mithi").get_json()["data"]["items"]] == ["Thar Campus"]
    assert len(client.get(SEARCH + "?q=karachi").get_json()["data"]["items"]) == 2
    assert client.get(SEARCH + "?q=n").get_json()["data"]["items"] == []           # too short
    assert client.get(SEARCH + "?q=%25").get_json()["data"]["items"] == []         # % is a literal, not "anything"


def test_search_marks_registered_campus(app, client):
    ids, _ = seed(app)
    assert campus_signup(client, ids["City Campus"]).status_code == 201
    items = {i["campus_name"]: i for i in client.get(SEARCH + "?q=ned").get_json()["data"]["items"]}
    assert items["City Campus"]["registered"] is True and items["Thar Campus"]["registered"] is False


# ---------- email codes ----------
def test_code_is_emailed_hashed_and_verifies_once(app, client):
    r = client.post(SEND, json={"email": "Admissions@NED.edu.pk"})
    assert r.status_code == 200 and r.get_json()["data"]["sent_to"] == "admissions@ned.edu.pk"
    code = last_code("admissions@ned.edu.pk")
    assert SENT_MAIL[-1]["subject"] == "Your Assessify verification code"
    with app.app_context():
        row = EmailOtp.query.one()
        assert code not in row.code_hash and len(row.code_hash) == 64
    r = client.post(VERIFY, json={"email": "admissions@ned.edu.pk", "code": code})
    assert r.status_code == 200 and r.get_json()["data"]["email_token"]
    assert client.post(VERIFY, json={"email": "admissions@ned.edu.pk", "code": code}).status_code == 400   # used up


def test_wrong_codes_lock_after_five_tries(client):
    client.post(SEND, json={"email": "a@ned.edu.pk"})
    code = last_code("a@ned.edu.pk")
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3, 2, 1):
        r = client.post(VERIFY, json={"email": "a@ned.edu.pk", "code": wrong})
        assert err(r)["code"] == "OTP_WRONG" and f"{left} " in err(r)["message"]
    assert err(client.post(VERIFY, json={"email": "a@ned.edu.pk", "code": wrong}))["code"] == "OTP_LOCKED"
    assert err(client.post(VERIFY, json={"email": "a@ned.edu.pk", "code": code}))["code"] == "OTP_LOCKED"   # even right


def test_expired_code_refused(app, client):
    client.post(SEND, json={"email": "a@ned.edu.pk"})
    with app.app_context():
        row = EmailOtp.query.one()
        row.expires_at -= timedelta(minutes=11)
        db.session.commit()
    assert err(client.post(VERIFY, json={"email": "a@ned.edu.pk", "code": last_code("a@ned.edu.pk")}))["code"] == "OTP_EXPIRED"


def test_resend_waits_60_seconds_and_five_per_hour(app, client):
    assert client.post(SEND, json={"email": "a@ned.edu.pk"}).status_code == 200
    r = client.post(SEND, json={"email": "a@ned.edu.pk"})
    assert r.status_code == 429 and err(r)["code"] == "OTP_TOO_SOON"
    for _ in range(4):
        with app.app_context():
            for row in EmailOtp.query:
                row.created_at -= timedelta(seconds=61)
            db.session.commit()
        assert client.post(SEND, json={"email": "a@ned.edu.pk"}).status_code == 200
    with app.app_context():
        for row in EmailOtp.query:
            row.created_at -= timedelta(seconds=61)
        db.session.commit()
    assert err(client.post(SEND, json={"email": "a@ned.edu.pk"}))["code"] == "TOO_MANY_ATTEMPTS"


def test_send_refuses_bad_taken_and_dead_domains(app, client, monkeypatch):
    assert client.post(SEND, json={"email": "nope"}).status_code == 422
    assert do_signup(client).status_code == 201
    assert err(client.post(SEND, json={"email": SIGNUP["admin_email"]}))["code"] == "EMAIL_TAKEN"
    monkeypatch.setattr(email_rules, "accepts_mail", lambda d: False)
    r = client.post(SEND, json={"email": "x@no-such-college.pk"})
    assert r.status_code == 422 and err(r)["code"] == "EMAIL_DOMAIN_INVALID"
    monkeypatch.setattr(email_rules, "accepts_mail", lambda d: None)                 # DNS unreachable: allowed
    assert client.post(SEND, json={"email": "x@no-such-college.pk"}).status_code == 200


# ---------- signup needs the verified email ----------
def test_signup_without_or_with_wrong_token_refused(client):
    r = client.post(SIGNUP_URL, json=SIGNUP)
    assert r.status_code == 422 and err(r)["code"] == "EMAIL_NOT_VERIFIED"
    other = email_token(client, "someone@else.edu.pk")
    r = client.post(SIGNUP_URL, json={**SIGNUP, "email_token": other})                # token of another email
    assert err(r)["code"] == "EMAIL_NOT_VERIFIED"
    r = client.post(SIGNUP_URL, json={**SIGNUP, "email_token": "forged.token"})
    assert err(r)["code"] == "EMAIL_NOT_VERIFIED"


def test_one_verification_makes_one_account(app, client):
    token = email_token(client, "a@ned.edu.pk")
    assert do_signup(client, admin_email="a@ned.edu.pk", email_token=token).status_code == 201
    with app.app_context():
        User.query.filter_by(email="a@ned.edu.pk").delete()
        db.session.commit()
    r = do_signup(client, admin_email="a@ned.edu.pk", institution_name="Second", email_token=token)
    assert err(r)["code"] == "EMAIL_NOT_VERIFIED"


def test_admin_has_no_phone_or_designation(app, client):
    r = do_signup(client, admin_phone="0300 1234567", admin_designation="Registrar")   # extra fields are ignored
    admin = r.get_json()["data"]["institution"]["admin"]
    assert admin == {"full_name": SIGNUP["admin_name"], "email": "admissions@ned.edu.pk"}
    assert not hasattr(User, "phone") and not hasattr(User, "designation")


# ---------- work-email rules ----------
def test_free_email_refused_unless_no_official_email(client):
    r = do_signup(client, admin_email="ayesha.khan@gmail.com")
    assert r.status_code == 422 and "personal email" in err(r)["details"]["admin_email"]
    r = do_signup(client, admin_email="ayesha.khan@gmail.com", no_official_email=True)    # ticked, but no proof
    assert r.status_code == 422 and "proof" in err(r)["details"]


def test_directory_campus_fills_details_and_checks_domain(app, client):
    ids, _ = seed(app)
    r = campus_signup(client, ids["Thar Campus"], email="admin@gmail.com")
    assert "personal email" in err(r)["details"]["admin_email"]
    r = campus_signup(client, ids["Thar Campus"], email="admin@ned.edu.pk")
    assert err(r)["details"]["admin_email"].startswith("Use your @neduet.edu.pk email")
    r = campus_signup(client, ids["Thar Campus"], email="dean@cs.neduet.edu.pk")       # sub-domain is fine
    assert r.status_code == 201
    inst = r.get_json()["data"]["institution"]
    assert inst["name"] == "NED University of Engineering & Technology" and inst["campus_name"] == "Thar Campus"
    assert inst["city"] == "Mithi" and inst["type"] == "University" and inst["website"] == "https://www.neduet.edu.pk"
    assert inst["from_directory"] and inst["email_domain_verified"] and not inst["no_official_email"]
    assert inst["display_name"] == "NED University of Engineering & Technology · Thar Campus"


def test_campus_registered_once_but_other_campus_free(app, client):
    ids, _ = seed(app)
    assert campus_signup(client, ids["City Campus"], email="a@neduet.edu.pk").status_code == 201
    r = campus_signup(client, ids["City Campus"], email="b@neduet.edu.pk")
    assert r.status_code == 409 and err(r)["code"] == "INSTITUTION_TAKEN"
    assert campus_signup(client, ids["Thar Campus"], email="b@neduet.edu.pk").status_code == 201
    with app.app_context():                                                             # rejected frees the campus
        Institution.query.filter_by(campus_name="City Campus").one().status = "rejected"
        db.session.commit()
    assert campus_signup(client, ids["City Campus"], email="c@neduet.edu.pk").status_code == 201


def test_no_official_email_refused_when_directory_knows_the_domain(app, client):
    ids, _ = seed(app)
    r = campus_signup(client, ids["City Campus"], email="ned.admin@gmail.com", no_official_email=True)
    assert "has official email addresses (@neduet.edu.pk)" in err(r)["details"]["admin_email"]


def multipart_signup(client, email, proof, **fields):
    form = {**{k: str(v) for k, v in SIGNUP.items()}, "admin_email": email, "no_official_email": "true",
            "email_token": email_token(client, email), **fields}
    if proof is not None:
        form["proof"] = (io.BytesIO(proof[1]), proof[0])
    return client.post(SIGNUP_URL, data=form, content_type="multipart/form-data")


def test_school_without_domain_signs_up_with_gmail_and_proof(app, client):
    ids, _ = seed(app)
    r = multipart_signup(client, "sunrise.school@gmail.com", ("letter.exe", b"MZ\x90\x00"),
                         directory_campus_id=ids["Gulshan Campus"])
    assert r.status_code == 422 and "PDF, JPG or PNG" in err(r)["details"]["proof"]
    big = b"%PDF" + b"0" * (5 * 1024 * 1024)
    r = multipart_signup(client, "sunrise.school@gmail.com", ("big.pdf", big), directory_campus_id=ids["Gulshan Campus"])
    assert "at most 5 MB" in err(r)["details"]["proof"]
    r = multipart_signup(client, "sunrise.school@gmail.com", ("letter.pdf", PDF), directory_campus_id=ids["Gulshan Campus"])
    assert r.status_code == 201, r.get_json()
    inst = r.get_json()["data"]["institution"]
    assert inst["no_official_email"] and inst["has_proof"] and not inst["email_domain_verified"]
    assert inst["name"] == "Sunrise Grammar School" and inst["type"] == "School"

    # only the Super Admin can download the proof, as a file
    assert client.get(f"/api/v1/super/institutions/{inst['id']}/proof").status_code == 401
    login(client, "root@assessify.com", "SuperSecret123")
    r = client.get(f"/api/v1/super/institutions/{inst['id']}/proof")
    assert r.status_code == 200 and r.data == PDF and r.mimetype == "application/pdf"
    assert "attachment" in r.headers["Content-Disposition"]


# ---------- not in the list ----------
def test_manual_institution_joins_directory_when_approved(app, client):
    seed(app)
    r = do_signup(client, institution_name="Bright Future College", institution_type="College", city="Hyderabad",
                  campus_name="Latifabad Campus", website="https://www.brightfuture.edu.pk",
                  admin_email="principal@brightfuture.edu.pk")
    assert r.status_code == 201
    inst = r.get_json()["data"]["institution"]
    assert not inst["from_directory"] and inst["email_domain_verified"]                # email matches the website
    assert client.get(SEARCH + "?q=bright").get_json()["data"]["items"] == []           # not before approval

    login(client, "root@assessify.com", "SuperSecret123")
    assert client.patch(f"/api/v1/super/institutions/{inst['id']}", json={"status": "approved"}).status_code == 200
    items = client.get(SEARCH + "?q=bright").get_json()["data"]["items"]
    assert [(i["label"], i["registered"], i["email_domain"]) for i in items] == [
        ("Bright Future College · Latifabad Campus, Hyderabad", True, "brightfuture.edu.pk")]
    r = do_signup(client.application.test_client(), institution_name="Bright Future College", institution_type="College",
                  city="Hyderabad", campus_name="Latifabad Campus", admin_email="other@brightfuture.edu.pk")
    assert r.status_code == 409


def test_new_campus_of_listed_institution(app, client):
    _, ned_id = seed(app)
    r = do_signup(client, directory_institution_id=ned_id, campus_name="Gulshan Campus", city="Karachi",
                  institution_name="", institution_type="", admin_email="g@neduet.edu.pk")
    assert r.status_code == 201
    inst = r.get_json()["data"]["institution"]
    assert inst["name"] == "NED University of Engineering & Technology" and inst["campus_name"] == "Gulshan Campus"
    assert inst["email_domain_verified"] and not inst["from_directory"]
    r = do_signup(client, directory_institution_id=ned_id, campus_name="Gulshan Campus", city="Karachi",
                  admin_email="h@ned.edu.pk")
    assert err(r)["details"]["admin_email"].startswith("Use your @neduet.edu.pk")       # parent's domain applies

    login(client, "root@assessify.com", "SuperSecret123")
    client.patch(f"/api/v1/super/institutions/{inst['id']}", json={"status": "approved"})
    with app.app_context():
        assert DirectoryInstitution.query.count() == 2                                  # same parent, new campus
        assert {c.campus_name for c in db.session.get(DirectoryInstitution, ned_id).campuses} == {
            "City Campus", "Thar Campus", "Gulshan Campus"}


def test_typed_name_of_listed_institution_uses_its_domain(app, client):
    seed(app)
    r = do_signup(client, institution_name="ned university of engineering & technology", admin_email="x@ned.edu.pk")
    assert err(r)["details"]["admin_email"].startswith("Use your @neduet.edu.pk")


# ---------- helpers ----------
def test_email_rules():
    assert email_rules.matches("cs.neduet.edu.pk", "neduet.edu.pk")
    assert not email_rules.matches("fakeneduet.edu.pk", "neduet.edu.pk")
    assert email_rules.matches("cuilahore.edu.pk", "comsats.edu.pk, cuilahore.edu.pk")
    assert email_rules.host_of("https://www.NEDuet.edu.pk/about") == "neduet.edu.pk"
    assert email_rules.is_free("gmail.com") and not email_rules.is_free("neduet.edu.pk")


def test_seed_file_loads_and_is_repeatable(app):
    import seed_directory
    with app.app_context():
        a, c, _ = seed_directory.load(seed_directory.DEFAULT_FILE)
        assert a > 100 and c > 150
        assert seed_directory.load(seed_directory.DEFAULT_FILE)[:2] == (0, 0)
        ned = DirectoryInstitution.query.filter_by(short_name="NED").one()
        assert {x.campus_name for x in ned.campuses} >= {"City Campus", "Thar Campus"}
