from app.extensions import db
from app.models.institution import Institution
from tests.conftest import SIGNUP, login

DEPT = {"name": "Pre-Engineering", "level": "Undergraduate", "mode": "field",
        "subjects": ["Mathematics", "Physics", "Chemistry", "English"]}


def make_admin(app, email="admissions@ned.edu.pk", name="NED University"):
    """Approved institution + its admin; returns a logged-in test client."""
    c = app.test_client()
    c.post("/api/v1/institutions/signup", json={**SIGNUP, "admin_email": email, "institution_name": name})
    with app.app_context():
        Institution.query.filter_by(name=name).first().status = "approved"
        db.session.commit()
    assert login(c, email, SIGNUP["password"]).status_code == 200
    return c


def test_meta_is_public_and_complete(client):
    d = client.get("/api/v1/meta").get_json()["data"]
    assert "University" in d["institution_types"]
    assert "pending" in d["institution_statuses"]
    assert [l["value"] for l in d["levels"]] == ["Undergraduate", "Masters", "PhD"]
    assert d["levels"][0]["term"] == "Field"
    assert d["levels"][1]["term"] == "Department"
    assert {m["value"] for m in d["modes"]} == {"general", "field"}


def test_departments_require_institution_admin(client, app):
    assert client.get("/api/v1/departments").status_code == 401
    login(client, "root@assessai.com", "SuperSecret123")
    assert client.get("/api/v1/departments").status_code == 403       # super admin has no institution


def test_create_list_update_delete(app):
    c = make_admin(app)
    assert c.get("/api/v1/departments").get_json()["data"]["items"] == []   # nothing is pre-filled
    r = c.post("/api/v1/departments", json=DEPT)
    assert r.status_code == 201
    dept = r.get_json()["data"]["department"]
    assert dept["subjects"] == DEPT["subjects"]
    assert dept["term"] == "Field"

    r = c.put(f"/api/v1/departments/{dept['id']}", json={**DEPT, "name": "Pre-Eng", "subjects": ["Physics", "Mathematics", "Biology"]})
    upd = r.get_json()["data"]["department"]
    assert r.status_code == 200
    assert upd["name"] == "Pre-Eng"
    assert upd["subjects"] == ["Physics", "Mathematics", "Biology"]

    assert len(c.get("/api/v1/departments?q=pre").get_json()["data"]["items"]) == 1
    assert c.get("/api/v1/departments?level=PhD").get_json()["data"]["items"] == []
    assert c.get("/api/v1/departments?level=bogus").status_code == 400

    assert c.delete(f"/api/v1/departments/{dept['id']}").status_code == 200
    assert c.get(f"/api/v1/departments/{dept['id']}").status_code == 404
    assert c.get("/api/v1/departments").get_json()["data"]["items"] == []


def test_validation(app):
    c = make_admin(app)
    r = c.post("/api/v1/departments", json={"name": "", "level": "Nope", "mode": "x", "subjects": []})
    assert r.status_code == 422
    assert set(r.get_json()["error"]["details"]) == {"name", "level", "mode", "subjects"}
    r = c.post("/api/v1/departments", json={**DEPT, "subjects": ["  ", ""]})
    assert r.status_code == 422
    r = c.post("/api/v1/departments", json={**DEPT, "subjects": ["Maths", "maths", " Maths "]})
    assert r.get_json()["data"]["department"]["subjects"] == ["Maths"]          # de-duplicated


def test_duplicate_name_same_level_only(app):
    c = make_admin(app)
    assert c.post("/api/v1/departments", json=DEPT).status_code == 201
    r = c.post("/api/v1/departments", json={**DEPT, "name": "pre-engineering"})
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "DUPLICATE_NAME"
    assert c.post("/api/v1/departments", json={**DEPT, "level": "Masters"}).status_code == 201


def test_institutions_cannot_see_each_others_data(app):
    a = make_admin(app, "a@one.edu", "One University")
    b = make_admin(app, "b@two.edu", "Two University")
    dept_id = a.post("/api/v1/departments", json=DEPT).get_json()["data"]["department"]["id"]
    assert b.get("/api/v1/departments").get_json()["data"]["items"] == []
    assert b.get(f"/api/v1/departments/{dept_id}").status_code == 404
    assert b.put(f"/api/v1/departments/{dept_id}", json=DEPT).status_code == 404
    assert b.delete(f"/api/v1/departments/{dept_id}").status_code == 404
    assert a.get(f"/api/v1/departments/{dept_id}").status_code == 200


def test_dashboard_summary_is_computed_from_the_database(app):
    c = make_admin(app)
    d = c.get("/api/v1/dashboard/summary").get_json()["data"]
    assert d["institution"]["name"] == "NED University"
    assert d["departments"]["total"] == 0
    assert d["subjects"]["total"] == 0
    c.post("/api/v1/departments", json=DEPT)
    c.post("/api/v1/departments", json={"name": "General Test", "level": "Undergraduate", "mode": "general", "subjects": ["Maths", "English"]})
    d = c.get("/api/v1/dashboard/summary").get_json()["data"]
    assert d["departments"]["total"] == 2
    assert d["departments"]["general_tests"] == 1
    assert d["subjects"]["total"] == 6
