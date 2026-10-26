"""Institution Admin only. Everything is scoped to the signed-in admin's institution.
GET    /departments?level=&q=   list
POST   /departments             create  {name, level, mode, subjects: [..]}
GET    /departments/<id>        one
PUT    /departments/<id>        update (same body as create)
DELETE /departments/<id>        delete (its subjects go with it)
"""
from flask import Blueprint, g, request

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.departments import service

bp = Blueprint("departments", __name__)


@bp.get("")
@auth_required(ROLE_INSTITUTION_ADMIN)
def list_all():
    items = service.list_departments(g.current_user.institution_id, request.args.get("level"), request.args.get("q"))
    return ok({"items": [d.to_dict() for d in items]})


@bp.post("")
@auth_required(ROLE_INSTITUTION_ADMIN)
def create():
    dept = service.create_department(g.current_user.institution_id, json_body())
    return ok({"department": dept.to_dict()}, 201)


@bp.get("/<int:department_id>")
@auth_required(ROLE_INSTITUTION_ADMIN)
def get_one(department_id: int):
    return ok({"department": service.get_department(g.current_user.institution_id, department_id).to_dict()})


@bp.put("/<int:department_id>")
@auth_required(ROLE_INSTITUTION_ADMIN)
def update(department_id: int):
    dept = service.update_department(g.current_user.institution_id, department_id, json_body())
    return ok({"department": dept.to_dict()})


@bp.delete("/<int:department_id>")
@auth_required(ROLE_INSTITUTION_ADMIN)
def delete(department_id: int):
    service.delete_department(g.current_user.institution_id, department_id)
    return ok({"deleted": department_id})
