"""Phase 11 - payments (Safepay), subscriptions, admit cards by email, Excel report.

Safepay itself is replaced by a fake HTTP server (requests.request is patched), so the real client code - URLs,
headers, amounts in paisa, reading Safepay's answers - is what runs. No network, no real money.
"""
import hashlib
import hmac
import io
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage

import pytest
import requests
from openpyxl import load_workbook

from app.common.utils import utcnow
from app.extensions import db
from app.models.admit_card import AdmitCardEmail
from app.models.institution import Institution
from app.models.payment import Payment
from app.modules.admit_cards import service as admit
from app.modules.payments import emails as pay_emails
from app.modules.payments.service import add_months
from tests.conftest import SIGNUP, do_signup, login
from tests.test_phase2 import make_admin
from tests.test_phase4 import row
from tests.test_phase6 import err, make_test, set_window

API_KEY, SECRET, HOOK_SECRET = "sec_test_public", "secret_test_private", "whsec_test"


# ================================================================ fake Safepay
class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSafepay:
    def __init__(self):
        self.trackers: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.refund_fails = False
        self.down = False

    def __call__(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append((method, url, json, dict(headers or {})))
        if self.down:
            raise requests.ConnectionError()
        if (headers or {}).get("X-SFPY-MERCHANT-SECRET") != SECRET:
            return FakeResp(401, {"status": {"errors": ["unauthorized"]}})
        path = url.split("getsafepay.com", 1)[1]
        if method == "POST" and path == "/order/payments/v3/":
            assert json["merchant_api_key"] == API_KEY and json["intent"] == "CYBERSOURCE" and json["mode"] == "payment"
            token = f"track_{len(self.trackers) + 1:04d}"
            self.trackers[token] = {"state": "TRACKER_STARTED", "amount": json["amount"], "currency": json["currency"]}
            return FakeResp(200, {"data": {"tracker": {"token": token, "state": "TRACKER_STARTED"}}})
        if method == "POST" and path == "/client/passport/v1/token":
            return FakeResp(200, {"data": "tbt_shortlived"})
        if method == "GET" and path.startswith("/reporter/api/v1/payments/"):
            t = self.trackers.get(path.rsplit("/", 1)[1])
            if t is None:
                return FakeResp(404, {"status": {"errors": ["not found"]}})
            return FakeResp(200, {"data": {"state": t["state"], "client": {"api_key": t.get("api_key", API_KEY)},
                                           "purchase_totals": {"quote_amount": {"amount": t["amount"],
                                                                                "currency": t["currency"]}},
                                           "action": {"payment_method": {"card_type": "visa", "last_four": "1005"}}}})
        if method == "POST" and path.endswith("/refund"):
            tracker = path.split("/")[-2]
            if self.refund_fails:
                return FakeResp(400, {"status": {"errors": ["refund not allowed within 24 hours"]}})
            self.trackers[tracker]["state"] = "TRACKER_REFUNDED"
            assert json["amount"] == self.trackers[tracker]["amount"]
            return FakeResp(200, {"data": {"tracker": {"token": tracker, "state": "TRACKER_REFUNDED"}}})
        return FakeResp(404, {"status": {"errors": ["no route"]}})

    def set(self, n, state, **extra):
        self.trackers[f"track_{n:04d}"].update(state=state, **extra)


MAILS: list[dict] = []


@pytest.fixture
def pay(app, monkeypatch):
    """Payments on, Safepay sandbox keys set, Safepay faked, emails captured."""
    fake = FakeSafepay()
    monkeypatch.setattr(requests, "request", fake)
    app.config.update(PAYMENTS_ENABLED=True, SAFEPAY_API_KEY=API_KEY, SAFEPAY_SECRET_KEY=SECRET,
                      SAFEPAY_ENVIRONMENT="sandbox", SAFEPAY_WEBHOOK_SECRET="")
    MAILS.clear()

    def capture(to, subject, body, attachments=None):
        MAILS.append({"to": to, "subject": subject, "body": body})
        return "logged"
    monkeypatch.setattr(pay_emails, "send_mail", capture)
    return fake


def signup(client, email="admissions@ned.edu.pk", name="NED University"):
    r = do_signup(client, admin_email=email, institution_name=name)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]


def checkout(client, token, plan="monthly"):
    return client.post("/api/v1/payments/checkout",
                       json={"token": token, "plan": plan, "return_url": "http://127.0.0.1:5000/aptitude/x.html"})


