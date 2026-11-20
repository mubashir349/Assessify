"""Phase 7 - reports, AI insights and result emails (Institution Admin).

GET  /reports/tests?q=&level=&year=                         published tests with a short summary each
GET  /reports/tests/<id>?department_id=&q=&status=&email=   full report of one test (+ filtered candidate list)
GET  /reports/tests/<id>/export.csv?(same filters)          the candidate list as a spreadsheet
GET  /reports/tests/<id>/export.xlsx?(same filters)         Phase 11: Excel workbook (summary, results, by field / subject)
POST /reports/tests/<id>/send-results {candidate_ids?, resend?}  result emails, logged in the email log
GET  /reports/bank-insights                                  rule-based tips about the question bank
POST /reports/ai-summary {scope: test | bank, test_id?}      short AI-written insights from the numbers
"""
import io

from flask import Blueprint, current_app, g, request, send_file

from app.common.decorators import auth_required
from app.common.responses import ok
from app.extensions import db
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.models.candidate import Candidate
from app.models.institution import Institution
from app.common.errors import ApiError
from app.modules.reports import ai_summary, emails, excel, pdf, service

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


@bp.get("/tests/<int:test_id>.pdf")
@auth_required(ADMIN)
def report_pdf(test_id: int):
    data = service.report(g.current_user.institution_id, test_id, request.args, current_app.config)
    institution = db.session.get(Institution, g.current_user.institution_id)
    payload = pdf.render_test_report(data, institution, current_app.config.get("ADMIT_CARD_FONT", ""),
                                     current_app.config.get("APP_TIMEZONE", "Asia/Karachi"))
    filename = "Assessify - " + "".join(ch if ch.isalnum() or ch in " -_" else "-" for ch in data["test"]["name"])[:70]
    response = send_file(io.BytesIO(payload), mimetype="application/pdf", as_attachment=True,
                         download_name=filename.strip() + ".pdf", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/tests/<int:test_id>/candidates/<int:candidate_id>.pdf")
@auth_required(ADMIN)
def candidate_result_pdf(test_id: int, candidate_id: int):
    candidate = Candidate.query.filter_by(id=candidate_id, test_id=test_id,
                                          institution_id=g.current_user.institution_id).first()
    if candidate is None:
        raise ApiError("NOT_FOUND", "Candidate not found.", 404)
    if candidate.attempt is None or candidate.attempt.status != "submitted":
        raise ApiError("RESULT_NOT_READY", "A result PDF is available after the assessment has been submitted.", 409)
    payload = pdf.render_student_result(candidate, current_app.config.get("ADMIT_CARD_FONT", ""),
                                        current_app.config.get("APP_TIMEZONE", "Asia/Karachi"))
    filename = "Result - " + "".join(ch if ch.isalnum() or ch in " -_" else "-" for ch in candidate.full_name)[:70]
    response = send_file(io.BytesIO(payload), mimetype="application/pdf", as_attachment=True,
                         download_name=filename.strip() + ".pdf", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/tests/<int:test_id>/export.csv")
@auth_required(ADMIN)
def export(test_id: int):
    filename, text = service.export_csv(g.current_user.institution_id, test_id, request.args)
    # a file download (never shown as a page); UTF-8 with BOM so Excel opens Urdu names correctly
    response = send_file(io.BytesIO(text.encode("utf-8-sig")), mimetype="text/csv", as_attachment=True,
                         download_name=filename, max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/tests/<int:test_id>/export.xlsx")
@auth_required(ADMIN)
def export_xlsx(test_id: int):
    filename, data = excel.export_xlsx(g.current_user.institution_id, test_id, request.args)
    response = send_file(io.BytesIO(data), as_attachment=True, download_name=filename, max_age=0,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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
