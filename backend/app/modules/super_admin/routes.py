"""Super Admin only.
GET   /super/institutions?status=&q=     list + counts
PATCH /super/institutions/<id>           {"status": "approved|rejected|suspended", "note": "..."}
"""
from flask import Blueprint, g, request

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_SUPER_ADMIN
from app.modules.super_admin import service

bp = Blueprint("super_admin", __name__)


@bp.get("/institutions")
@auth_required(ROLE_SUPER_ADMIN)
def list_institutions():
    items, counts = service.list_institutions(request.args.get("status"), request.args.get("q"))
    return ok({"items": [i.to_dict() for i in items], "counts": counts})


@bp.patch("/institutions/<int:institution_id>")
@auth_required(ROLE_SUPER_ADMIN)
def update_institution(institution_id: int):
    body = json_body()
    inst = service.change_status(institution_id, body.get("status"), body.get("note"), g.current_user.email)
    return ok({"institution": inst.to_dict()})