def paid_signup(client, fake, plan="monthly", **kw):
    data = signup(client, **kw)
    r = checkout(client, data["payment_token"], plan)
    assert r.status_code == 201, r.get_json()
    pid = r.get_json()["data"]["payment"]["id"]
    fake.set(len(fake.trackers), "TRACKER_ENDED")
    c = client.post("/api/v1/payments/confirm", json={"token": data["payment_token"], "payment": pid})
    assert c.get_json()["data"]["payment"]["status"] == "paid"
    return data["payment_token"], pid


def super_admin(app):
    c = app.test_client()
    assert login(c, "root@assessify.com", "SuperSecret123").status_code == 200
    return c


def inst(name="NED University") -> Institution:
    db.session.expire_all()
    return Institution.query.filter_by(name=name).first()


# ================================================================ signup -> pay -> approve
def test_signup_waits_for_payment_and_login_sends_to_payment_page(app, client, pay):
    data = signup(client)
    assert data["institution"]["status"] == "awaiting_payment" and data["next"] == "payment" and data["payment_token"]
    r = login(client, SIGNUP["admin_email"], SIGNUP["password"])
    assert r.status_code == 402 and err(r) == "INSTITUTION_PAYMENT_REQUIRED"
    assert r.get_json()["error"]["details"]["payment_token"]
    bad = login(client, SIGNUP["admin_email"], "wrong-password1A!")
    assert bad.status_code == 401 and "payment_token" not in json.dumps(bad.get_json())   # nothing before the password
    sa = super_admin(app)
    listed = sa.get("/api/v1/super/institutions?status=awaiting_payment").get_json()["data"]["items"]
    assert listed[0]["payment"] is None and listed[0]["status"] == "awaiting_payment"


def test_payment_page_session_and_bad_links(app, client, pay):
    token = signup(client)["payment_token"]
    d = client.get("/api/v1/payments/session?token=" + token).get_json()["data"]
    assert d["purpose"] == "registration" and d["gateway"]["configured"] and d["gateway"]["environment"] == "sandbox"
    assert [(p["id"], p["amount"]) for p in d["plans"]] == [("monthly", 5000), ("yearly", 50000)]
    assert d["plans"][1]["saving"] == 10000
    assert SECRET not in json.dumps(d) and API_KEY not in json.dumps(d)
    assert client.get("/api/v1/payments/session?token=nonsense").status_code == 400
    assert client.get("/api/v1/payments/session?token=" + token[:-3] + "abc").status_code == 400   # tampered
    app.config["PAYMENT_LINK_DAYS"] = -1
    r = client.get("/api/v1/payments/session?token=" + token)
    assert r.status_code == 410 and err(r) == "PAYMENT_LINK_EXPIRED"


def test_checkout_builds_the_safepay_request_and_url(app, client, pay):
    token = signup(client)["payment_token"]
    assert checkout(client, token, "weekly").status_code == 422
    bad = client.post("/api/v1/payments/checkout", json={"token": token, "plan": "monthly", "return_url": "javascript:x"})
    assert bad.status_code == 422
    r = checkout(client, token, "yearly")
    assert r.status_code == 201
    d = r.get_json()["data"]
    url = d["checkout_url"]
    assert url.startswith("https://sandbox.api.getsafepay.com/embedded/?")
    for part in ("environment=sandbox", "tracker=track_0001", "tbt=tbt_shortlived", "source=hosted", "redirect_url=",
                 "cancel_url="):
        assert part in url
    assert pay.trackers["track_0001"]["amount"] == 5_000_000            # PKR 50,000 in paisa
    assert d["payment"]["amount"] == 50000 and d["payment"]["status"] == "created"
    assert all(h["X-SFPY-MERCHANT-SECRET"] == SECRET for _, _, _, h in pay.calls)


