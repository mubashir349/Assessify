"""Phase 5 - candidate sign-in (public) and the candidate's own session.

POST /candidate/login    {access_code, date_of_birth: "YYYY-MM-DD"} or {access_code, pin: "123456"} -> {candidate} and sets the candidate cookie
POST /candidate/logout   clears it
GET  /candidate/me       {candidate}: name, roll number, field, institution, test name, schedule, subjects

The candidate cookie ("candidate_token") is separate from the admin login cookie, so an admin and a candidate can
use the same browser without signing each other out, and a candidate token is never accepted on admin routes.
"""
from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import create_access_token

from app.common.candidate import CANDIDATE_COOKIE, candidate_required, code_version
from app.common.responses import ok
from app.common.validation import json_body
from app.modules.candidate_auth import service

bp = Blueprint("candidate_auth", __name__)


@bp.post("/login")
def login():
    body = json_body()
    candidate = service.authenticate(body.get("access_code"), body.get("date_of_birth"), request.remote_addr,
                                     pin=body.get("pin"))
    lifetime = service.session_lifetime(candidate)
    token = create_access_token(identity=f"candidate:{candidate.id}", expires_delta=lifetime,
                                additional_claims={"kind": "candidate", "test_id": candidate.test_id,
                                                   "cv": code_version(candidate.access_code)})
    resp = jsonify({"data": {"candidate": candidate.session_dict()}})
    resp.set_cookie(CANDIDATE_COOKIE, token, max_age=int(lifetime.total_seconds()), httponly=True,
                    secure=current_app.config["JWT_COOKIE_SECURE"], samesite="Lax", path="/")
    return resp, 200


@bp.post("/logout")
def logout():
    resp = jsonify({"data": {"message": "Signed out."}})
    resp.delete_cookie(CANDIDATE_COOKIE, path="/")
    return resp, 200


@bp.get("/me")
@candidate_required(allow_ended=True)
def me():
    return ok({"candidate": g.current_candidate.session_dict()})
