"""Phase 10 (public): GET /directory/search?q=ned  -> matching campuses for the signup search box."""
from flask import Blueprint, request

from app.common.responses import ok
from app.modules.directory import service

bp = Blueprint("directory", __name__)


@bp.get("/search")
def search():
    return ok({"items": service.search(request.args.get("q"))})