def test_confirm_is_decided_by_safepay_not_the_browser(app, client, pay):
    token = signup(client)["payment_token"]
    pid = checkout(client, token).get_json()["data"]["payment"]["id"]
    still = client.post("/api/v1/payments/confirm", json={"token": token, "payment": pid}).get_json()["data"]
    assert still["payment"]["status"] == "created" and still["institution_status"] == "awaiting_payment"
    pay.set(1, "TRACKER_ENDED")
    done = client.post("/api/v1/payments/confirm", json={"token": token, "payment": pid}).get_json()["data"]
    p = done["payment"]
    assert p["status"] == "paid" and done["institution_status"] == "pending"
    assert p["receipt_no"].startswith(f"ASY-{utcnow().year}-") and p["card_hint"] == "VISA ending 1005"
    assert len(MAILS) == 1 and MAILS[0]["subject"].startswith("Payment received")
    assert "PKR 5,000" in MAILS[0]["body"] and p["receipt_no"] in MAILS[0]["body"]
    client.post("/api/v1/payments/confirm", json={"token": token, "payment": pid})
    assert len(MAILS) == 1                                              # confirming twice: one receipt only
    r = login(client, SIGNUP["admin_email"], SIGNUP["password"])
    assert r.status_code == 403 and err(r) == "INSTITUTION_PENDING" and "payment is received" in r.get_json()["error"]["message"]
    assert checkout(client, token).status_code == 409                    # nothing more to pay


def test_wrong_amount_or_account_is_not_accepted(app, client, pay):
    token = signup(client)["payment_token"]
    pid = checkout(client, token).get_json()["data"]["payment"]["id"]
    pay.set(1, "TRACKER_ENDED", amount=100)
    p = client.post("/api/v1/payments/confirm", json={"token": token, "payment": pid}).get_json()["data"]["payment"]
    assert p["status"] == "failed" and "different amount" in p["failure_reason"]
    assert inst().status == "awaiting_payment"
    pid2 = checkout(client, token).get_json()["data"]["payment"]["id"]
    pay.set(2, "TRACKER_ENDED", api_key="sec_someone_else")
    p2 = client.post("/api/v1/payments/confirm", json={"token": token, "payment": pid2}).get_json()["data"]["payment"]
    assert p2["status"] == "failed" and "different Safepay account" in p2["failure_reason"]


def test_cancelled_and_expired_payments_email_a_retry_link_once(app, client, pay):
    token = signup(client)["payment_token"]
    pid = checkout(client, token).get_json()["data"]["payment"]["id"]
    p = client.post("/api/v1/payments/cancel", json={"token": token, "payment": pid}).get_json()["data"]["payment"]
    assert p["status"] == "cancelled" and "cancelled" in p["failure_reason"]
    client.post("/api/v1/payments/cancel", json={"token": token, "payment": pid})
    assert [m["subject"] for m in MAILS] == ["Your Assessify payment was not completed"]
    assert "institution-payment.html?token=" in MAILS[0]["body"] and "No money was taken" in MAILS[0]["body"]
    pid2 = checkout(client, token).get_json()["data"]["payment"]["id"]
    pay.set(2, "TRACKER_EXPIRED")
    p2 = client.post("/api/v1/payments/confirm", json={"token": token, "payment": pid2}).get_json()["data"]["payment"]
    assert p2["status"] == "cancelled" and "expired" in p2["failure_reason"]


def test_cancel_page_after_a_real_payment_still_counts_it(app, client, pay):
    token = signup(client)["payment_token"]
    pid = checkout(client, token).get_json()["data"]["payment"]["id"]
    pay.set(1, "TRACKER_ENDED")                     # paid, then the browser somehow reached cancel_url
    p = client.post("/api/v1/payments/cancel", json={"token": token, "payment": pid}).get_json()["data"]["payment"]
    assert p["status"] == "paid"


def test_another_institutions_token_cannot_touch_a_payment(app, client, pay):
    token_a = signup(client)["payment_token"]
    pid_a = checkout(client, token_a).get_json()["data"]["payment"]["id"]
    token_b = signup(app.test_client(), email="b@two.edu", name="Two University")["payment_token"]
    r = client.post("/api/v1/payments/confirm", json={"token": token_b, "payment": pid_a})
    assert r.status_code == 404


def test_super_admin_approves_and_subscription_starts(app, client, pay):
    paid_signup(client, pay, plan="yearly")
    sa = super_admin(app)
    i = inst()
    r = sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "approved"})
    assert r.status_code == 200
    i = inst()
    assert i.status == "approved" and i.plan == "yearly"
    assert abs((i.paid_until - add_months(utcnow(), 12)).total_seconds()) < 120
    assert MAILS[-1]["subject"] == "Your institution is approved on Assessify"
    assert "institution-login.html" in MAILS[-1]["body"] and "active until" in MAILS[-1]["body"]
    assert login(client, SIGNUP["admin_email"], SIGNUP["password"]).status_code == 200


