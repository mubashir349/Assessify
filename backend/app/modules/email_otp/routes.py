"""Phase 10 (public):
POST /auth/otp/send     {"email"}           -> emails a 6-digit code
POST /auth/otp/verify   {"email", "code"}   -> {"email_token"} to send with the signup
"""
from flask import Blueprint, request

from app.common.responses import ok
from app.common.validation import json_body
from app.modules.email_otp import service

bp = Blueprint("email_otp", __name__)


@bp.post("/send")
def send():
    return ok(service.send_code(json_body().get("email"), request.remote_addr))


@bp.post("/verify")
def verify():
    body = json_body()
    return ok(service.verify_code(body.get("email"), body.get("code")))
