from app.extensions import db
from app.models.institution import Institution
from tests.conftest import SIGNUP, login


def signup(client, **over):
    return client.post("/api/v1/institutions/signup", json={**SIGNUP, **over})


def super_login(client):
    assert login(client, "root@assessai.com", "SuperSecret123").status_code == 200


# ---------- signup ----------
def test_signup_creates_pending_institution(client):
    r = signup(client)
    assert r.status_code == 201
    inst = r.get_json()["data"]["institution"]
    assert inst["status"] == "pending"
    assert inst["admin"]["email"] == "admissions@ned.edu.pk"  # email lower-cased
    assert "password" not in str(r.get_json()).lower().replace("password_hash", "")


def test_signup_validation_errors(client):
    r = signup(client, institution_name="", admin_email="nope", password="short", institution_type="Zoo")
    assert r.status_code == 422
    d = r.get_json()["error"]["details"]
    assert set(d) >= {"institution_name", "admin_email", "password", "institution_type"}


def test_signup_duplicate_email(client):
    assert signup(client).status_code == 201
    r = signup(client, institution_name="Other Uni")
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "EMAIL_TAKEN"


def test_signup_rejects_non_json(client):
    r = client.post("/api/v1/institutions/signup", data="x=1")
    assert r.status_code == 400


# ---------- login rules ----------
def test_pending_institution_cannot_login(client):
    signup(client)
    r = login(client, "admissions@ned.edu.pk", "Strong#Pass1")
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "INSTITUTION_PENDING"


def test_wrong_password_and_unknown_email_look_identical(client):
    signup(client)
    a = login(client, "admissions@ned.edu.pk", "wrong-password")
    b = login(client, "ghost@nowhere.com", "wrong-password")
    assert a.status_code == b.status_code == 401
    assert a.get_json() == b.get_json()


def test_pending_status_not_leaked_with_wrong_password(client):
    signup(client)
    r = login(client, "admissions@ned.edu.pk", "wrong-password")
    assert r.get_json()["error"]["code"] == "INVALID_CREDENTIALS"


# ---------- approval flow ----------
def approve(client, inst_id, status="approved"):
    return client.patch(f"/api/v1/super/institutions/{inst_id}", json={"status": status, "note": "ok"})


def test_full_flow_signup_approve_login_me_logout(client, app):
    inst_id = signup(client).get_json()["data"]["institution"]["id"]

    super_login(client)
    listing = client.get("/api/v1/super/institutions?status=pending").get_json()["data"]
    assert listing["counts"]["pending"] == 1
    assert listing["items"][0]["id"] == inst_id
    assert approve(client, inst_id).status_code == 200
    client.post("/api/v1/auth/logout")

    r = login(client, "admissions@ned.edu.pk", "Strong#Pass1")
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["role"] == "institution_admin"
    me = client.get("/api/v1/auth/me").get_json()["data"]["user"]
    assert me["institution"]["name"] == "NED University"
    assert me["institution"]["status"] == "approved"

    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_cookie_is_httponly(client):
    r = login(client, "root@assessai.com", "SuperSecret123")
    cookie = [h for h in r.headers.getlist("Set-Cookie") if h.startswith("access_token_cookie")][0]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_rejected_then_approved_and_invalid_transitions(client):
    inst_id = signup(client).get_json()["data"]["institution"]["id"]
    super_login(client)
    assert approve(client, inst_id, "suspended").status_code == 409      # pending -> suspended not allowed
    assert approve(client, inst_id, "rejected").status_code == 200
    assert approve(client, inst_id, "pending").status_code == 400
    assert approve(client, inst_id, "approved").status_code == 200
    assert approve(client, 9999).status_code == 404


def test_suspension_cuts_off_an_active_session_immediately(client, app):
    inst_id = signup(client).get_json()["data"]["institution"]["id"]
    with app.app_context():
        db.session.get(Institution, inst_id).status = "approved"
        db.session.commit()
    admin = app.test_client()
    assert login(admin, "admissions@ned.edu.pk", "Strong#Pass1").status_code == 200
    assert admin.get("/api/v1/auth/me").status_code == 200

    super_login(client)
    assert approve(client, inst_id, "suspended").status_code == 200

    r = admin.get("/api/v1/auth/me")                       # old cookie, but institution is suspended
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "INSTITUTION_NOT_ACTIVE"
    assert login(app.test_client(), "admissions@ned.edu.pk", "Strong#Pass1").get_json()["error"]["code"] == "INSTITUTION_SUSPENDED"


# ---------- access control ----------
def test_super_routes_require_login_and_role(client, app):
    assert client.get("/api/v1/super/institutions").status_code == 401
    inst_id = signup(client).get_json()["data"]["institution"]["id"]
    with app.app_context():
        db.session.get(Institution, inst_id).status = "approved"
        db.session.commit()
    login(client, "admissions@ned.edu.pk", "Strong#Pass1")
    r = client.get("/api/v1/super/institutions")
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "FORBIDDEN"
    assert approve(client, inst_id, "suspended").status_code == 403


def test_garbage_cookie_gives_json_401(client):
    client.set_cookie("access_token_cookie", "not.a.jwt")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_search_and_filter(client):
    signup(client)
    signup(client, institution_name="Karachi College", admin_email="b@kc.edu", city="Karachi")
    super_login(client)
    d = client.get("/api/v1/super/institutions?q=college").get_json()["data"]
    assert [i["name"] for i in d["items"]] == ["Karachi College"]
    assert d["counts"]["total"] == 2
    assert client.get("/api/v1/super/institutions?q=b@kc.edu").get_json()["data"]["items"][0]["name"] == "Karachi College"
    assert client.get("/api/v1/super/institutions?status=bogus").status_code == 400