def test_unpaid_cannot_be_approved_but_can_be_removed(app, client, pay):
    signup(client)
    sa = super_admin(app)
    i = inst()
    r = sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "approved"})
    assert r.status_code == 409 and err(r) == "NOT_PAID"
    r = sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "rejected", "note": "Spam"})
    assert r.status_code == 200 and r.get_json()["data"]["refund"] is None
    assert not any(c[1].endswith("/refund") for c in pay.calls)
    assert MAILS[-1]["subject"] == "Your Assessify registration was not approved" and "Spam" in MAILS[-1]["body"]


def test_reject_after_payment_refunds_automatically(app, client, pay):
    paid_signup(client, pay)
    sa = super_admin(app)
    i = inst()
    r = sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "rejected", "note": "Not a real institute"})
    refund = r.get_json()["data"]["refund"]
    assert refund["status"] == "refunded" and refund["amount"] == "PKR 5,000"
    assert any(m == "POST" and u.endswith("/order/payments/v3/track_0001/refund") for m, u, *_ in pay.calls)
    assert "has been refunded" in MAILS[-1]["body"] and "Not a real institute" in MAILS[-1]["body"]
    again = sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "approved"})
    assert again.status_code == 409 and err(again) == "PAYMENT_REFUNDED"


def test_failed_refund_can_be_retried_or_marked_by_hand(app, client, pay):
    paid_signup(client, pay)
    sa = super_admin(app)
    i = inst()
    pay.refund_fails = True
    r = sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "rejected"})
    refund = r.get_json()["data"]["refund"]
    assert refund["status"] == "refund_failed" and "24 hours" in refund["error"]
    assert "complete it by hand" in MAILS[-1]["body"]
    listed = sa.get("/api/v1/super/institutions").get_json()["data"]["items"][0]
    assert listed["payment"]["status"] == "refund_failed"
    pay.refund_fails = False
    d = sa.post(f"/api/v1/super/institutions/{i.id}/refund/retry", json={}).get_json()["data"]
    assert d["payment"]["status"] == "refunded" and MAILS[-1]["subject"] == "Your Assessify payment has been refunded"
    assert sa.post(f"/api/v1/super/institutions/{i.id}/refund/retry", json={}).status_code == 409

    # second institution: refunded by hand in the Safepay dashboard
    c2 = app.test_client()
    paid_signup(c2, pay, email="b@two.edu", name="Two University")
    j = inst("Two University")
    pay.refund_fails = True
    sa.patch(f"/api/v1/super/institutions/{j.id}", json={"status": "rejected"})
    d = sa.post(f"/api/v1/super/institutions/{j.id}/refund/manual", json={"note": "ref R-77"}).get_json()["data"]
    assert d["payment"]["status"] == "refunded" and "ref R-77" in d["payment"]["refund_note"]
    assert "by our team" in MAILS[-1]["body"]


def test_subscription_expiry_and_renewal(app, client, pay):
    token, _ = paid_signup(client, pay, plan="monthly")
    sa = super_admin(app)
    i = inst()
    sa.patch(f"/api/v1/super/institutions/{i.id}", json={"status": "approved"})
    admin = app.test_client()
    assert login(admin, SIGNUP["admin_email"], SIGNUP["password"]).status_code == 200
    i = inst()
    i.paid_until = utcnow() - timedelta(days=1)                         # the month ran out
    db.session.commit()
    r = admin.get("/api/v1/departments")
    assert r.status_code == 402 and err(r) == "INSTITUTION_SUBSCRIPTION_EXPIRED"
    r = login(app.test_client(), SIGNUP["admin_email"], SIGNUP["password"])
    assert r.status_code == 402 and err(r) == "INSTITUTION_SUBSCRIPTION_EXPIRED"
    renew_token = r.get_json()["error"]["details"]["payment_token"]
    s = client.get("/api/v1/payments/session?token=" + renew_token).get_json()["data"]
    assert s["purpose"] == "renewal" and s["institution"]["expired"] is True
    pid = checkout(client, renew_token, "yearly").get_json()["data"]["payment"]["id"]
    pay.set(len(pay.trackers), "TRACKER_ENDED")
    p = client.post("/api/v1/payments/confirm", json={"token": renew_token, "payment": pid}).get_json()["data"]
    assert p["payment"]["purpose"] == "renewal" and p["institution_status"] == "approved"
    i = inst()
    assert abs((i.paid_until - add_months(utcnow(), 12)).total_seconds()) < 120 and i.plan == "yearly"
    assert MAILS[-1]["subject"] == "Payment received: subscription renewed"
    assert login(app.test_client(), SIGNUP["admin_email"], SIGNUP["password"]).status_code == 200

    # renewing early adds to the end of the current period, not to today
    end = i.paid_until
    pid = checkout(client, renew_token, "monthly").get_json()["data"]["payment"]["id"]
    pay.set(len(pay.trackers), "TRACKER_ENDED")
    client.post("/api/v1/payments/confirm", json={"token": renew_token, "payment": pid})
    assert inst().paid_until == add_months(end, 1)


