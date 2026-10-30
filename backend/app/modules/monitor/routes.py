"""Phase 7 - live monitor for the Institution Admin.

GET /monitor/tests                                   published tests with state upcoming | live | ended
GET /monitor?test_id=&status=&department_id=&q=      counts + candidates of one test (the page polls every 5 s)

Actions on a row use the attempt routes: POST /attempts/<id>/unlock and POST /attempts/<id>/end.
"""
from flask import Blueprint, current_app, g, request

from app.common.decorators import auth_required
from app.common.responses import ok
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.monitor import service

bp = Blueprint("monitor", __name__)


@bp.get("/tests")
@auth_required(ROLE_INSTITUTION_ADMIN)
def tests():
    return ok({"tests": service.list_tests(g.current_user.institution_id)})


@bp.get("")
@auth_required(ROLE_INSTITUTION_ADMIN)
def snapshot():
    offline_after = int(current_app.config.get("MONITOR_DISCONNECTED_SECONDS", 75))
    return ok(service.snapshot(g.current_user.institution_id, request.args, offline_after))
