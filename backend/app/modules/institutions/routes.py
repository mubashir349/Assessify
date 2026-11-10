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
    return ok({"institution": inst.to_dict(),
               "message": "Registration submitted. You can sign in once the platform team approves it."}, 201)