def test_institutions_from_before_payments_never_expire(app, client, pay):
    c = make_admin(app)                      # approved directly, no payment, paid_until stays NULL
    assert inst().paid_until is None
    assert c.get("/api/v1/departments").status_code == 200


def test_webhook_signature_and_recheck(app, client, pay):
    app.config["SAFEPAY_WEBHOOK_SECRET"] = HOOK_SECRET
    token = signup(client)["payment_token"]
    checkout(client, token)
    body = json.dumps({"type": "payment.succeeded", "data": {"tracker": "track_0001"}}).encode()
    bad = client.post("/api/v1/payments/webhook", data=body, headers={"X-SFPY-SIGNATURE": "00",
                                                                       "Content-Type": "application/json"})
    assert bad.status_code == 400
    sig = hmac.new(HOOK_SECRET.encode(), body, hashlib.sha512).hexdigest()
    ok = client.post("/api/v1/payments/webhook", data=body, headers={"X-SFPY-SIGNATURE": sig,
                                                                      "Content-Type": "application/json"})
    assert ok.status_code == 200
    assert Payment.query.one().status == "created"              # Safepay itself still says STARTED: not paid
    pay.set(1, "TRACKER_ENDED")
    client.post("/api/v1/payments/webhook", data=body, headers={"X-SFPY-SIGNATURE": sig, "Content-Type": "application/json"})
    db.session.expire_all()
    assert Payment.query.one().status == "paid" and inst().status == "pending"


def test_gateway_problems_are_clear(app, client, pay):
    token = signup(client)["payment_token"]
    app.config["SAFEPAY_SECRET_KEY"] = ""
    r = checkout(client, token)
    assert r.status_code == 503 and err(r) == "PAYMENTS_NOT_CONFIGURED" and "SAFEPAY_SECRET_KEY" in r.get_json()["error"]["message"]
    assert client.get("/api/v1/payments/session?token=" + token).get_json()["data"]["gateway"]["configured"] is False
    app.config["SAFEPAY_SECRET_KEY"] = "wrong"
    r = checkout(client, token)
    assert r.status_code == 503 and err(r) == "PAYMENT_GATEWAY_AUTH"
    app.config["SAFEPAY_SECRET_KEY"] = SECRET
    pay.down = True
    r = checkout(client, token)
    assert r.status_code == 503 and err(r) == "PAYMENT_GATEWAY_UNAVAILABLE"
    assert Payment.query.count() == 0                            # nothing half-saved


def test_several_unpaid_payments_allowed(app, client, pay):
    token = signup(client)["payment_token"]
    for _ in range(3):
        assert checkout(client, token).status_code == 201         # receipt_no NULL x3: filtered unique index
    assert Payment.query.count() == 3


def test_unpaid_signup_holds_the_name_only_for_a_while(app, client, pay):
    signup(client)
    r = do_signup(app.test_client(), admin_email="other@ned.edu.pk")
    assert r.status_code == 409
    i = inst()
    i.created_at = utcnow() - timedelta(days=8)
    db.session.commit()
    assert do_signup(app.test_client(), admin_email="other@ned.edu.pk").status_code == 201


def test_add_months_clamps_the_day():
    assert add_months(datetime(2027, 1, 31), 1) == datetime(2027, 2, 28)
    assert add_months(datetime(2028, 1, 31), 1) == datetime(2028, 2, 29)
    assert add_months(datetime(2026, 12, 15), 1) == datetime(2027, 1, 15)
    assert add_months(datetime(2026, 11, 19), 12) == datetime(2027, 11, 19)


# ================================================================ admit cards
class FakeBatch:
    """Stands in for mail_batch(); `fail` maps an address to an exception."""
    def __init__(self):
        self.sent, self.fail = [], {}

    @contextmanager
    def __call__(self):
        def send(to, subject, body, attachments=None):
            if to in self.fail:
                raise self.fail[to]
            self.sent.append({"to": to, "subject": subject, "body": body, "attachments": attachments or []})
            return "sent"
        yield send


