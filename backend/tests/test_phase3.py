"""Phase 3 - PDF upload, AI generation (MOCKED provider - no network, no quota used), draft review, question bank."""
import io
import json
import re

import pytest
import requests

from app.ai import errors as ai_errors
from app.ai.providers import AIProvider, OpenAICompatibleProvider, get_provider
from app.extensions import db
from app.models.institution import Institution
from app.models.question import GenerationAttempt, Question
from app.modules.questions import generator, pdf, service
from tests.conftest import SIGNUP, login
from tests.pdf_factory import SAMPLE_TEXT, blank_pdf, encrypted_pdf, make_pdf, mixed_pdf, photo_pdf
from tests.test_phase2 import DEPT, make_admin

GEN = "/api/v1/questions/generate"
BANK = "/api/v1/questions/bank"


# ------------------------------------------------------------------ fake AI provider (tests only)
class FakeProvider(AIProvider):
    """Replies are strings, exceptions, or callables(prompt)->str. The last reply repeats."""
    name, model = "fake", "fake-model"

    def __init__(self, *replies, vision=False):
        self.replies, self.calls, self.supports_images, self.image_calls = list(replies), 0, vision, []

    def complete(self, system, user, images=None):
        self.calls += 1
        if images:
            self.image_calls.append(len(images))
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return r(user) if callable(r) else r


_counter = {"n": 0}


def mcq_items(n):
    items = []
    for _ in range(n):
        _counter["n"] += 1
        k = _counter["n"]
        items.append({"question": f"Question number {k}: where does photosynthesis take place?",
                      "options": [f"Chloroplast {k}", f"Nucleus {k}", f"Ribosome {k}", f"Vacuole {k}"],
                      "correct_index": 0, "explanation": "The source says chloroplasts.", "topic": "Photosynthesis"})
    return items


def smart_reply(prompt):
    """Answers exactly the number of questions the prompt asks for (like a real model would)."""
    n = int(re.search(r"Write (\d+) ", prompt).group(1))
    return json.dumps({"questions": mcq_items(n)})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(generator, "_sleep", lambda s: None)


@pytest.fixture()
def fake(monkeypatch):
    holder = {"p": FakeProvider(smart_reply)}
    monkeypatch.setattr(service, "get_provider", lambda cfg: holder["p"])
    return holder


def setup_admin(app, email="admissions@ned.edu.pk", name="NED University"):
    c = make_admin(app, email, name)
    dept = c.post("/api/v1/departments", json={**DEPT, "subjects": ["Biology", "Physics"]}).get_json()["data"]["department"]
    return c, dept


def upload(c, dept, data=None, filename="notes.pdf", **form):
    fields = {"department_id": str(dept["id"]), "subject": "Biology", "question_type": "mcq",
              "difficulty": "medium", "count": "5", "marks": "2"}
    fields.update({k: str(v) for k, v in form.items()})
    if data is not False:
        fields["file"] = (io.BytesIO(make_pdf() if data is None else data), filename)
    return c.post(GEN, data=fields, content_type="multipart/form-data")


def gen_ok(c, dept, **form):
    r = upload(c, dept, **form)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]["attempt"]


# ------------------------------------------------------------------ PDF processing
def test_valid_pdf_generates_drafts(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    assert a["status"] == "completed" and a["generated_count"] == 5 and len(a["questions"]) == 5
    assert a["source"]["filename"] == "notes.pdf" and a["source"]["pages"] == 1 and a["source"]["characters"] > 300
    assert all(q["status"] == "draft" for q in a["questions"])          # never auto-approved
    assert a["questions"][0]["marks"] == 2 and a["questions"][0]["subject"] == "Biology"
    assert a["provider"] == "fake" and a["department_name"] == DEPT["name"]


def test_prompt_contains_source_text_and_rules(app, fake):
    seen = {}
    fake["p"] = FakeProvider(lambda p: (seen.setdefault("p", p), smart_reply(p))[1])
    c, dept = setup_admin(app)
    gen_ok(c, dept, focus="Focus on chloroplasts")
    assert "chloroplasts, which contain the green pigment" in seen["p"]
    assert "Focus on chloroplasts" in seen["p"] and "exactly 4 options" in seen["p"]


def test_not_a_pdf_rejected(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, data=b"Hello, I am a text file pretending to be a PDF")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "INVALID_PDF"


def test_corrupted_pdf_rejected(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, data=b"%PDF-1.4\nthis is garbage and not really a pdf at all")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "INVALID_PDF"
    assert "Traceback" not in r.get_data(as_text=True)


def test_empty_upload_and_missing_file(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, data=b"")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "EMPTY_FILE"
    r = upload(c, dept, data=False)
    assert r.status_code == 422 and "file" in r.get_json()["error"]["details"]


def test_unsupported_file_type(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, data=make_pdf(), filename="notes.docx")
    assert r.status_code == 415 and r.get_json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_oversized_upload(app, fake):
    app.config["MAX_CONTENT_LENGTH"] = 2000
    c, dept = setup_admin(app)
    r = upload(c, dept, data=make_pdf(pages=5))
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "FILE_TOO_LARGE"


def test_pdf_without_text(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, data=blank_pdf())
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "PDF_NO_TEXT"
    assert "Please upload another PDF" in r.get_json()["error"]["message"]   # no text and no page pictures


def test_encrypted_pdf(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, data=encrypted_pdf("secret"))
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "PDF_ENCRYPTED"
    # "protected" PDFs that open without a password are fine
    assert upload(c, dept, data=encrypted_pdf("")).status_code == 201


def test_filename_is_sanitised(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, filename="../../etc/passwd.pdf")
    assert a["source"]["filename"] == "passwd.pdf"
    assert pdf.display_name("C:\\Users\\x\\secret notes.pdf") == "secret notes.pdf"


def test_long_text_is_cut_to_source_limit(app, fake):
    app.config["SOURCE_MAX_CHARS"] = 500
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, data=make_pdf(pages=4))
    with app.app_context():
        att = db.session.get(GenerationAttempt, a["id"])
        assert len(att.source_text) <= 500 and att.source_truncated is True


