"""Phase 7 - reports, AI insights and result emails (Institution Admin).

GET  /reports/tests?q=&level=&year=                         published tests with a short summary each
GET  /reports/tests/<id>?department_id=&q=&status=&email=   full report of one test (+ filtered candidate list)
GET  /reports/tests/<id>/export.csv?(same filters)          the candidate list as a spreadsheet
POST /reports/tests/<id>/send-results {candidate_ids?, resend?}  result emails, logged in the email log
GET  /reports/bank-insights                                  rule-based tips about the question bank
POST /reports/ai-summary {scope: test | bank, test_id?}      short AI-written insights from the numbers
"""
from flask import Blueprint, Response, current_app, g, request

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.reports import ai_summary, emails, service

bp = Blueprint("reports", __name__)
ADMIN = ROLE_INSTITUTION_ADMIN


@bp.get("/tests")
@auth_required(ADMIN)
def tests():
    return ok({"tests": service.list_tests(g.current_user.institution_id, request.args)})


@bp.get("/tests/<int:test_id>")
@auth_required(ADMIN)
def report(test_id: int):
    return ok(service.report(g.current_user.institution_id, test_id, request.args, current_app.config))


@bp.get("/tests/<int:test_id>/export.csv")
@auth_required(ADMIN)
def export(test_id: int):
    filename, text = service.export_csv(g.current_user.institution_id, test_id, request.args)
    # BOM so Excel opens UTF-8 names (e.g. Urdu) correctly
    return Response("﻿" + text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@bp.post("/tests/<int:test_id>/send-results")
@auth_required(ADMIN)
def send_results(test_id: int):
    return ok(emails.send_results(g.current_user, test_id, json_body()))


@bp.get("/bank-insights")
@auth_required(ADMIN)
def bank_insights():
    data = ai_summary.bank_stats(g.current_user.institution_id)
    return ok({**data, "tips": ai_summary.bank_tips(data)})


@bp.post("/ai-summary")
@auth_required(ADMIN)
def ai():
    return ok(ai_summary.ai_summary(g.current_user.institution_id, json_body()))