@pytest.fixture
def cards(app, monkeypatch):
    admin = make_admin(app)
    test_id, dept = make_test(app, admin, [row(count=6)], roster=4)
    set_window(app, test_id, 60, 180)                 # starts in an hour
    batch = FakeBatch()
    monkeypatch.setattr(admit, "mail_batch", batch)
    app.config.update(MAIL_BACKEND="smtp", MAIL_SERVER="smtp.gmail.com", MAIL_USERNAME="assessify@gmail.com",
                      MAIL_PASSWORD="app-password")
    return admin, test_id, dept, batch


def admit_status(admin, test_id):
    return admin.get(f"/api/v1/admit-cards?test_id={test_id}").get_json()["data"]


def test_admit_cards_need_an_admin(app, client, cards):
    admin, test_id, *_ = cards
    assert client.get(f"/api/v1/admit-cards?test_id={test_id}").status_code == 401
    other = make_admin(app, "b@two.edu", "Two University")
    assert other.get(f"/api/v1/admit-cards?test_id={test_id}").status_code == 404
    assert other.get("/api/v1/admit-cards/1.pdf").status_code == 404


def test_send_admit_cards_with_pdf_and_schedule(app, cards):
    admin, test_id, dept, batch = cards
    s = admit_status(admin, test_id)
    assert s["can_send"] and s["with_email"] == 4 and s["counts"]["not_sent"] == 4
    r = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id, "login_url": "http://127.0.0.1:5000/aptitude/candidate-login.html"})
    d = r.get_json()["data"]
    assert r.status_code == 200 and len(d["sent"]) == 4 and d["failed"] == []
    mail = batch.sent[0]
    assert mail["subject"] == "Admit card: Entry Test (NED University)"
    name, data, mime = mail["attachments"][0]
    assert mime == "application/pdf" and data[:5] == b"%PDF-" and name.endswith(".pdf")
    body = mail["body"]
    for part in ("You are receiving this email because it contains your admit card", "Test schedule:", "Test starts",
                 "Duration:", "Access code: CAND-0001", "Second step: your date of birth",
                 "http://127.0.0.1:5000/aptitude/candidate-login.html", "PKT, UTC+05:00"):
        assert part in body, part
    s = admit_status(admin, test_id)
    assert s["counts"]["sent"] == 4 and not s["can_send"] and "already has their admit card" in s["blocked_reason"]
    assert s["can_resend"]
    again = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id, "resend": True}).get_json()["data"]
    assert len(again["sent"]) == 4 and AdmitCardEmail.query.first().attempts == 2


def test_no_email_on_roster_blocks_the_button_with_a_reason(app, cards):
    admin, test_id, dept, batch = cards
    for cid in [c["id"] for c in admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"]]:
        r = admin.put(f"/api/v1/roster/{cid}", json={"full_name": "Someone", "email": "", "roll_number": f"R-{cid}",
                                                      "date_of_birth": "2008-01-01", "department_id": dept})
        assert r.status_code == 200, r.get_json()
    s = admit_status(admin, test_id)
    assert not s["can_send"] and "No candidate on this roster has an email address" in s["blocked_reason"]
    assert len(s["no_email"]) == 4 and s["no_email"][0]["candidate"]["id"]
    r = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id})
    assert r.status_code == 409 and err(r) == "ADMIT_CARDS_BLOCKED"


def test_problems_are_reported_by_name_with_the_reason(app, cards, monkeypatch):
    from app.common import email_rules
    from app.common.mailer import MailError
    admin, test_id, dept, batch = cards
    rows = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"]
    by_roll = {r["roll_number"]: r for r in rows}

    def set_email(roll, email):
        r = by_roll[roll]
        return admin.put(f"/api/v1/roster/{r['id']}", json={"full_name": r["full_name"], "email": email, "roll_number": roll,
                                                            "date_of_birth": r["date_of_birth"], "department_id": dept})
    set_email("R-2", "")                                                  # no email
    set_email("R-3", "c3@no-such-domain-xyz.pk")                          # domain has no mail server
    monkeypatch.setattr(email_rules, "accepts_mail", lambda d: d != "no-such-domain-xyz.pk")
    batch.fail["c4@mail.com"] = MailError("The mail server refused this address (it may not exist).", "recipient")
    d = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id}).get_json()["data"]
    assert [x["full_name"] for x in d["sent"]] == ["Candidate 1"]
    failed = {x["full_name"]: x["reason"] for x in d["failed"]}
    assert "does not exist or cannot receive email" in failed["Candidate 3"]
    assert "refused this address" in failed["Candidate 4"]
    assert [p["full_name"] for p in d["no_email"]] == ["Candidate 2"]
    s = d["status"]
    assert {p["full_name"] for p in s["problems"]} == {"Candidate 3", "Candidate 4"} and s["can_send"]

    # fix candidate 4's email -> only the people still missing a card are sent next time
    batch.fail.clear()
    set_email("R-4", "c4-fixed@mail.com")
    d = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id}).get_json()["data"]
    assert {x["full_name"] for x in d["sent"]} == {"Candidate 4"}
    assert {x["full_name"] for x in d["failed"]} == {"Candidate 3"}


