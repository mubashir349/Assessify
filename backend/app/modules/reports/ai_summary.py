"""Phase 7 - AI insights. The AI gets the NUMBERS only (no names, emails, roll numbers or question answers) and
writes a few short, practical points for the admin. Two scopes:

    test  -> one test's report (averages, subjects, departments, hardest questions)
    bank  -> the question bank (approved / waiting questions per field and subject, draft tests that can't publish)

AI errors come back as the same safe messages as question generation (AI_NOT_CONFIGURED, AI_RATE_LIMITED, ...).
"""
import json

from flask import current_app
from sqlalchemy import func

from app.ai import AIError, get_provider
from app.common.errors import ApiError
from app.common.utils import utcnow
from app.extensions import db
from app.models.aptitude_test import AptitudeTest
from app.models.question import Question
from app.modules.aptitude_tests.service import availability_of
from app.modules.reports.service import load, stats

MAX_POINTS = 6
SYSTEM_PROMPT = (
    "You help the admissions office of a school or university understand aptitude test data. "
    "You get statistics as JSON. Reply with JSON only: {\"insights\": [\"...\", \"...\"]} with 3 to 6 short points "
    "(one or two sentences each) in plain English. Each point states a finding from the numbers and, when useful, "
    "one practical next step. Do not invent numbers that are not in the data. Do not mention JSON."
)


def bank_stats(institution_id: int) -> dict:
    """Question counts per field / subject / status + draft tests that do not have enough approved questions."""
    rows = (db.session.query(Question.department_name, Question.subject_name, Question.status, func.count(Question.id))
            .filter(Question.institution_id == institution_id, Question.status.in_(("approved", "draft")))
            .group_by(Question.department_name, Question.subject_name, Question.status).all())
    subjects: dict[tuple, dict] = {}
    for dept, subject, status, n in rows:
        s = subjects.setdefault((dept, subject), {"field": dept, "subject": subject, "approved": 0, "waiting_review": 0})
        s["approved" if status == "approved" else "waiting_review"] += n
    drafts = AptitudeTest.query.filter_by(institution_id=institution_id, status="draft").all()
    blocked = []
    for t in drafts:
        short = availability_of(t)["shortfalls"]
        if short:
            blocked.append({"test": t.name, "short": [{"row": s.get("label"), "needed": s.get("needed"),
                                                       "available": s.get("pool")} for s in short[:5]]})
    return {"subjects": sorted(subjects.values(), key=lambda s: s["approved"]), "draft_tests_short_of_questions": blocked}


def bank_tips(data: dict) -> list[str]:
    """Rule-based tips shown even without AI."""
    tips = []
    waiting = sum(s["waiting_review"] for s in data["subjects"])
    if waiting:
        tips.append(f"{waiting} generated question(s) are waiting for review; approve them to grow the bank.")
    thin = [s for s in data["subjects"] if s["approved"] < 10]
    if thin:
        names = ", ".join(f"{s['field']} / {s['subject']} ({s['approved']})" for s in thin[:4])
        tips.append(f"Few approved questions in: {names}. Generate more before building tests on them.")
    for t in data["draft_tests_short_of_questions"][:3]:
        tips.append(f"Draft test \"{t['test']}\" cannot be published yet: {len(t['short'])} composition row(s) "
                    f"need more approved questions.")
    return tips or ["The question bank has enough approved questions for every draft test."]


def _test_payload(institution_id: int, test_id) -> dict:
    test, candidates, rows = load(institution_id, test_id)
    data = stats(test, candidates, rows, utcnow())
    for q in data["hardest_questions"]:
        q.pop("question_id", None)
    return {"test": {"name": test.name, "level": test.level,
                     "timing_mode": test.schedule.timing_mode, "duration_minutes": test.schedule.duration_minutes},
            **{k: v for k, v in data.items() if k != "insights"}}


def _parse(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    try:
        points = json.loads(text[start:end + 1]).get("insights") if start >= 0 else None
    except (ValueError, AttributeError):
        points = None
    if not isinstance(points, list):
        points = [line.lstrip("-*• ").strip() for line in raw.splitlines()]
    points = [str(p).strip()[:400] for p in points if str(p).strip()]
    if not points:
        raise ApiError("AI_BAD_RESPONSE", "The AI service returned an answer that could not be used. Please try again.", 502)
    return points[:MAX_POINTS]


def ai_summary(institution_id: int, data: dict) -> dict:
    """POST /reports/ai-summary {scope: test | bank, test_id (scope test)}"""
    scope = data.get("scope")
    if scope == "test":
        payload = _test_payload(institution_id, data.get("test_id"))
    elif scope == "bank":
        payload = bank_stats(institution_id)
    else:
        raise ApiError("VALIDATION_ERROR", "scope must be test or bank.", 422, {"scope": "Choose test or bank."})
    try:
        provider = get_provider(current_app.config)
        raw = provider.complete(SYSTEM_PROMPT, f"Scope: {scope}\nStatistics:\n{json.dumps(payload, default=str)}")
    except AIError as exc:
        raise ApiError(exc.code, exc.message, exc.status)
    return {"scope": scope, "insights": _parse(raw), "provider": provider.name, "model": provider.model}