def test_form_validation(app, fake):
    c, dept = setup_admin(app)
    r = upload(c, dept, subject="Chemistry", question_type="essay", difficulty="extreme", count=999, marks=0)
    assert r.status_code == 422
    assert set(r.get_json()["error"]["details"]) == {"subject", "question_type", "difficulty", "count", "marks"}
    r = upload(c, dept, department_id="abc")
    assert r.status_code == 422 and "department_id" in r.get_json()["error"]["details"]


# ------------------------------------------------------------------ AI generation behaviour
def test_malformed_json_retries_are_bounded(app, fake):
    app.config["AI_MAX_RETRIES"] = 2
    fake["p"] = FakeProvider("Sure! Here are your questions: (not json)")
    c, dept = setup_admin(app)
    r = upload(c, dept)
    body = r.get_json()["error"]
    assert r.status_code == 502 and body["code"] == "AI_BAD_RESPONSE"
    assert fake["p"].calls == 3                                  # 1 try + 2 retries, then stop
    with app.app_context():                                      # failed attempt is still recorded, safely
        att = db.session.get(GenerationAttempt, body["details"]["attempt_id"])
        assert att.status == "failed" and att.error_code == "AI_BAD_RESPONSE" and att.questions == []


def test_malformed_then_valid(app, fake):
    fake["p"] = FakeProvider("{broken json", smart_reply)
    c, dept = setup_admin(app)
    assert gen_ok(c, dept)["generated_count"] == 5 and fake["p"].calls == 2


def test_markdown_fences_letters_and_labels_are_accepted(app, fake):
    reply = "```json\n" + json.dumps({"questions": [
        {"question": "Which pigment absorbs light energy?", "options": ["A) Chlorophyll", "B) Haemoglobin",
         "C) Keratin", "D) Melanin"], "answer": "A"},
        {"question": "Which gas is released as a by-product?", "options": ["Nitrogen", "Oxygen", "Helium", "Argon"],
         "correct_answer": "Oxygen"}]}) + "\n```"
    fake["p"] = FakeProvider(reply)
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, count=2)
    q1, q2 = a["questions"]
    assert q1["options"][0] == "Chlorophyll" and q1["correct_index"] == 0 and q2["correct_index"] == 1


def test_invalid_items_are_discarded(app, fake):
    good = mcq_items(2)
    bad = [
        {"question": "Missing options entirely?"},                                            # no options
        {"options": ["a", "b", "c", "d"], "correct_index": 0},                               # no question
        {"question": "Only three options here?", "options": ["x", "y", "z"], "correct_index": 0},
        {"question": "Duplicate options present?", "options": ["x", "x", "y", "z"], "correct_index": 0},
        {"question": "Answer index out of range?", "options": ["a", "b", "c", "d"], "correct_index": 7},
        "not even an object",
    ]
    fake["p"] = FakeProvider(json.dumps({"questions": good + bad}))
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, count=5)
    assert a["status"] == "partial" and a["generated_count"] == 2 and a["discarded_count"] >= 6


def test_true_false_generation(app, fake):
    fake["p"] = FakeProvider(json.dumps({"questions": [
        {"question": "Oxygen is released during the light reactions.", "answer": True},
        {"question": "The Calvin cycle takes place in the nucleus.", "answer": "false"}]}))
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, question_type="true_false", count=2)
    assert [q["options"] for q in a["questions"]] == [["True", "False"]] * 2
    assert [q["correct_index"] for q in a["questions"]] == [0, 1]


@pytest.mark.parametrize("exc,status,code", [
    (ai_errors.timeout(), 504, "AI_TIMEOUT"),
    (ai_errors.unavailable(), 503, "AI_UNAVAILABLE"),
    (ai_errors.auth_failed(), 503, "AI_AUTH_FAILED"),
])
def test_provider_failures(app, fake, exc, status, code):
    app.config["AI_MAX_RETRIES"] = 2
    fake["p"] = FakeProvider(exc)
    c, dept = setup_admin(app)
    r = upload(c, dept)
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    assert fake["p"].calls == (1 if code == "AI_AUTH_FAILED" else 3)    # auth errors are not retried


def test_rate_limit_quota_is_not_retried(app, fake):
    fake["p"] = FakeProvider(ai_errors.rate_limited(None))
    c, dept = setup_admin(app)
    r = upload(c, dept)
    assert r.status_code == 429 and r.get_json()["error"]["code"] == "AI_RATE_LIMITED" and fake["p"].calls == 1


def test_short_rate_limit_is_retried(app, fake):
    fake["p"] = FakeProvider(ai_errors.rate_limited(1), smart_reply)
    c, dept = setup_admin(app)
    assert gen_ok(c, dept)["generated_count"] == 5 and fake["p"].calls == 2


def test_missing_configuration(app):
    c, dept = setup_admin(app)
    for provider, key in (("none", ""), ("gemini", ""), ("bogus", "x")):
        app.config.update(AI_PROVIDER=provider, GEMINI_API_KEY=key)
        r = upload(c, dept)
        assert r.status_code == 503 and r.get_json()["error"]["code"] == "AI_NOT_CONFIGURED"
    with app.app_context():
        assert GenerationAttempt.query.count() == 0          # nothing recorded when AI is switched off


def test_ai_status_never_leaks_key(app):
    c, _ = setup_admin(app)
    app.config.update(AI_PROVIDER="gemini", GEMINI_API_KEY="AIza-super-secret-key", AI_MODEL="")
    r = c.get("/api/v1/questions/ai-status")
    d = r.get_json()["data"]
    assert d == {"provider": "gemini", "model": "gemini-3.5-flash-lite", "configured": True, "message": None,
                 "reads_images": True}
    assert "super-secret" not in r.get_data(as_text=True)