def test_a_broken_mail_login_stops_the_batch(app, cards):
    from app.common.mailer import MailError
    admin, test_id, dept, batch = cards
    batch.fail["c1@mail.com"] = MailError("The mail server refused the username / password.", "setup")
    d = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id}).get_json()["data"]
    assert "username / password" in d["stopped"] and len(d["failed"]) == 1 and d["sent"] == []
    assert d["status"]["counts"]["not_sent"] == 3                         # the others were not tried


def test_email_changed_after_sending_counts_as_not_sent(app, cards):
    admin, test_id, dept, batch = cards
    admin.post("/api/v1/admit-cards/send", json={"test_id": test_id})
    r = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"][0]
    admin.put(f"/api/v1/roster/{r['id']}", json={"full_name": r["full_name"], "email": "new@mail.com",
                                                 "roll_number": r["roll_number"], "date_of_birth": r["date_of_birth"],
                                                 "department_id": dept})
    s = admit_status(admin, test_id)
    assert s["counts"]["changed"] == 1 and s["can_send"]
    d = admin.post("/api/v1/admit-cards/send", json={"test_id": test_id}).get_json()["data"]
    assert [x["email"] for x in d["sent"]] == ["new@mail.com"]


def test_after_the_test_ends_sending_is_blocked(app, cards):
    admin, test_id, *_ = cards
    set_window(app, test_id, -120, -10)
    s = admit_status(admin, test_id)
    assert not s["can_send"] and "test has ended" in s["blocked_reason"] and not s["can_resend"]
    assert admin.post("/api/v1/admit-cards/send", json={"test_id": test_id}).status_code == 409


def test_mail_not_set_up_blocks_with_the_reason(app, cards):
    admin, test_id, *_ = cards
    app.config["MAIL_SERVER"] = ""
    s = admit_status(admin, test_id)
    assert not s["can_send"] and "MAIL_SERVER" in s["blocked_reason"]


