"""Phase 5 - candidate roster. Institution Admin only; everything is scoped to the signed-in admin's institution.

GET    /roster?test_id=&department_id=&q=&page=&per_page=   one published test's roster (paged) + summary
POST   /roster/import                multipart: file (CSV or .xlsx), test_id, dry_run? -> imported / warnings / skipped /
                                     errors per row (Phase 9: lenient, see service.py)
GET    /roster/template.csv          empty CSV with the expected headings and two example rows
GET    /roster/export.csv?test_id=   the whole roster filled in: access codes, PINs, dates of birth (Phase 9)
GET    /roster/slips?test_id=        one slip per candidate for printing (code + PIN, never the date of birth)
GET    /roster/counts                {test_id: number of candidates} for every test of the institution
POST   /roster                       add one candidate {test_id, full_name, email?, phone?, roll_number?, date_of_birth?,
                                     department_id, access_code?} - name + one of email / phone / roll number
PUT    /roster/<id>                  correct a candidate (same fields, no test_id / access_code)
POST   /roster/<id>/new-code         replace the access code (old one stops working at once)
DELETE /roster/<id>                  remove from the roster
"""
from flask import Blueprint, Response, g, request

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.roster import service

bp = Blueprint("roster", __name__)
ADMIN = ROLE_INSTITUTION_ADMIN


def _csv(filename: str, text: str) -> Response:
    # BOM so Excel opens UTF-8 names (e.g. Urdu) correctly
    return Response("﻿" + text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@bp.get("")
@auth_required(ADMIN)
def list_all():
    return ok(service.list_roster(g.current_user.institution_id, request.args))


@bp.post("/import")
@auth_required(ADMIN)
def import_csv():
    dry_run = str(request.form.get("dry_run", "")).lower() in ("1", "true", "yes")
    return ok(service.import_csv(g.current_user, request.form.get("test_id"), request.files.get("file"), dry_run))


@bp.get("/template.csv")
@auth_required(ADMIN)
def template():
    return _csv("roster-template.csv", service.template_csv())


@bp.get("/export.csv")
@auth_required(ADMIN)
def export():
    return _csv(*service.export_csv(g.current_user.institution_id, request.args.get("test_id")))


@bp.get("/slips")
@auth_required(ADMIN)
def slips():
    return ok(service.slips(g.current_user.institution_id, request.args.get("test_id")))


@bp.get("/counts")
@auth_required(ADMIN)
def counts():
    return ok({"counts": service.counts_by_test(g.current_user.institution_id)})


@bp.post("")
@auth_required(ADMIN)
def add():
    body = json_body()
    c = service.add_candidate(g.current_user, body.get("test_id"), body)
    return ok({"candidate": service.serialise(c)}, 201)


@bp.get("/<int:candidate_id>")
@auth_required(ADMIN)
def detail(candidate_id: int):
    c = service.get_candidate(g.current_user.institution_id, candidate_id)
    return ok({"candidate": service.serialise(c)})


@bp.put("/<int:candidate_id>")
@auth_required(ADMIN)
def update(candidate_id: int):
    c = service.update_candidate(g.current_user.institution_id, candidate_id, json_body())
    return ok({"candidate": service.serialise(c)})


@bp.post("/<int:candidate_id>/new-code")
@auth_required(ADMIN)
def new_code(candidate_id: int):
    c = service.regenerate_code(g.current_user.institution_id, candidate_id)
    return ok({"candidate": service.serialise(c)})


@bp.delete("/<int:candidate_id>")
@auth_required(ADMIN)
def delete(candidate_id: int):
    service.delete_candidate(g.current_user.institution_id, candidate_id)
    return ok({"deleted": candidate_id})
