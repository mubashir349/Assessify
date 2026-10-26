"""Phase 3 - AI question generation, draft review and question bank.
Institution Admin only; everything is scoped to the signed-in admin's institution.

GET   /questions/ai-status                       is AI generation configured? (no secrets)
POST  /questions/check-pdf                       multipart: file -> is it readable? (no AI call, no quota)
POST  /questions/generate                        multipart: files (0-5 PDFs) + department_id, subject, question_type,
                                                 difficulty, count, marks, focus (required detail if no PDF)
GET   /questions/attempts?status=&q=&page=&per_page=
GET   /questions/attempts/<id>?include_replaced=true
POST  /questions/attempts/<id>/approve-all
POST  /questions/attempts/<id>/regenerate        {include_drafts?: bool}
GET   /questions/bank?department_id=&level=&subject=&difficulty=&question_type=&topic=&q=&page=&per_page=
GET   /questions/<id>
PUT   /questions/<id>                            edit a draft {text, options, correct_index, explanation, topic, difficulty, marks}
POST  /questions/<id>/approve
POST  /questions/<id>/reject                     {reason?}
POST  /questions/<id>/regenerate
"""
from flask import Blueprint, current_app, g, request

from app.ai import provider_status
from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.questions import service

bp = Blueprint("questions", __name__)
ADMIN = ROLE_INSTITUTION_ADMIN


def _optional_json() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.get("/ai-status")
@auth_required(ADMIN)
def ai_status():
    return ok(provider_status(current_app.config))


@bp.post("/check-pdf")
@auth_required(ADMIN)
def check_pdf():
    return ok(service.check_pdf(request.files.get("file")))


@bp.post("/generate")
@auth_required(ADMIN)
def generate():
    files = request.files.getlist("files") + request.files.getlist("file")   # "file" = older single-file form
    attempt = service.generate(g.current_user, request.form, files)
    return ok({"attempt": attempt.to_dict(with_questions=True)}, 201)


@bp.get("/attempts")
@auth_required(ADMIN)
def list_attempts():
    return ok(service.list_attempts(g.current_user.institution_id, request.args))


@bp.get("/attempts/<int:attempt_id>")
@auth_required(ADMIN)
def get_attempt(attempt_id: int):
    attempt = service.get_attempt(g.current_user.institution_id, attempt_id)
    include = request.args.get("include_replaced", "").lower() in ("1", "true", "yes")
    return ok({"attempt": attempt.to_dict(with_questions=True, include_replaced=include)})


@bp.post("/attempts/<int:attempt_id>/approve-all")
@auth_required(ADMIN)
def approve_all(attempt_id: int):
    return ok(service.approve_all(g.current_user, attempt_id))


@bp.post("/attempts/<int:attempt_id>/regenerate")
@auth_required(ADMIN)
def regenerate_attempt(attempt_id: int):
    return ok(service.regenerate_attempt(g.current_user, attempt_id, _optional_json()))


@bp.get("/bank")
@auth_required(ADMIN)
def bank():
    return ok(service.bank(g.current_user.institution_id, request.args))


@bp.get("/<int:question_id>")
@auth_required(ADMIN)
def get_question(question_id: int):
    return ok({"question": service.get_question(g.current_user.institution_id, question_id).to_dict()})


@bp.put("/<int:question_id>")
@auth_required(ADMIN)
def edit_question(question_id: int):
    return ok({"question": service.edit_question(g.current_user.institution_id, question_id, json_body()).to_dict()})


@bp.post("/<int:question_id>/approve")
@auth_required(ADMIN)
def approve(question_id: int):
    return ok({"question": service.approve_question(g.current_user, question_id).to_dict()})


@bp.post("/<int:question_id>/reject")
@auth_required(ADMIN)
def reject(question_id: int):
    return ok({"question": service.reject_question(g.current_user, question_id, _optional_json()).to_dict()})


@bp.post("/<int:question_id>/regenerate")
@auth_required(ADMIN)
def regenerate(question_id: int):
    new = service.regenerate_question(g.current_user, question_id)
    return ok({"question": new.to_dict(), "replaced_id": new.regenerated_from_id}, 201)
