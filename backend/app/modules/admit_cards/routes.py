"""Phase 11 - admit cards by email. Institution Admin only; scoped to the signed-in admin's institution.

GET  /admit-cards?test_id=                          who got a card, who has no email, why a card failed / bounced,
                                                    and whether (and why not) the Send button can be used
POST /admit-cards/send {test_id, candidate_ids?, resend?, login_url?}
GET  /admit-cards/<candidate_id>.pdf?login_url=     the admit card PDF (preview / print)
POST /admit-cards/check-bounces {test_id}           reads "delivery failed" replies from the sending mailbox
"""
import io

from flask import Blueprint, g, request, send_file

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.models.user import ROLE_INSTITUTION_ADMIN
from app.modules.admit_cards import service

bp = Blueprint("admit_cards", __name__)
ADMIN = ROLE_INSTITUTION_ADMIN


@bp.get("")
@auth_required(ADMIN)
def status():
    return ok(service.status(g.current_user.institution_id, request.args.get("test_id")))


@bp.post("/send")
@auth_required(ADMIN)
def send():
    return ok(service.send(g.current_user, json_body()))


@bp.get("/<int:candidate_id>.pdf")
@auth_required(ADMIN)
def card(candidate_id: int):
    filename, data = service.card_pdf(g.current_user.institution_id, candidate_id, request.args.get("login_url"))
    response = send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=False,
                         download_name=filename, max_age=0)
    response.headers["Cache-Control"] = "no-store"          # it holds the access code and PIN
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.post("/check-bounces")
@auth_required(ADMIN)
def check_bounces():
    return ok(service.check_bounces(g.current_user, json_body()))
