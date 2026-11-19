"""Safepay (Pakistan) hosted checkout, as documented by Safepay and used in their SDKs.

Flow (sandbox and production work the same way, only the hosts and keys differ):
  1. POST {api}/order/payments/v3/                  body: merchant_api_key, intent=CYBERSOURCE, mode=payment,
                                                    currency=PKR, amount (paisa)          -> data.tracker.token
  2. POST {api}/client/passport/v1/token            header X-SFPY-MERCHANT-SECRET          -> data (short-lived tbt)
  3. Send the browser to {checkout}/embedded/?environment=..&tracker=..&tbt=..&source=hosted&redirect_url=..&cancel_url=..
     Safepay sends it back to redirect_url (paid) or cancel_url.
  4. GET  {api}/reporter/api/v1/payments/{tracker}  header X-SFPY-MERCHANT-SECRET          -> state TRACKER_ENDED = paid
     This server-to-server check is the ONLY thing that marks a payment paid.
  5. Refund: POST {api}{SAFEPAY_REFUND_PATH}         body: amount (paisa), currency. Safepay's docs show this call only
     through their SDK (order.payments.refund), so the path is a setting. If Safepay refuses it, the Super Admin sees
     the reason and can retry or refund in the Safepay dashboard.
  Webhooks (optional): header X-SFPY-SIGNATURE = hex HMAC-SHA512 of the raw body with the webhook secret. They are only
  used as a hint to re-check step 4, so a forged webhook cannot mark anything paid.

Keys never leave the server and are never logged.
"""
import hashlib
import hmac
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

HOSTS = {
    "sandbox": {"api": "https://sandbox.api.getsafepay.com", "checkout": "https://sandbox.api.getsafepay.com/embedded/"},
    "production": {"api": "https://api.getsafepay.com", "checkout": "https://getsafepay.com/embedded/"},
}
PAID_STATES = ("TRACKER_ENDED",)
REFUNDED_STATES = ("TRACKER_REFUNDED", "TRACKER_PARTIAL_REFUND", "TRACKER_REVERSED", "TRACKER_VOIDED")
DEAD_STATES = ("TRACKER_CANCELLED", "TRACKER_EXPIRED")


