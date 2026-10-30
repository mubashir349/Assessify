"""Phase 4 - creating tests. Institution Admin only; everything is scoped to the signed-in admin's institution.

GET    /tests?status=&level=&q=     list (summaries)
POST   /tests/availability          {level, compositions} -> 1.5x pool check, nothing is saved
POST   /tests                       create a draft {name, level, compositions, schedule}
GET    /tests/<id>                  one test, with a fresh availability check
PUT    /tests/<id>                  replace a draft (same body as create)
DELETE /tests/<id>                  delete a draft
POST   /tests/<id>/publish          re-validate, refuse while any pool is short, then publish
"""
from flask import Blueprint, g, request

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.aptitude_tests import service

bp = Blueprint("aptitude_tests", __name__)
ADMIN = ROLE_INSTITUTION_ADMIN


def _full(test) -> dict:
    return {**test.to_dict(), "availability": service.availability_of(test)}


@bp.get("")
@auth_required(ADMIN)
def list_all():
    items = service.list_tests(g.current_user.institution_id, request.args)
    return ok({"items": [t.summary_dict() for t in items]})


@bp.post("/availability")
@auth_required(ADMIN)
def availability():
    return ok({"availability": service.preview_availability(g.current_user.institution_id, json_body())})


@bp.post("")
@auth_required(ADMIN)
def create():
    return ok({"test": _full(service.create_test(g.current_user, json_body()))}, 201)


@bp.get("/<int:test_id>")
@auth_required(ADMIN)
def get_one(test_id: int):
    return ok({"test": _full(service.get_test(g.current_user.institution_id, test_id))})


@bp.put("/<int:test_id>")
@auth_required(ADMIN)
def update(test_id: int):
    return ok({"test": _full(service.update_test(g.current_user.institution_id, test_id, json_body()))})


@bp.delete("/<int:test_id>")
@auth_required(ADMIN)
def delete(test_id: int):
    service.delete_test(g.current_user.institution_id, test_id)
    return ok({"deleted": test_id})


@bp.post("/<int:test_id>/publish")
@auth_required(ADMIN)
def publish(test_id: int):
    return ok({"test": _full(service.publish_test(g.current_user.institution_id, test_id))})
