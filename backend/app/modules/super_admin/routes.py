"""Super Admin only.
GET   /super/institutions?status=&q=     list + counts
PATCH /super/institutions/<id>           {"status": "approved|rejected|suspended", "note": "..."}
GET   /super/institutions/<id>/proof     the proof document (Phase 10: institutions without official email)
GET   /super/institutions/<id>/payments  Phase 11: every payment of the institution
POST  /super/institutions/<id>/refund/retry    Phase 11: try the automatic refund again
POST  /super/institutions/<id>/refund/manual   Phase 11: {note} - refunded by hand in the Safepay dashboard
"""
import io

from flask import Blueprint, g, request, send_file

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
    return ok({"institution": inst.to_dict(), "refund": getattr(inst, "_refund", None)})


@bp.get("/institutions/<int:institution_id>/payments")
@auth_required(ROLE_SUPER_ADMIN)
def institution_payments(institution_id: int):
    from app.modules.payments.service import payments_of
    return ok({"payments": payments_of(institution_id)})


@bp.post("/institutions/<int:institution_id>/refund/retry")
@auth_required(ROLE_SUPER_ADMIN)
def refund_retry(institution_id: int):
    from app.modules.payments.service import retry_refund
    return ok(retry_refund(institution_id))


@bp.post("/institutions/<int:institution_id>/refund/manual")
@auth_required(ROLE_SUPER_ADMIN)
def refund_manual(institution_id: int):
    from app.modules.payments.service import mark_refunded_by_hand
    return ok(mark_refunded_by_hand(institution_id, json_body().get("note"), g.current_user.email))


@bp.get("/institutions/<int:institution_id>/proof")
@auth_required(ROLE_SUPER_ADMIN)
def institution_proof(institution_id: int):
    proof = service.proof_of(institution_id)
    # attachment: the browser saves it instead of running it (PDF / image only, checked on upload)
    return send_file(io.BytesIO(proof.data), mimetype=proof.content_type, as_attachment=True,
                     download_name=proof.filename)