class GatewayError(Exception):
    """Safe to show to users: never contains keys or raw gateway output."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class Checkout:
    tracker: str
    url: str


@dataclass
class TrackerInfo:
    state: str
    amount_minor: int | None
    currency: str | None
    api_key: str | None
    card_hint: str | None


def _first(d, *paths):
    """First value found at any of the dotted paths (Safepay nests some fields under data.tracker, some not)."""
    for path in paths:
        cur = d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, ""):
            return cur
    return None


class SafepayGateway:
    name = "safepay"

    def __init__(self, environment: str, api_key: str, secret_key: str, webhook_secret: str = "",
                 api_base: str = "", checkout_base: str = "", refund_path: str = "", timeout: int = 30):
        env = environment if environment in HOSTS else "sandbox"
        self.environment = env
        self.api_key, self._secret, self._webhook_secret = api_key, secret_key, webhook_secret
        self.api_base = (api_base or HOSTS[env]["api"]).rstrip("/")
        self.checkout_base = checkout_base or HOSTS[env]["checkout"]
        self.refund_path = refund_path or "/order/payments/v3/{tracker}/refund"
        self.timeout = timeout

    # ------------------------------------------------------------------ HTTP
    def _call(self, method: str, path: str, body: dict | None = None, *, what: str) -> dict:
        headers = {"Content-Type": "application/json", "X-SFPY-MERCHANT-SECRET": self._secret}
        try:
            resp = requests.request(method, self.api_base + path, json=body, headers=headers, timeout=self.timeout)
        except requests.Timeout:
            raise GatewayError("PAYMENT_GATEWAY_TIMEOUT", "Safepay took too long to answer. Please try again.", 504)
        except requests.RequestException:
            log.warning("Safepay could not be reached (%s)", what)
            raise GatewayError("PAYMENT_GATEWAY_UNAVAILABLE", "Safepay could not be reached. Check the internet "
                               "connection and try again.", 503)
        if resp.status_code in (401, 403):
            raise GatewayError("PAYMENT_GATEWAY_AUTH", "Safepay rejected the API keys. Check SAFEPAY_API_KEY and "
                               "SAFEPAY_SECRET_KEY (sandbox keys for sandbox).", 503)
        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.status_code >= 400 or not isinstance(data, dict):
            detail = ""
            if isinstance(data, dict):
                errs = _first(data, "status.errors") or []
                detail = "; ".join(str(e) for e in errs)[:200] if isinstance(errs, list) else str(errs)[:200]
            log.warning("Safepay %s failed: HTTP %s %s", what, resp.status_code, detail)
            raise GatewayError("PAYMENT_GATEWAY_ERROR", f"Safepay refused the request ({what}"
                               + (f": {detail}" if detail else "") + ").", 502)
        return data

    # ------------------------------------------------------------------ steps
    def create_checkout(self, amount_minor: int, currency: str, redirect_url: str, cancel_url: str,
                        order_id: str) -> Checkout:
        session = self._call("POST", "/order/payments/v3/", {
            "merchant_api_key": self.api_key, "intent": "CYBERSOURCE", "mode": "payment",
            "currency": currency, "amount": int(amount_minor),
        }, what="create payment")
        tracker = _first(session, "data.tracker.token", "data.token")
        if not tracker:
            raise GatewayError("PAYMENT_GATEWAY_ERROR", "Safepay did not return a payment session.", 502)
        passport = self._call("POST", "/client/passport/v1/token", {}, what="checkout token")
        tbt = passport.get("data") if isinstance(passport.get("data"), str) else _first(passport, "data.token")
        if not tbt:
            raise GatewayError("PAYMENT_GATEWAY_ERROR", "Safepay did not return a checkout token.", 502)
        query = urlencode({"environment": self.environment, "tracker": tracker, "tbt": tbt, "source": "hosted",
                           "order_id": order_id, "redirect_url": redirect_url, "cancel_url": cancel_url})
        return Checkout(tracker=str(tracker), url=f"{self.checkout_base}?{query}")

    def fetch(self, tracker: str) -> TrackerInfo:
        data = self._call("GET", f"/reporter/api/v1/payments/{tracker}", what="check payment")
        state = _first(data, "data.tracker.state", "data.state") or "UNKNOWN"
        amount = _first(data, "data.tracker.purchase_totals.quote_amount.amount",
                        "data.purchase_totals.quote_amount.amount", "data.tracker.amount", "data.amount")
        currency = _first(data, "data.tracker.purchase_totals.quote_amount.currency",
                          "data.purchase_totals.quote_amount.currency", "data.tracker.currency", "data.currency")
        key = _first(data, "data.tracker.client.api_key", "data.client.api_key", "data.tracker.client")
        method = _first(data, "data.action.payment_method", "data.tracker.action.payment_method") or {}
        hint = None
        if isinstance(method, dict) and method.get("last_four"):
            hint = f"{(method.get('card_type') or method.get('scheme') or 'Card').upper()} ending {method['last_four']}"
        try:
            amount = int(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount = None
        return TrackerInfo(state=str(state), amount_minor=amount, currency=currency,
                           api_key=key if isinstance(key, str) else None, card_hint=hint)

    def refund(self, tracker: str, amount_minor: int, currency: str) -> str:
        """Returns the tracker state after the refund (e.g. TRACKER_REFUNDED). Raises GatewayError if refused."""
        data = self._call("POST", self.refund_path.format(tracker=tracker),
                          {"amount": int(amount_minor), "currency": currency}, what="refund")
        return str(_first(data, "data.tracker.state", "data.state") or "TRACKER_REFUNDED")

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        if not self._webhook_secret or not signature:
            return False
        expected = hmac.new(self._webhook_secret.encode(), raw_body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())


def gateway_status(config) -> dict:
    """For the payment page and the Super Admin: is a gateway set up? (never returns keys)"""
    if not config.get("PAYMENTS_ENABLED", True):
        return {"enabled": False, "configured": False, "environment": None, "message": "Payments are switched off."}
    missing = [k for k in ("SAFEPAY_API_KEY", "SAFEPAY_SECRET_KEY") if not config.get(k)]
    env = config.get("SAFEPAY_ENVIRONMENT") or "sandbox"
    return {"enabled": True, "configured": not missing, "environment": env, "provider": "safepay",
            "message": (f"Payments are not set up on the server yet: add {' and '.join(missing)} to backend/.env."
                        if missing else None)}


def get_gateway(config) -> SafepayGateway:
    status = gateway_status(config)
    if not status["configured"]:
        raise GatewayError("PAYMENTS_NOT_CONFIGURED", status["message"], 503)
    return SafepayGateway(config.get("SAFEPAY_ENVIRONMENT") or "sandbox", config["SAFEPAY_API_KEY"],
                          config["SAFEPAY_SECRET_KEY"], config.get("SAFEPAY_WEBHOOK_SECRET") or "",
                          config.get("SAFEPAY_API_BASE") or "", config.get("SAFEPAY_CHECKOUT_BASE") or "",
                          config.get("SAFEPAY_REFUND_PATH") or "", int(config.get("SAFEPAY_TIMEOUT_SECONDS", 30)))