def test_admit_card_pdf_download(app, cards):
    admin, test_id, *_ = cards
    cid = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"][0]["id"]
    r = admin.get(f"/api/v1/admit-cards/{cid}.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:5] == b"%PDF-"
    assert r.headers["Cache-Control"] == "no-store"


def _bounce(recipient: str, status: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"
    msg["Subject"] = "Delivery Status Notification (Failure)"
    msg["Date"] = "Wed, 18 Nov 2099 10:00:00 +0000"
    msg["X-Failed-Recipients"] = recipient
    msg.set_content(f"Address not found\n\nYour message wasn't delivered to {recipient}.")
    return msg.as_bytes()


def test_parse_bounce_reasons():
    assert admit.parse_bounce(_bounce("x@gmail.com", "5.1.1")) == [
        ("x@gmail.com", "Address not found: this mailbox does not exist.")]
    plain = EmailMessage()
    plain["Subject"] = "hello"
    plain.set_content("not a bounce")
    assert admit.parse_bounce(plain.as_bytes()) == []


def test_check_bounces_marks_cards_with_the_reason(app, cards, monkeypatch):
    admin, test_id, dept, batch = cards
    admin.post("/api/v1/admit-cards/send", json={"test_id": test_id})
    raw = _bounce("c2@mail.com", "5.1.1")

    class FakeImap:
        def __init__(self, *a, **k):
            pass

        def login(self, user, password):
            assert user == "assessify@gmail.com"

        def select(self, box, readonly=False):
            assert readonly is True                                     # never changes the mailbox
            return "OK", [b"1"]

        def search(self, charset, criteria):
            return "OK", [b"1"]

        def fetch(self, num, what):
            return "OK", [(b"1 (BODY[] {123}", raw)]

        def logout(self):
            pass
    monkeypatch.setattr(admit.imaplib, "IMAP4_SSL", FakeImap)
    d = admin.post("/api/v1/admit-cards/check-bounces", json={"test_id": test_id}).get_json()["data"]
    assert [(b["full_name"], b["reason"]) for b in d["bounced"]] == [
        ("Candidate 2", "Address not found: this mailbox does not exist.")]
    s = d["status"]
    assert s["counts"]["bounced"] == 1 and s["problems"][0]["state"] == "bounced" and s["can_send"]


# ================================================================ Excel report
def test_excel_report(app, cards):
    admin, test_id, dept, _ = cards
    r = admin.get(f"/api/v1/reports/tests/{test_id}/export.xlsx")
    assert r.status_code == 200 and r.headers["Content-Disposition"].endswith('.xlsx"') or "xlsx" in r.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ["Summary", "Results", "By field", "By subject"]
    results = wb["Results"]
    assert [c.value for c in results[1]][:3] == ["Rank", "Name", "Roll number"]
    assert results.max_row == 5                                        # header + 4 candidates
    summary = {row[0].value: row[1].value for row in wb["Summary"].iter_rows() if row[0].value}
    assert summary["Test"] == "Entry Test" and summary["Candidates on roster"] == 4
    csv_rows = admin.get(f"/api/v1/reports/tests/{test_id}/export.csv").get_data(as_text=True).strip().splitlines()
    assert len(csv_rows) == results.max_row


def test_excel_keeps_formula_looking_names_as_text(app, cards):
    admin, test_id, dept, _ = cards
    r = admin.get(f"/api/v1/roster?test_id={test_id}").get_json()["data"]["items"][0]
    admin.put(f"/api/v1/roster/{r['id']}", json={"full_name": "=HYPERLINK(\"http://evil\")", "email": r["email"],
                                                 "roll_number": r["roll_number"], "date_of_birth": r["date_of_birth"],
                                                 "department_id": dept})
    wb = load_workbook(io.BytesIO(admin.get(f"/api/v1/reports/tests/{test_id}/export.xlsx").data))
    cell = next(c for row in wb["Results"].iter_rows(min_row=2) for c in row if c.value and "HYPERLINK" in str(c.value))
    assert cell.data_type == "s"


def test_confirm_finds_payment_when_safepay_mangles_the_return_address(app, client, pay):
    """Safepay can add '?tracker=...' after our own query, so 'payment' arrives as '1?tracker=track_0001'."""
    token = signup(client)["payment_token"]
    pid = checkout(client, token).get_json()["data"]["payment"]["id"]
    pay.set(1, "TRACKER_ENDED")
    r = client.post("/api/v1/payments/confirm", json={"token": token, "payment": f"{pid}?tracker=track_0001"})
    assert r.status_code == 200 and r.get_json()["data"]["payment"]["status"] == "paid"


def test_confirm_falls_back_to_tracker_then_newest_open_payment(app, client, pay):
    token = signup(client)["payment_token"]
    checkout(client, token)
    pay.set(1, "TRACKER_STARTED")
    by_tracker = client.post("/api/v1/payments/confirm", json={"token": token, "tracker": "track_0001"})
    assert by_tracker.status_code == 200
    nothing = client.post("/api/v1/payments/confirm", json={"token": token})          # no id, no tracker
    assert nothing.status_code == 200 and nothing.get_json()["data"]["payment"]["status"] == "created"
    other = signup(client, email="admissions@fast.edu.pk", name="FAST University")["payment_token"]
    assert client.post("/api/v1/payments/confirm", json={"token": other}).status_code == 404   # never another's


def test_reset_admin_password_script(app, monkeypatch, capsys):
    import reset_admin_password as script
    from app.models.user import User
    monkeypatch.setattr(script, "create_app", lambda: app)
    answers = iter(["BrandNewPass123", "BrandNewPass123"])
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr(script.sys, "argv", ["x", "root@assessify.com"])
    assert script.main() == 0
    assert "root@assessify.com" in capsys.readouterr().out
    db.session.expire_all()
    assert User.query.filter_by(email="root@assessify.com").first().check_password("BrandNewPass123")
    monkeypatch.setattr(script.sys, "argv", ["x", "nobody@x.com"])
    assert script.main() == 1
