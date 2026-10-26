"""POST /institutions/signup   (public)  -> creates a PENDING institution + its first admin."""
from flask import Blueprint

from app.common.responses import ok
from app.common.validation import json_body
from app.modules.institutions import service

bp = Blueprint("institutions", __name__)


@bp.post("/signup")
def signup():
    inst = service.register_institution(json_body())
    return ok({"institution": inst.to_dict(),
               "message": "Registration submitted. You can sign in once the platform team approves it."}, 201)
