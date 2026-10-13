"""POST /auth/login   POST /auth/logout   GET /auth/me"""
from flask import Blueprint, g, jsonify
from flask_jwt_extended import create_access_token, set_access_cookies, unset_jwt_cookies

from app.common.decorators import auth_required
from app.common.responses import ok
from app.common.validation import json_body
from app.modules.auth import service

bp = Blueprint("auth", __name__)


@bp.post("/login")
def login():
    body = json_body()
    user = service.authenticate(body.get("email"), body.get("password"))
    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    resp = jsonify({"data": {"user": user.to_dict()}})
    set_access_cookies(resp, token)
    return resp, 200


@bp.post("/logout")
def logout():
    resp = jsonify({"data": {"message": "Signed out."}})
    unset_jwt_cookies(resp)
    return resp, 200


@bp.get("/me")
@auth_required()
def me():
    return ok({"user": g.current_user.to_dict()})