def test_duplicate_generation_in_progress(app, fake):
    c, dept = setup_admin(app)
    first = gen_ok(c, dept)
    with app.app_context():
        db.session.get(GenerationAttempt, first["id"]).status = "processing"    # pretend it is still running
        db.session.commit()
    r = upload(c, dept)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "GENERATION_IN_PROGRESS"


# ------------------------------------------------------------------ provider HTTP layer (requests is mocked)
class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _chat(content, finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


@pytest.mark.parametrize("resp,code", [
    (FakeResp(401), "AI_AUTH_FAILED"),
    (FakeResp(429, headers={"Retry-After": "5"}), "AI_RATE_LIMITED"),
    (FakeResp(500), "AI_UNAVAILABLE"),
    (FakeResp(404), "AI_REQUEST_REJECTED"),
    (FakeResp(200, None), "AI_BAD_RESPONSE"),
    (FakeResp(200, _chat("   ")), "AI_BAD_RESPONSE"),
    (requests.Timeout(), "AI_TIMEOUT"),
    (requests.ConnectionError(), "AI_UNAVAILABLE"),
])
def test_openai_compatible_errors(monkeypatch, resp, code):
    def post(*a, **k):
        if isinstance(resp, Exception):
            raise resp
        return resp
    monkeypatch.setattr(requests, "post", post)
    p = OpenAICompatibleProvider("x", "https://example.invalid/v1", "m", "KEY", json_mode=False, timeout=5)
    with pytest.raises(ai_errors.AIError) as e:
        p.complete("sys", "user")
    assert e.value.code == code
    assert "KEY" not in e.value.message
    if code == "AI_RATE_LIMITED":
        assert e.value.retry_after == 5


def test_openai_compatible_request_shape(monkeypatch):
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers, timeout=timeout)
        return FakeResp(200, _chat('{"questions": []}'))
    monkeypatch.setattr(requests, "post", post)
    cfg = {"AI_PROVIDER": "groq", "GROQ_API_KEY": "gsk_test", "AI_TIMEOUT_SECONDS": 33}
    p = get_provider(cfg)
    assert p.complete("sys", "hello") == '{"questions": []}'
    assert sent["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer gsk_test" and sent["timeout"] == 33
    assert sent["body"]["response_format"] == {"type": "json_object"}
    assert get_provider({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k"}).base_url.startswith(
        "https://generativelanguage.googleapis.com/")
    assert get_provider({"AI_PROVIDER": "ollama"})._api_key is None               # local model: no key needed


# ------------------------------------------------------------------ lifecycle
def test_lifecycle_draft_approve_reject_bank(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    ids = [q["id"] for q in a["questions"]]
    assert c.get(BANK).get_json()["data"]["items"] == []                         # drafts are not in the bank

    r = c.post(f"/api/v1/questions/{ids[0]}/approve")
    assert r.status_code == 200 and r.get_json()["data"]["question"]["status"] == "approved"
    assert r.get_json()["data"]["question"]["reviewed_by"] == SIGNUP["admin_name"]
    r = c.post(f"/api/v1/questions/{ids[1]}/reject", json={"reason": "Ambiguous wording"})
    assert r.get_json()["data"]["question"]["status"] == "rejected"
    assert r.get_json()["data"]["question"]["rejection_reason"] == "Ambiguous wording"

    bank = c.get(BANK).get_json()["data"]
    assert [q["id"] for q in bank["items"]] == [ids[0]] and bank["summary"]["total"] == 1

    # decisions are final for approved questions
    assert c.post(f"/api/v1/questions/{ids[0]}/reject").status_code == 409
    assert c.post(f"/api/v1/questions/{ids[0]}/approve").status_code == 409
    assert c.put(f"/api/v1/questions/{ids[0]}", json={"text": "Changed text here?", "options": ["a", "b"],
                                                      "correct_index": 0}).status_code == 409
    assert c.post(f"/api/v1/questions/{ids[1]}/approve").status_code == 409        # rejected -> regenerate instead

    detail = c.get(f"/api/v1/questions/attempts/{a['id']}").get_json()["data"]["attempt"]
    assert detail["counts"]["approved"] == 1 and detail["counts"]["rejected"] == 1 and detail["counts"]["draft"] == 3


def test_edit_draft_validates(app, fake):
    c, dept = setup_admin(app)
    qid = gen_ok(c, dept)["questions"][0]["id"]
    r = c.put(f"/api/v1/questions/{qid}", json={"text": "short", "options": ["same", "same"], "correct_index": 5,
                                                  "difficulty": "impossible", "marks": 0})
    assert r.status_code == 422
    assert {"text", "options", "difficulty", "marks"} <= set(r.get_json()["error"]["details"])
    good = {"text": "Where in the plant cell does photosynthesis happen?", "options": ["Chloroplast", "Nucleus", "Wall"],
            "correct_index": 0, "explanation": "Chloroplasts hold chlorophyll.", "topic": "Cells",
            "difficulty": "hard", "marks": 3}
    q = c.put(f"/api/v1/questions/{qid}", json=good).get_json()["data"]["question"]
    assert q["is_edited"] and q["options"] == good["options"] and q["difficulty"] == "hard" and q["marks"] == 3
    assert q["status"] == "draft"                                                  # editing never approves
    assert c.put(f"/api/v1/questions/{qid}", data="nope").status_code == 400


def test_invalid_question_cannot_be_approved(app, fake):
    c, dept = setup_admin(app)
    att = gen_ok(c, dept)
    qid = att["questions"][0]["id"]
    with app.app_context():                     # simulate bad data that slipped into the database
        q = db.session.get(Question, qid)
        q.options, q.correct_index = ["only one"], 3
        db.session.commit()
    r = c.post(f"/api/v1/questions/{qid}/approve")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "QUESTION_INVALID"
    assert c.get(BANK).get_json()["data"]["items"] == []
    r = c.post(f"/api/v1/questions/attempts/{att['id']}/approve-all").get_json()["data"]
    assert qid in [s["id"] for s in r["skipped"]] and len(r["approved"]) == 4


def test_regenerate_single_question(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    old = a["questions"][0]
    r = c.post(f"/api/v1/questions/{old['id']}/regenerate")
    assert r.status_code == 201
    new = r.get_json()["data"]["question"]
    assert new["status"] == "draft" and new["regenerated_from_id"] == old["id"] and new["text"] != old["text"]
    detail = c.get(f"/api/v1/questions/attempts/{a['id']}").get_json()["data"]["attempt"]
    assert old["id"] not in [q["id"] for q in detail["questions"]]                # hidden by default
    hist = c.get(f"/api/v1/questions/attempts/{a['id']}?include_replaced=1").get_json()["data"]["attempt"]
    replaced = next(q for q in hist["questions"] if q["id"] == old["id"])
    assert replaced["status"] == "replaced" and replaced["replaced_by_id"] == new["id"]
    assert c.get(BANK).get_json()["data"]["items"] == []                          # regeneration never approves


def test_regenerate_never_touches_approved(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    qid = a["questions"][0]["id"]
    c.post(f"/api/v1/questions/{qid}/approve")
    r = c.post(f"/api/v1/questions/{qid}/regenerate")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "INVALID_TRANSITION"
    with app.app_context():
        assert db.session.get(Question, qid).status == "approved"


def test_failed_regeneration_changes_nothing(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    qid = a["questions"][0]["id"]
    fake["p"] = FakeProvider(ai_errors.unavailable())
    r = c.post(f"/api/v1/questions/{qid}/regenerate")
    assert r.status_code == 503
    with app.app_context():
        assert db.session.get(Question, qid).status == "draft" and Question.query.count() == 5


def test_regenerate_attempt_replaces_rejected_only(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    q = [x["id"] for x in a["questions"]]
    c.post(f"/api/v1/questions/{q[0]}/approve")
    c.post(f"/api/v1/questions/{q[1]}/reject")
    c.post(f"/api/v1/questions/{q[2]}/reject")
    d = c.post(f"/api/v1/questions/attempts/{a['id']}/regenerate").get_json()["data"]
    assert d["replaced"] == 2 and d["added"] == 0
    statuses = {x["id"]: x["status"] for x in d["attempt"]["questions"]}
    assert statuses[q[0]] == "approved" and q[1] not in statuses and q[2] not in statuses
    assert d["attempt"]["counts"]["draft"] == 5 - 1                                # 2 old drafts + 2 new
    r = c.post(f"/api/v1/questions/attempts/{a['id']}/regenerate")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "NOTHING_TO_REGENERATE"


def test_failed_attempt_can_be_retried(app, fake):
    fake["p"] = FakeProvider(ai_errors.rate_limited(None))
    c, dept = setup_admin(app)
    attempt_id = upload(c, dept).get_json()["error"]["details"]["attempt_id"]
    fake["p"] = FakeProvider(smart_reply)
    d = c.post(f"/api/v1/questions/attempts/{attempt_id}/regenerate").get_json()["data"]
    assert d["added"] == 5 and d["attempt"]["status"] == "completed" and d["attempt"]["error"] is None


def test_approve_all(app, fake):
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    c.post(f"/api/v1/questions/{a['questions'][0]['id']}/reject")
    d = c.post(f"/api/v1/questions/attempts/{a['id']}/approve-all").get_json()["data"]
    assert len(d["approved"]) == 4 and d["skipped"] == []
    assert c.get(BANK).get_json()["data"]["total"] == 4


# ------------------------------------------------------------------ question bank
def test_bank_filters_and_pagination(app, fake):
    c, dept = setup_admin(app)
    a1 = gen_ok(c, dept, count=6)                                              # Biology, mcq, medium
    a2 = gen_ok(c, dept, subject="Physics", difficulty="hard", count=3)
    for a in (a1, a2):
        c.post(f"/api/v1/questions/attempts/{a['id']}/approve-all")

    d = c.get(BANK + "?per_page=4").get_json()["data"]
    assert d["total"] == 9 and d["pages"] == 3 and len(d["items"]) == 4 and d["page"] == 1
    d2 = c.get(BANK + "?per_page=4&page=3").get_json()["data"]
    assert len(d2["items"]) == 1
    assert c.get(BANK + "?difficulty=hard").get_json()["data"]["total"] == 3
    assert c.get(BANK + "?subject=physics").get_json()["data"]["total"] == 3
    assert c.get(BANK + "?question_type=true_false").get_json()["data"]["total"] == 0
    assert c.get(BANK + f"?department_id={dept['id']}&level=Undergraduate").get_json()["data"]["total"] == 9
    assert c.get(BANK + "?level=PhD").get_json()["data"]["total"] == 0
    assert c.get(BANK + "?topic=photo").get_json()["data"]["total"] == 9
    one = d["items"][0]["text"][:20]
    assert c.get(BANK + "?q=" + one).get_json()["data"]["total"] >= 1
    s = d["summary"]
    assert s["by_difficulty"] == {"medium": 6, "hard": 3} and s["by_subject"] == {"Biology": 6, "Physics": 3}
    for bad in ("difficulty=x", "level=x", "question_type=x", "department_id=x", "page=x"):
        assert c.get(BANK + "?" + bad).status_code == 400


def test_attempt_list_pagination_and_filters(app, fake):
    c, dept = setup_admin(app)
    for _ in range(3):
        gen_ok(c, dept, count=1)
    d = c.get("/api/v1/questions/attempts?per_page=2").get_json()["data"]
    assert d["total"] == 3 and len(d["items"]) == 2 and "source_text" not in json.dumps(d)
    assert c.get("/api/v1/questions/attempts?status=failed").get_json()["data"]["total"] == 0
    assert c.get("/api/v1/questions/attempts?q=notes").get_json()["data"]["total"] == 3
    assert c.get("/api/v1/questions/attempts?status=bogus").status_code == 400


def test_meta_lists_phase3_options(client):
    d = client.get("/api/v1/meta").get_json()["data"]
    assert [t["value"] for t in d["question_types"]] == ["mcq", "true_false"]
    assert [t["value"] for t in d["difficulties"]] == ["easy", "medium", "hard"]
    assert d["generation_limits"]["max_questions"] >= 1


# ------------------------------------------------------------------ security
ENDPOINTS = [("get", "/api/v1/questions/ai-status"), ("post", GEN), ("post", "/api/v1/questions/check-pdf"), ("get", "/api/v1/questions/attempts"),
             ("get", "/api/v1/questions/attempts/1"), ("post", "/api/v1/questions/attempts/1/approve-all"),
             ("post", "/api/v1/questions/attempts/1/regenerate"), ("get", BANK), ("get", "/api/v1/questions/1"),
             ("put", "/api/v1/questions/1"), ("post", "/api/v1/questions/1/approve"),
             ("post", "/api/v1/questions/1/reject"), ("post", "/api/v1/questions/1/regenerate")]


def test_unauthenticated_and_wrong_role(client):
    for method, url in ENDPOINTS:
        assert getattr(client, method)(url).status_code == 401, url
    login(client, "root@assessai.com", "SuperSecret123")                  # super admin: no institution
    for method, url in ENDPOINTS:
        assert getattr(client, method)(url).status_code == 403, url


def test_institutions_are_isolated(app, fake):
    a, dept_a = setup_admin(app, "a@one.edu", "One University")
    b, dept_b = setup_admin(app, "b@two.edu", "Two University")
    att = gen_ok(a, dept_a)
    qid = att["questions"][0]["id"]
    a.post(f"/api/v1/questions/{qid}/approve")
    q2 = att["questions"][1]["id"]

    assert b.get("/api/v1/questions/attempts").get_json()["data"]["items"] == []
    assert b.get(BANK).get_json()["data"]["items"] == [] and b.get(BANK).get_json()["data"]["summary"]["total"] == 0
    assert b.get(f"/api/v1/questions/attempts/{att['id']}").status_code == 404
    assert b.post(f"/api/v1/questions/attempts/{att['id']}/approve-all").status_code == 404
    assert b.post(f"/api/v1/questions/attempts/{att['id']}/regenerate").status_code == 404
    for url in (f"/api/v1/questions/{q2}", f"/api/v1/questions/{qid}"):
        assert b.get(url).status_code == 404
    assert b.put(f"/api/v1/questions/{q2}", json={"text": "Hijacked question text?", "options": ["a", "b"],
                                                   "correct_index": 0}).status_code == 404
    assert b.post(f"/api/v1/questions/{q2}/approve").status_code == 404
    assert b.post(f"/api/v1/questions/{q2}/reject").status_code == 404
    assert b.post(f"/api/v1/questions/{q2}/regenerate").status_code == 404
    # B cannot generate into A's department, and a client-sent institution_id is ignored
    assert upload(b, dept_a).status_code == 404
    with app.app_context():
        inst_a = Institution.query.filter_by(name="One University").first().id
    mine = gen_ok(b, dept_b, institution_id=inst_a)
    with app.app_context():
        assert db.session.get(GenerationAttempt, mine["id"]).institution_id != inst_a
        assert db.session.get(Question, q2).status == "draft"
    assert len(a.get("/api/v1/questions/attempts").get_json()["data"]["items"]) == 1


def test_pending_and_suspended_institutions_blocked(app, fake):
    c = app.test_client()
    c.post("/api/v1/institutions/signup", json={**SIGNUP, "admin_email": "p@pending.edu", "institution_name": "Pending U"})
    r = login(c, "p@pending.edu", SIGNUP["password"])
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "INSTITUTION_PENDING"
    assert c.get(BANK).status_code == 401

    s, dept = setup_admin(app, "s@susp.edu", "Susp U")
    with app.app_context():
        Institution.query.filter_by(name="Susp U").first().status = "suspended"
        db.session.commit()
    r = upload(s, dept)
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "INSTITUTION_NOT_ACTIVE"
    assert s.get(BANK).status_code == 403


# ------------------------------------------------------------------ PDF pre-check (used by the Generate page on file select)
def test_check_pdf(app, fake):
    c, _ = setup_admin(app)
    url = "/api/v1/questions/check-pdf"
    r = c.post(url, data={"file": (io.BytesIO(make_pdf(pages=2)), "ch3.pdf")}, content_type="multipart/form-data")
    d = r.get_json()["data"]
    assert r.status_code == 200 and d["filename"] == "ch3.pdf" and d["pages"] == 2 and d["characters"] > 300
    for data, code in ((blank_pdf(), "PDF_NO_TEXT"), (b"nope", "INVALID_PDF"), (encrypted_pdf("x"), "PDF_ENCRYPTED")):
        r = c.post(url, data={"file": (io.BytesIO(data), "x.pdf")}, content_type="multipart/form-data")
        assert r.status_code == 422 and r.get_json()["error"]["code"] == code
    assert fake["p"].calls == 0                                   # no AI quota used
    with app.app_context():
        assert GenerationAttempt.query.count() == 0
    assert app.test_client().post(url).status_code == 401


# ------------------------------------------------------------------ photographed / scanned PDFs (AI reads the pictures)
NOTES = ("--- Page 1 ---\nPhotosynthesis happens in the chloroplasts of plant cells. Chlorophyll absorbs light energy "
         "and the plant uses it to turn carbon dioxide and water into glucose.\n--- Page 2 ---\nOxygen is released as a "
         "by-product when water molecules are split during the light reactions. The Calvin cycle fixes carbon dioxide "
         "in the stroma using ATP and NADPH made in the light reactions.")


def vision_reply(prompt):
    return NOTES if prompt.startswith("Transcribe") else smart_reply(prompt)


def test_photo_pdf_check_needs_vision_provider(app, fake):
    c, _ = setup_admin(app)
    url = "/api/v1/questions/check-pdf"
    send = lambda: c.post(url, data={"file": (io.BytesIO(photo_pdf(3)), "phone-photos.pdf")},  # noqa: E731
                          content_type="multipart/form-data")
    fake["p"] = FakeProvider(vision_reply, vision=True)
    d = send().get_json()["data"]
    assert d["needs_ocr"] is True and d["image_pages"] == 3 and d["characters"] == 0
    assert fake["p"].calls == 0                                    # checking never spends AI quota
    fake["p"] = FakeProvider(smart_reply, vision=False)            # e.g. Groq / Ollama text model
    r = send()
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "PDF_NO_TEXT"
    assert "gemini" in r.get_json()["error"]["message"].lower()
    fake["p"] = FakeProvider(vision_reply, vision=True)
    r = c.post(url, data={"file": (io.BytesIO(blank_pdf()), "blank.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "PDF_NO_TEXT"   # no text AND no pictures


def test_photo_pdf_generates_from_transcription(app, fake):
    app.config["OCR_PAGES_PER_REQUEST"] = 2
    fake["p"] = FakeProvider(vision_reply, vision=True)
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, data=photo_pdf(5), filename="notes-photos.pdf", count=3)
    assert a["source"]["ocr"] is True and a["source"]["pages"] == 5 and a["source"]["characters"] > 300
    assert fake["p"].image_calls == [2, 2, 1]                     # 5 pictures sent in batches of 2
    assert len(a["questions"]) == 3 and all(q["status"] == "draft" for q in a["questions"])
    with app.app_context():
        att = db.session.get(GenerationAttempt, a["id"])
        assert "Calvin cycle" in att.source_text                   # transcription kept for "Regenerate"
    r = c.post(f"/api/v1/questions/{a['questions'][0]['id']}/regenerate")
    assert r.status_code == 201 and fake["p"].image_calls == [2, 2, 1]   # regenerating re-uses text, no pictures


def test_photo_pdf_unreadable_or_ai_error(app, fake):
    c, dept = setup_admin(app)
    fake["p"] = FakeProvider(lambda p: "--- Page 1 ---\n[unreadable]\n--- Page 2 ---\n[unreadable]", vision=True)
    r = upload(c, dept, data=photo_pdf(2))
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "PDF_NO_TEXT"
    assert "clearer photos" in r.get_json()["error"]["message"]
    fake["p"] = FakeProvider(ai_errors.rate_limited(None), vision=True)
    r = upload(c, dept, data=photo_pdf(2))
    assert r.status_code == 429 and r.get_json()["error"]["code"] == "AI_RATE_LIMITED"
    with app.app_context():
        assert GenerationAttempt.query.count() == 0                # nothing half-saved


def test_text_pdf_never_sends_pictures(app, fake):
    fake["p"] = FakeProvider(vision_reply, vision=True)
    c, dept = setup_admin(app)
    a = gen_ok(c, dept)
    assert a["source"]["ocr"] is False and fake["p"].image_calls == []


def test_image_request_shape(monkeypatch):
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(body=json)
        return FakeResp(200, _chat("Page text"))
    monkeypatch.setattr(requests, "post", post)
    p = get_provider({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k"})
    assert p.supports_images and p.complete("sys", "Transcribe", images=[b"\xff\xd8jpegbytes"]) == "Page text"
    parts = sent["body"]["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "Transcribe"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    groq = get_provider({"AI_PROVIDER": "groq", "GROQ_API_KEY": "k"})
    assert not groq.supports_images
    with pytest.raises(ai_errors.AIError) as e:
        groq.complete("sys", "Transcribe", images=[b"x"])
    assert e.value.code == "AI_NO_VISION"


# ------------------------------------------------------------------ PDFs with BOTH typed pages and photo pages
def labelled_reply(prompt):
    """Transcription echoes which pages it was given, so the test can check the page order."""
    if prompt.startswith("Transcribe"):
        label = re.search(r"\((pages? [\d-]+) of the document\)", prompt).group(1)
        return f"PHOTO-TEXT {label}: " + "Chlorophyll absorbs light; stomata let carbon dioxide in. " * 4
    return smart_reply(prompt)


def check(c, data):
    return c.post("/api/v1/questions/check-pdf", data={"file": (io.BytesIO(data), "mixed.pdf")},
                  content_type="multipart/form-data")


def test_mixed_pdf_reads_photo_pages_in_page_order(app, fake):
    fake["p"] = FakeProvider(labelled_reply, vision=True)
    c, dept = setup_admin(app)
    data = mixed_pdf("TPPTP")
    d = check(c, data).get_json()["data"]
    assert (d["typed_pages"], d["image_pages"], d["skipped_photo_pages"], d["needs_ocr"]) == (2, 3, 0, True)
    a = gen_ok(c, dept, data=data, count=3)
    assert a["source"]["ocr"] is True
    assert fake["p"].image_calls == [2, 1]          # pages 2-3 together; page 5 alone (typed page 4 sits between)
    with app.app_context():
        t = db.session.get(GenerationAttempt, a["id"]).source_text
    order = [t.index("Typed page 1"), t.index("PHOTO-TEXT pages 2-3"), t.index("Typed page 4"), t.index("PHOTO-TEXT page 5")]
    assert order == sorted(order)


def test_mixed_pdf_without_vision_uses_typed_pages_and_says_so(app, fake):
    fake["p"] = FakeProvider(smart_reply, vision=False)          # e.g. Groq / Ollama
    c, dept = setup_admin(app)
    data = mixed_pdf("TPPTP")
    d = check(c, data).get_json()["data"]
    assert (d["typed_pages"], d["image_pages"], d["skipped_photo_pages"], d["truncated"]) == (2, 0, 3, True)
    a = gen_ok(c, dept, data=data, count=2)
    assert a["source"]["ocr"] is False and a["source"]["truncated"] is True and fake["p"].image_calls == []


def test_figures_in_typed_pages_are_not_sent(app, fake):
    fake["p"] = FakeProvider(labelled_reply, vision=True)
    c, dept = setup_admin(app)
    d = check(c, mixed_pdf("FTF")).get_json()["data"]
    assert (d["typed_pages"], d["image_pages"], d["needs_ocr"]) == (3, 0, False)   # diagrams don't cost quota


def test_scanner_watermark_page_is_still_a_photo_page(app, fake):
    fake["p"] = FakeProvider(labelled_reply, vision=True)
    c, _ = setup_admin(app)
    d = check(c, mixed_pdf("WW")).get_json()["data"]
    assert (d["typed_pages"], d["image_pages"]) == (0, 2)


def test_photo_page_limits(app, fake):
    fake["p"] = FakeProvider(labelled_reply, vision=True)
    c, dept = setup_admin(app)
    app.config["OCR_MAX_PAGES"] = 2
    d = check(c, mixed_pdf("PPP")).get_json()["data"]
    assert (d["image_pages"], d["skipped_photo_pages"], d["truncated"]) == (2, 1, True)
    # once the AI text limit is surely full, later photo pages are not sent at all (saves quota)
    app.config.update(OCR_MAX_PAGES=20, SOURCE_MAX_CHARS=1500)
    gen_ok(c, dept, data=mixed_pdf("TPPPP"), count=1)
    assert sum(fake["p"].image_calls) == 1


# ------------------------------------------------------------------ several PDFs, whole-document coverage, description-only
def upload_many(c, dept, files, **form):
    fields = {"department_id": str(dept["id"]), "subject": "Biology", "question_type": "mcq",
              "difficulty": "medium", "count": "4", "marks": "1"}
    fields.update({k: str(v) for k, v in form.items()})
    fields["files"] = [(io.BytesIO(data), name) for name, data in files]
    return c.post(GEN, data=fields, content_type="multipart/form-data")


def test_multiple_pdfs(app, fake):
    c, dept = setup_admin(app)
    one = make_pdf(["Handout A: " + line for line in SAMPLE_TEXT])
    two = make_pdf(["Handout B: " + line for line in SAMPLE_TEXT])
    r = upload_many(c, dept, [("a.pdf", one), ("b.pdf", two)])
    assert r.status_code == 201, r.get_json()
    a = r.get_json()["data"]["attempt"]
    assert a["source"]["files"] == 2 and a["source"]["filename"] == "a.pdf, b.pdf" and a["source"]["pages"] == 2
    with app.app_context():
        t = db.session.get(GenerationAttempt, a["id"]).source_text
    assert t.index("=== Document 1: a.pdf ===") < t.index("Handout A") < t.index("=== Document 2: b.pdf ===") < t.index("Handout B")


def test_multiple_pdfs_limits_and_bad_file_named(app, fake):
    c, dept = setup_admin(app)
    app.config["MAX_PDFS_PER_GENERATION"] = 2
    r = upload_many(c, dept, [(f"{i}.pdf", make_pdf()) for i in range(3)])
    assert r.status_code == 422 and "at most 2" in r.get_json()["error"]["details"]["file"]
    r = upload_many(c, dept, [("good.pdf", make_pdf()), ("broken.pdf", b"not a pdf")])
    assert r.status_code == 422 and r.get_json()["error"]["message"].startswith('"broken.pdf":')


def test_fair_share_between_big_and_small_pdf(app, fake):
    app.config["SOURCE_MAX_CHARS"] = 3000
    c, dept = setup_admin(app)
    big = mixed_pdf("T" * 12)                                       # ~9,000 characters
    small = make_pdf(["Small handout: " + line for line in SAMPLE_TEXT])
    a = upload_many(c, dept, [("big.pdf", big), ("small.pdf", small)]).get_json()["data"]["attempt"]
    with app.app_context():
        t = db.session.get(GenerationAttempt, a["id"]).source_text
    assert "Small handout" in t and len(t) <= 3200 and a["source"]["truncated"] is True


def test_questions_are_spread_over_the_whole_document(app, fake):
    prompts = []
    fake["p"] = FakeProvider(lambda p: (prompts.append(p), smart_reply(p))[1])
    app.config.update(AI_MAX_SOURCE_CHARS=1500, AI_MAX_REQUESTS_PER_GENERATION=3)
    c, dept = setup_admin(app)
    gen_ok(c, dept, data=mixed_pdf("T" * 20), count=6)              # 20 distinct pages, ~13 parts
    sources = [p.split("<<<SOURCE")[1] for p in prompts]
    assert len(prompts) == 3
    assert "Typed page 1:" in sources[0] and "Typed page 20:" in sources[-1]   # beginning AND end are used
    assert "part 1 of" in prompts[0] and all(p.count("Write 2 ") for p in prompts)


def test_description_only(app, fake):
    prompts = []
    fake["p"] = FakeProvider(lambda p: (prompts.append(p), smart_reply(p))[1])
    c, dept = setup_admin(app)
    r = upload(c, dept, data=False, focus="photosynthesis")         # too vague
    err = r.get_json()["error"]
    assert r.status_code == 422 and "at least 8 words" in err["details"]["focus"] and "file" in err["details"]
    focus = "Photosynthesis: light reactions, Calvin cycle and factors affecting the rate, first-year biology"
    a = gen_ok(c, dept, data=False, focus=focus)
    assert a["source"]["kind"] == "description" and a["source"]["files"] == 0 and a["source"]["filename"] == ""
    assert "TOPIC DESCRIPTION" in prompts[0] and focus in prompts[0] and "<<<SOURCE" not in prompts[0]
    assert all(q["status"] == "draft" for q in a["questions"])


def test_check_pdf_suggests_headings(app, fake):
    c, _ = setup_admin(app)
    r = c.post("/api/v1/questions/check-pdf", data={"file": (io.BytesIO(make_pdf()), "ch.pdf")},
               content_type="multipart/form-data")
    assert "Chapter 3: Photosynthesis" in r.get_json()["data"]["headings"]


def test_meta_has_file_limits(client):
    lim = client.get("/api/v1/meta").get_json()["data"]["generation_limits"]
    assert lim["max_files"] == 10 and lim["max_upload_mb"] == 200 and lim["max_questions"] == 100
    assert lim["description_min_words"] == 8


def test_hundred_questions_spread_over_ten_parts(app, fake):
    prompts = []
    fake["p"] = FakeProvider(lambda p: (prompts.append(p), smart_reply(p))[1])
    app.config["AI_MAX_SOURCE_CHARS"] = 1500
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, data=mixed_pdf("T" * 30), count=100)      # 30 distinct pages -> ~20 parts
    assert a["generated_count"] == 100 and a["status"] == "completed" and len(prompts) == 10
    sources = [p.split("<<<SOURCE")[1] for p in prompts]
    assert "Typed page 1:" in sources[0] and "Typed page 30:" in sources[-1]
    assert upload(c, dept, count=101).status_code == 422


# ------------------------------------------------------------------ server without Pillow must not crash
def test_without_pillow_typed_pdfs_still_work(app, fake, monkeypatch):
    import sys
    from pypdf import PdfReader, PdfWriter
    photos = photo_pdf(2)                                              # built while Pillow is still available
    monkeypatch.setitem(sys.modules, "PIL", None)                     # like a PC where Pillow isn't installed
    fake["p"] = FakeProvider(vision_reply, vision=True)
    c, dept = setup_admin(app)
    w = PdfWriter()                                                    # typed PDF with a short title page
    w.append(PdfReader(io.BytesIO(make_pdf(["Biology Notes"]))))
    w.append(PdfReader(io.BytesIO(make_pdf())))
    buf = io.BytesIO()
    w.write(buf)
    r = c.post("/api/v1/questions/check-pdf", data={"file": (io.BytesIO(buf.getvalue()), "notes.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["data"]["typed_pages"] == 1
    r = c.post("/api/v1/questions/check-pdf", data={"file": (io.BytesIO(photos), "photos.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "SERVER_SETUP"
    assert "pip install" in r.get_json()["error"]["message"]


def test_old_database_gives_clear_message(app, fake):
    from sqlalchemy import text
    c, _ = setup_admin(app)
    with app.app_context():                                    # simulate "forgot to run flask db upgrade"
        db.session.execute(text("ALTER TABLE generation_attempts DROP COLUMN source_kind"))
        db.session.commit()
    r = c.get("/api/v1/questions/attempts")
    assert r.status_code == 500 and r.get_json()["error"]["code"] == "DB_NOT_UPGRADED"
    assert "flask --app run db upgrade" in r.get_json()["error"]["message"]



# ------------------------------------------------------------------ messy but usable AI replies (real models do this)
def _q(n, extra=""):
    return ('{"question": "Question %d about photosynthesis%s?", "options": ["Chloroplast %d", "Nucleus %d", '
            '"Ribosome %d", "Vacuole %d"], "correct_index": 0, "explanation": "From the text."}' % (n, extra, n, n, n, n))


@pytest.mark.parametrize("reply,expected", [
    ('{"questions": [' + _q(1, r" with \alpha and \(x^2\)") + "]}", 1),            # LaTeX backslashes
    ('{"questions": [' + _q(1) + ", " + _q(2) + ",]}", 2),                         # trailing comma
    ('{"questions": [{"question": "Line one\nline two of the question?", "options": ["a", "b", "c", "d"], '
     '"correct_index": 1}]}', 1),                                                  # real line break inside a string
    ('Here you go:\n```json\n{"questions": [' + _q(1) + ", " + _q(2) + ", " + _q(3)[:60], 2),   # cut off mid-item
    (_q(1), 1),                                                                     # a single object, no list
])
def test_parse_messy_replies(reply, expected):
    items = generator.parse_items(reply)
    assert len(items) == expected
    for it in items:
        from app.modules.questions.validation import clean_question
        clean_question(it, "mcq", from_ai=True)                                     # every kept item is usable


def test_cut_off_reply_still_gives_questions(app, fake):
    cut = '{"questions": [' + ", ".join(_q(i) for i in range(1, 5)) + ", " + _q(5)[:40]
    fake["p"] = FakeProvider(cut, smart_reply)       # first answer cut off, the top-up request answers normally
    c, dept = setup_admin(app)
    a = gen_ok(c, dept, count=5)
    assert a["generated_count"] == 5 and a["status"] == "completed"


def test_provider_keeps_cut_off_and_list_content(monkeypatch):
    replies = iter([FakeResp(200, _chat('{"questions": [', finish="length")),
                    FakeResp(200, {"choices": [{"message": {"content": [{"type": "text", "text": "part one "},
                                                                        {"type": "text", "text": "part two"}]},
                                                "finish_reason": "stop"}]})])
    monkeypatch.setattr(requests, "post", lambda *a, **k: next(replies))
    p = get_provider({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k"})
    assert p.complete("s", "u") == '{"questions": ['
    assert p.complete("s", "u") == "part one part two"


def test_options_as_dict_or_choices():
    from app.modules.questions.validation import clean_question
    q = clean_question({"question": "Where does photosynthesis happen?", "options": {"B": "Nucleus", "A": "Chloroplast",
                        "D": "Wall", "C": "Ribosome"}, "answer": "A"}, "mcq", from_ai=True)
    assert q["options"] == ["Chloroplast", "Nucleus", "Ribosome", "Wall"] and q["correct_index"] == 0
    q = clean_question({"question": "Which gas is released as a by-product?", "choices": ["Oxygen", "Neon", "Argon",
                        "Helium"], "correct_answer": "Oxygen"}, "mcq", from_ai=True)
    assert q["correct_index"] == 0
