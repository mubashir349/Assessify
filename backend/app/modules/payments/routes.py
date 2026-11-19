"""Phase 11 - payments (public: the institution cannot sign in until it has paid, so the payment page carries a
signed "pay now" token instead of a login cookie).

GET  /payments/plans                       plans and prices, and whether the gateway is set up
GET  /payments/session?token=              the payment page: institution, what is due, latest payment
POST /payments/checkout {token, plan, return_url}   -> {checkout_url}: the browser goes to Safepay
POST /payments/confirm  {token, payment}   back from Safepay: the server asks Safepay whether it is paid
POST /payments/cancel   {token, payment}   the institution cancelled on the Safepay page
POST /payments/webhook                     Safepay -> us (optional; X-SFPY-SIGNATURE checked)
"""
from flask import Blueprint, current_app, request

from app.common.responses import ok
from app.common.validation import json_body
from app.modules.payments import service
from app.payments import gateway_status

bp = Blueprint("payments", __name__)


@bp.get("/plans")
def plans():
    return ok({"plans": service.plans(), "gateway": gateway_status(current_app.config)})


@bp.get("/session")
def session():
    return ok(service.session_info(request.args.get("token")))


@bp.post("/checkout")
def checkout():
    return ok(service.start_checkout(json_body()), 201)


@bp.post("/confirm")
def confirm():
    return ok(service.confirm(json_body()))


@bp.post("/cancel")
def cancel():
    return ok(service.cancel(json_body()))


@bp.post("/webhook")
def webhook():
    raw = request.get_data(cache=True)          # the signature is over the exact bytes Safepay sent
    return ok(service.webhook(raw, request.headers.get("X-SFPY-SIGNATURE"), request.get_json(silent=True)))
