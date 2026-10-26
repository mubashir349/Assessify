"""Phase 6 - taking the test. Candidate routes use the candidate cookie (Phase 5 sign-in).

GET  /exam                 the time gate for the start page: state, server time, start / end, attempt if any
POST /exam/start           starts (or resumes) the attempt -> {attempt, questions}
GET  /exam/paper           the attempt + its questions (to resume after a reload or a lost connection)
PUT  /exam/answers/<n>     {choice: 0-based | null, flagged?: bool} for question number n -> {attempt, question}
POST /exam/lock            {reason: fullscreen_exit | tab_hidden} -> {attempt} (status locked)
POST /exam/submit          -> {attempt} (status submitted, scored on the server)
GET  /exam/result          -> score (immediate release) or the release date (scheduled)

Institution Admin:
POST /attempts/<id>/unlock -> {attempt}   (the Phase 7 monitor page builds on this)

Every candidate route runs with allow_ended=True so that, after the end time, the attempt is submitted and the
request gets a clear TIME_UP / result instead of a bare "session closed".
"""
from flask import Blueprint, g, request

from app.common.candidate import candidate_required
from app.common.decorators import auth_required
from app.common.errors import ApiError
from app.common.responses import ok
from app.common.validation import json_body
from app.extensions import db
from app.models.exam import ExamAttempt
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.exam import service

bp = Blueprint("exam", __name__)
admin_bp = Blueprint("exam_admin", __name__)


def _with_paper(attempt: ExamAttempt) -> dict:
    return {"attempt": attempt.to_dict(), "questions": attempt.paper_dict()}


@bp.get("")
@candidate_required(allow_ended=True)
def gate():
    return ok({"gate": service.gate(g.current_candidate)})


@bp.post("/start")
@candidate_required(allow_ended=True)
def start():
    return ok(_with_paper(service.start(g.current_candidate)))


@bp.get("/paper")
@candidate_required(allow_ended=True)
def paper():
    attempt = service.current(g.current_candidate)
    if attempt.status == "submitted":
        return ok({"attempt": attempt.to_dict(), "questions": []})
    return ok(_with_paper(attempt))


@bp.put("/answers/<int:number>")
@candidate_required(allow_ended=True)
def answer(number: int):
    item = service.save_answer(g.current_candidate, number, json_body())
    return ok({"attempt": item.attempt.to_dict(), "question": item.candidate_dict()})


@bp.post("/lock")
@candidate_required(allow_ended=True)
def lock():
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    return ok({"attempt": service.lock(g.current_candidate, body.get("reason")).to_dict()})


@bp.post("/submit")
@candidate_required(allow_ended=True)
def submit():
    return ok({"attempt": service.submit(g.current_candidate).to_dict()})


@bp.get("/result")
@candidate_required(allow_ended=True)
def result():
    return ok(service.result(g.current_candidate))


@admin_bp.post("/<int:attempt_id>/unlock")
@auth_required(ROLE_INSTITUTION_ADMIN)
def unlock(attempt_id: int):
    attempt = db.session.get(ExamAttempt, attempt_id)
    if attempt is None or attempt.candidate.institution_id != g.current_user.institution_id:
        raise ApiError("NOT_FOUND", "Attempt not found.", 404)
    return ok({"attempt": service.unlock(attempt, g.current_user).admin_dict()})
