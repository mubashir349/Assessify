"""POST /institutions/signup   (public)  -> creates a PENDING institution + its first admin.

Phase 10: JSON, or multipart/form-data when a proof document is attached (field "proof").
"""
from flask import Blueprint, request

from app.common.responses import ok
from app.common.validation import json_body
from app.modules.institutions import service

bp = Blueprint("institutions", __name__)


@bp.post("/signup")
def signup():
    if request.mimetype == "multipart/form-data":
        inst = service.register_institution(request.form.to_dict(), request.files.get("proof"))
    else:
        inst = service.register_institution(json_body())
    if inst.status == "awaiting_payment":         # Phase 11: pay first, then the Super Admin reviews it
        from app.modules.payments.service import make_token
        return ok({"institution": inst.to_dict(), "next": "payment", "payment_token": make_token(inst),
                   "message": "Registration saved. Pay the subscription fee to send it for approval."}, 201)
    return ok({"institution": inst.to_dict(), "next": "wait",
               "message": "Registration submitted. You can sign in once the platform team approves it."}, 201)
