"""Phase 3 business rules: generation attempts, draft review and the question bank.

Every query is filtered by the signed-in admin's institution_id (taken from the login, never from the request),
so one institution can never read or change another institution's attempts or questions - they simply get 404.
"""
import hashlib
import logging
import re
from datetime import timedelta

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import defer

from app.ai import AIError, get_provider
from app.common.errors import ApiError
from app.common.utils import utcnow
from app.common.validation import FIX_FIELDS
from app.extensions import db
from app.models.department import LEVELS
from app.models.question import ATTEMPT_STATUSES, DIFFICULTIES, QUESTION_TYPES, GenerationAttempt, Question
from app.models.user import User
from app.modules.departments.service import get_department
from app.modules.questions import generator, pdf
from app.modules.questions.validation import MARKS_MAX, MARKS_MIN, QuestionInvalid, clean_question

log = logging.getLogger(__name__)
DUPLICATE_WINDOW = timedelta(minutes=10)
PER_PAGE_DEFAULT, PER_PAGE_MAX = 20, 100


# ---------------------------------------------------------------- helpers
def _cfg(key):
    return current_app.config[key]


def _ai_error(exc: AIError, attempt_id: int | None = None) -> ApiError:
    return ApiError(exc.code, exc.message, exc.status, {"attempt_id": attempt_id} if attempt_id else None)


def _int(value, label: str, key: str, errors: dict, lo: int, hi: int, default=None):
    if value in (None, "") and default is not None:
        return default
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        errors[key] = f"{label} must be a whole number."
        return None
    if not lo <= n <= hi:
        errors[key] = f"{label} must be between {lo} and {hi}."
    return n


def _page_args(args) -> tuple[int, int]:
    try:
        page = max(1, int(args.get("page", 1)))
        per_page = min(PER_PAGE_MAX, max(1, int(args.get("per_page", PER_PAGE_DEFAULT))))
    except (TypeError, ValueError):
        raise ApiError("BAD_REQUEST", "page and per_page must be whole numbers.", 400)
    return page, per_page


def _paged(query, args, serialise) -> dict:
    page, per_page = _page_args(args)
    p = query.paginate(page=page, per_page=per_page, error_out=False)
    return {"items": [serialise(x) for x in p.items], "page": p.page, "per_page": p.per_page,
            "total": p.total, "pages": p.pages}


def _commit():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_attempt(institution_id: int, attempt_id: int) -> GenerationAttempt:
    a = GenerationAttempt.query.filter_by(id=attempt_id, institution_id=institution_id).first()
    if a is None:
        raise ApiError("NOT_FOUND", "Generation attempt not found.", 404)
    return a


def get_question(institution_id: int, question_id: int) -> Question:
    q = Question.query.filter_by(id=question_id, institution_id=institution_id).first()
    if q is None:
        raise ApiError("NOT_FOUND", "Question not found.", 404)
    return q


def _require_status(q: Question, allowed: tuple, action: str):
    if q.status not in allowed:
        raise ApiError("INVALID_TRANSITION", f"A question that is '{q.status}' cannot be {action}.", 409,
                       {"status": q.status})


def _new_question(attempt: GenerationAttempt, data: dict, position: int, **extra) -> Question:
    """Creates a draft and adds it to attempt.questions (so counts are right straight away)."""
    q = Question(
        institution_id=attempt.institution_id, attempt_id=attempt.id, department_id=attempt.department_id,
        department_name=attempt.department_name, level=attempt.level, subject_name=attempt.subject_name,
        topic=data.get("topic"), question_type=attempt.question_type, text=data["text"], options=data["options"],
        correct_index=data["correct_index"], explanation=data.get("explanation"), difficulty=attempt.difficulty,
        marks=attempt.marks, position=position, status="draft", **extra)
    attempt.questions.append(q)
    return q


def _params(attempt: GenerationAttempt, count: int) -> generator.Params:
    existing = [q.text for q in attempt.questions]
    return generator.Params(source_text=attempt.source_text, count=count, question_type=attempt.question_type,
                            difficulty=attempt.difficulty, subject=attempt.subject_name, level=attempt.level,
                            focus=attempt.focus, avoid=existing, mode=attempt.source_kind or "pdf")


def _run(provider, params: generator.Params) -> generator.Outcome:
    return generator.generate(provider, params, batch_size=max(1, _cfg("AI_BATCH_SIZE")),
                              max_retries=max(0, _cfg("AI_MAX_RETRIES")),
                              chunk_size=_cfg("AI_MAX_SOURCE_CHARS"),
                              max_requests=max(1, _cfg("AI_MAX_REQUESTS_PER_GENERATION")))


# ---------------------------------------------------------------- generate
def _clean_generate_form(institution_id: int, form) -> dict:
    errors: dict = {}
    max_q = _cfg("MAX_QUESTIONS_PER_ATTEMPT")

    dept = None
    dept_id = _int(form.get("department_id"), "Field / department", "department_id", errors, 1, 2**31 - 1)
    if dept_id is None and "department_id" not in errors:
        errors["department_id"] = "Choose a field / department."
    elif "department_id" not in errors:
        dept = get_department(institution_id, dept_id)     # 404 if it belongs to another institution

    subject = (form.get("subject") or "").strip()
    if not subject:
        errors["subject"] = "Choose a subject."
    elif dept is not None:
        match = next((s.name for s in dept.subjects if s.name.lower() == subject.lower()), None)
        if match is None:
            errors["subject"] = "This subject is not part of the selected field / department."
        subject = match or subject

    qtype = form.get("question_type")
    if qtype not in QUESTION_TYPES:
        errors["question_type"] = "Choose one of: " + ", ".join(QUESTION_TYPES) + "."
    diff = form.get("difficulty")
    if diff not in DIFFICULTIES:
        errors["difficulty"] = "Choose one of: " + ", ".join(DIFFICULTIES) + "."
    count = _int(form.get("count"), "Number of questions", "count", errors, 1, max_q, default=10)
    marks = _int(form.get("marks"), "Marks per question", "marks", errors, MARKS_MIN, MARKS_MAX, default=1)
    focus = (form.get("focus") or "").strip()
    if len(focus) > 500:
        errors["focus"] = "Description / focus must be at most 500 characters."
    if errors:
        raise ApiError("VALIDATION_ERROR", FIX_FIELDS, 422, errors)
    return {"dept": dept, "subject": subject, "question_type": qtype, "difficulty": diff, "count": count,
            "marks": marks, "focus": focus or None}


def description_problem(text: str | None) -> str | None:
    """Without a PDF the description is the only scope the AI gets, so it must say enough. None = fine."""
    words = re.findall(r"[^\W\d_]{2,}", text or "")
    need = _cfg("DESCRIPTION_MIN_WORDS")
    if len(words) < need:
        return (f"Without a PDF, describe the scope in at least {need} words - which topics or chapters, and what to "
                "focus on. Example: 'Photosynthesis: light reactions, Calvin cycle, factors affecting the rate, "
                "for first-year biology'.")
    return None


def _optional_provider():
    try:
        return get_provider(current_app.config)
    except AIError:
        return None


def _extract(file_storage, provider, image_budget: int | None = None) -> pdf.ExtractedPdf:
    budget = _cfg("OCR_MAX_PAGES") if image_budget is None else image_budget
    return pdf.extract(file_storage, max_pages=_cfg("PDF_MAX_PAGES"), min_chars=_cfg("PDF_MIN_TEXT_CHARS"),
                       max_chars=_cfg("SOURCE_MAX_CHARS"), allow_images=bool(provider and provider.supports_images),
                       max_image_pages=budget, image_max_side=_cfg("OCR_IMAGE_MAX_SIDE"))


def check_pdf(file_storage) -> dict:
    """Same checks as generation, but stops after reading the PDF: lets the page ask for another PDF straight away.
    No AI call is made here (photo pages are only read when the admin actually generates)."""
    doc = _extract(file_storage, _optional_provider())
    return {"filename": doc.filename, "pages": doc.pages, "characters": doc.total_chars, "truncated": doc.truncated,
            "typed_pages": doc.typed_pages, "needs_ocr": doc.needs_ocr, "image_pages": len(doc.images),
            "skipped_photo_pages": doc.skipped_photo_pages, "headings": pdf.headings(doc.text)}


def _photo_batches(parts: list[tuple], size: int) -> list[list[tuple[int, bytes]]]:
    """Groups photo pages that sit next to each other in the document (max `size` per AI request)."""
    batches, run = [], []
    for kind, no, payload in parts + [("end", 0, None)]:
        if kind == "photo":
            run.append((no, payload))
            if len(run) == size:
                batches.append(run)
                run = []
        elif run:
            batches.append(run)
            run = []
    return batches


def _read_photos(provider, doc: pdf.ExtractedPdf, who: str = "this PDF") -> None:
    """Photo pages are read by the AI; typed pages keep their own text. Both are joined back in page order and
    the result becomes the document's text."""
    by_first_page: dict[int, str] = {}
    try:
        for batch in _photo_batches(doc.parts, max(1, _cfg("OCR_PAGES_PER_REQUEST"))):
            by_first_page[batch[0][0]] = generator.transcribe_pages(provider, batch,
                                                                    max_retries=max(0, _cfg("AI_MAX_RETRIES")))
    except AIError as exc:
        raise _ai_error(exc)

    pieces = []
    for kind, no, payload in doc.parts:
        if kind == "text":
            pieces.append(payload)
        elif no in by_first_page:
            pieces.append(by_first_page[no])
    text = pdf.normalise("\n\n".join(pieces))
    readable = re.sub(r"\[unreadable\]|--- ?Page \d+ ?---|\W+", "", text, flags=re.IGNORECASE)
    if len(readable) < _cfg("PDF_MIN_TEXT_CHARS"):
        raise ApiError("PDF_NO_TEXT", f"The AI could not read enough text from the pictures in {who} (they may be "
                       "blurry, dark or tilted). Please upload clearer photos or another PDF.", 422,
                       {"file": "The photos could not be read clearly."})
    doc.text, was_cut = pdf.cut(text, _cfg("SOURCE_MAX_CHARS"))
    doc.truncated = doc.truncated or was_cut
    doc.total_chars = len(text)
    doc.parts = []           # pictures are not kept


def _combine(docs: list[pdf.ExtractedPdf]) -> tuple[str, bool]:
    """Joins several PDFs into one source text. SOURCE_MAX_CHARS is shared fairly, so one huge book cannot
    crowd out a short handout."""
    budget, n = _cfg("SOURCE_MAX_CHARS"), len(docs)
    order = sorted(range(n), key=lambda i: len(docs[i].text))
    alloc, remaining = {}, budget
    for k, i in enumerate(order):
        alloc[i] = min(len(docs[i].text), remaining // (n - k))
        remaining -= alloc[i]
    pieces, cut_any = [], False
    for i, d in enumerate(docs):
        text, was_cut = pdf.cut(d.text, max(1, alloc[i]))
        cut_any = cut_any or was_cut
        pieces.append(f"=== Document {i + 1}: {d.filename} ===\n{text}" if n > 1 else text)
    return "\n\n".join(pieces), cut_any


def generate(user: User, form, files: list) -> GenerationAttempt:
    """Upload PDF(s) -> extract text (photo pages are read by the AI) -> ask the AI for questions spread over the
    whole material -> save the attempt and its valid drafts (never auto-approved).
    No PDF at all -> questions from the admin's description, which must describe the scope well enough."""
    inst = user.institution_id
    f = _clean_generate_form(inst, form)
    files = [x for x in (files or []) if x is not None and x.filename]
    _check_generate_files(f, files)

    provider = _optional_provider()
    docs = _extract_all(files, provider)
    if provider is None:
        try:
            provider = get_provider(current_app.config)
        except AIError as exc:
            raise _ai_error(exc)
    used_ocr = any(d.needs_ocr for d in docs)
    for d in docs:
        if d.needs_ocr:
            _read_photos(provider, d, f'"{d.filename}"')

    src = _source_of(docs, f["focus"])
    _ensure_not_busy(inst, src["fingerprint"], f)

    attempt = GenerationAttempt(
        institution_id=inst, created_by_id=user.id, department_id=f["dept"].id, department_name=f["dept"].name,
        level=f["dept"].level, subject_name=f["subject"], question_type=f["question_type"], difficulty=f["difficulty"],
        requested_count=f["count"], marks=f["marks"], focus=f["focus"], source_kind=src["kind"], source_files=len(docs),
        source_filename=src["name"], source_pages=src["pages"], source_chars=src["chars"],
        source_truncated=src["truncated"], source_sha256=src["fingerprint"], source_text=src["text"],
        source_ocr=used_ocr, status="processing", provider=provider.name, model=provider.model)
    db.session.add(attempt)
    _commit()                                     # the attempt is recorded even if the AI call fails

    try:
        outcome = _run(provider, _params(attempt, f["count"]))
        _save_outcome(attempt, outcome, f["count"])
        _commit()
    except Exception:
        log.exception("Generation attempt %s crashed", attempt.id)
        db.session.rollback()
        attempt = db.session.get(GenerationAttempt, attempt.id)
        attempt.status, attempt.error_code = "failed", "SERVER_ERROR"
        attempt.error_message = "Something went wrong on the server while saving the questions."
        _commit()
        raise

    if attempt.status == "failed":
        exc = outcome.error or AIError("AI_NO_VALID_QUESTIONS", attempt.error_message, status=502)
        raise _ai_error(exc, attempt.id)
    return attempt


def _check_generate_files(f: dict, files: list) -> None:
    max_files = _cfg("MAX_PDFS_PER_GENERATION")
    if len(files) > max_files:
        raise ApiError("VALIDATION_ERROR", FIX_FIELDS, 422,
                       {"file": f"Upload at most {max_files} PDFs at a time."})
    if not files:
        problem = description_problem(f["focus"])
        if problem:
            raise ApiError("VALIDATION_ERROR", "Upload a PDF, or describe the scope in more detail.", 422,
                           {"file": "Upload at least one PDF, or describe the scope below.", "focus": problem})


def _extract_all(files: list, provider) -> list:
    docs: list[pdf.ExtractedPdf] = []
    image_budget = _cfg("OCR_MAX_PAGES")
    for fs in files:
        try:
            doc = _extract(fs, provider, image_budget)
        except ApiError as exc:
            if len(files) > 1:          # say WHICH file is the problem
                exc.message = f'"{pdf.display_name(fs.filename)}": {exc.message}'
            raise
        image_budget -= len(doc.images)
        docs.append(doc)
    return docs


def _source_of(docs: list, focus: str) -> dict:
    """What the questions are generated from: the uploaded PDFs, or the admin's description."""
    if not docs:
        return {"kind": "description", "text": focus, "name": "", "pages": 0, "chars": len(focus), "truncated": False,
                "fingerprint": hashlib.sha256(("description|" + focus.lower()).encode()).hexdigest()}
    source_text, cut_any = _combine(docs)
    names = ", ".join(d.filename for d in docs)
    return {"kind": "pdf", "text": source_text,
            "name": names if len(names) <= 255 else names[:240] + f"… (+{len(docs)} files)",
            "pages": sum(d.pages for d in docs), "chars": sum(d.total_chars for d in docs),
            "truncated": cut_any or any(d.truncated for d in docs),
            "fingerprint": hashlib.sha256("|".join(d.sha256 for d in docs).encode()).hexdigest()}


def _ensure_not_busy(inst: int, fingerprint: str, f: dict) -> None:
    """Same material + same settings already being processed (e.g. a double click) -> don't spend quota twice."""
    busy = GenerationAttempt.query.filter(
        GenerationAttempt.institution_id == inst, GenerationAttempt.source_sha256 == fingerprint,
        GenerationAttempt.status == "processing", GenerationAttempt.department_id == f["dept"].id,
        GenerationAttempt.subject_name == f["subject"], GenerationAttempt.question_type == f["question_type"],
        GenerationAttempt.difficulty == f["difficulty"], GenerationAttempt.created_at >= utcnow() - DUPLICATE_WINDOW,
    ).first()
    if busy:
        raise ApiError("GENERATION_IN_PROGRESS", "These questions are already being generated. Please wait.", 409,
                       {"attempt_id": busy.id})


def _save_outcome(attempt: GenerationAttempt, outcome, requested: int) -> None:
    for i, data in enumerate(outcome.questions):
        _new_question(attempt, data, i)
    attempt.generated_count = len(outcome.questions)
    attempt.discarded_count = outcome.discarded
    if not outcome.questions:
        err = outcome.error
        attempt.status = "failed"
        attempt.error_code = err.code if err else "AI_NO_VALID_QUESTIONS"
        attempt.error_message = (err.message if err else "The AI did not return any usable questions.")[:500]
        return
    attempt.status = "completed" if len(outcome.questions) >= requested else "partial"
    if outcome.error:
        attempt.error_code, attempt.error_message = outcome.error.code, outcome.error.message[:500]


# ---------------------------------------------------------------- attempts
def list_attempts(institution_id: int, args) -> dict:
    q = GenerationAttempt.query.options(defer(GenerationAttempt.source_text)).filter_by(institution_id=institution_id)
    status = args.get("status")
    if status:
        if status not in ATTEMPT_STATUSES:
            raise ApiError("BAD_REQUEST", "Unknown status filter.", 400)
        q = q.filter(GenerationAttempt.status == status)
    text = (args.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        q = q.filter(db.or_(GenerationAttempt.subject_name.ilike(like), GenerationAttempt.department_name.ilike(like),
                            GenerationAttempt.source_filename.ilike(like)))
    q = q.order_by(GenerationAttempt.created_at.desc(), GenerationAttempt.id.desc())
    return _paged(q, args, lambda a: a.to_dict())


# ---------------------------------------------------------------- review actions
def edit_question(institution_id: int, question_id: int, body: dict) -> Question:
    q = get_question(institution_id, question_id)
    _require_status(q, ("draft",), "edited")
    try:
        data = clean_question(body, q.question_type, from_ai=False)
    except QuestionInvalid as exc:
        raise ApiError("VALIDATION_ERROR", FIX_FIELDS, 422, exc.errors)
    q.text, q.options, q.correct_index = data["text"], data["options"], data["correct_index"]
    q.explanation, q.topic = data["explanation"], data["topic"]
    if "difficulty" in data:
        q.difficulty = data["difficulty"]
    if "marks" in data:
        q.marks = data["marks"]
    q.is_edited = True
    _commit()
    return q


def _validate_stored(q: Question) -> dict | None:
    """Re-check a saved question before approval. Returns the errors, or None if it is fine."""
    try:
        clean_question({"text": q.text, "options": q.options, "correct_index": q.correct_index,
                        "explanation": q.explanation, "topic": q.topic}, q.question_type, from_ai=False)
    except QuestionInvalid as exc:
        return exc.errors
    if q.difficulty not in DIFFICULTIES or q.level not in LEVELS:
        return {"question": "Difficulty or level is invalid."}
    return None


def approve_question(user: User, question_id: int) -> Question:
    q = get_question(user.institution_id, question_id)
    _require_status(q, ("draft",), "approved")
    problems = _validate_stored(q)
    if problems:
        raise ApiError("QUESTION_INVALID", "Fix this question before approving it.", 422, problems)
    q.status, q.reviewed_by_id, q.reviewed_at = "approved", user.id, utcnow()
    _commit()
    return q


def reject_question(user: User, question_id: int, body: dict) -> Question:
    q = get_question(user.institution_id, question_id)
    _require_status(q, ("draft",), "rejected")
    reason = body.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if len(reason) > 500:
        raise ApiError("VALIDATION_ERROR", FIX_FIELDS, 422,
                       {"reason": "Reason must be at most 500 characters."})
    q.status, q.rejection_reason = "rejected", reason or None
    q.reviewed_by_id, q.reviewed_at = user.id, utcnow()
    _commit()
    return q


def approve_all(user: User, attempt_id: int) -> dict:
    attempt = get_attempt(user.institution_id, attempt_id)
    approved, skipped = [], []
    now = utcnow()
    for q in attempt.questions:
        if q.status != "draft":
            continue
        problems = _validate_stored(q)
        if problems:
            skipped.append({"id": q.id, "errors": problems})
            continue
        q.status, q.reviewed_by_id, q.reviewed_at = "approved", user.id, now
        approved.append(q.id)
    _commit()
    return {"approved": approved, "skipped": skipped, "attempt": attempt.to_dict(with_questions=True)}


# ---------------------------------------------------------------- regeneration
def _provider_or_error():
    try:
        return get_provider(current_app.config)
    except AIError as exc:
        raise _ai_error(exc)


def regenerate_question(user: User, question_id: int) -> Question:
    """Replace ONE draft or rejected question with a fresh draft. The old one is kept as 'replaced' (history).
    If the AI fails, nothing in the database changes."""
    q = get_question(user.institution_id, question_id)
    _require_status(q, ("draft", "rejected"), "regenerated")
    attempt = q.attempt
    provider = _provider_or_error()
    outcome = _run(provider, _params(attempt, 1))
    if not outcome.questions:
        raise _ai_error(outcome.error or AIError("AI_NO_VALID_QUESTIONS", "The AI did not return a usable question. "
                                                 "Please try again.", status=502), attempt.id)

    db.session.refresh(q)                      # someone may have approved it while the AI was working
    _require_status(q, ("draft", "rejected"), "regenerated")
    new = _new_question(attempt, outcome.questions[0], q.position, regenerated_from_id=q.id)
    db.session.flush()
    q.status, q.replaced_by_id = "replaced", new.id
    attempt.generated_count += 1
    _commit()
    return new


def regenerate_attempt(user: User, attempt_id: int, body: dict) -> dict:
    """Replace every rejected question (and drafts too, if include_drafts=true) and top the attempt up to the
    number originally requested - which also lets a failed / partial attempt be retried from its stored text."""
    attempt = get_attempt(user.institution_id, attempt_id)
    include_drafts = body.get("include_drafts") is True
    allowed = ("rejected", "draft") if include_drafts else ("rejected",)
    targets = [q for q in attempt.questions if q.status in allowed]
    active = [q for q in attempt.questions if q.status != "replaced"]
    missing = max(0, attempt.requested_count - len(active))
    wanted = len(targets) + missing
    if wanted == 0:
        raise ApiError("NOTHING_TO_REGENERATE", "There are no rejected questions to regenerate in this attempt.", 409)

    provider = _provider_or_error()
    outcome = _run(provider, _params(attempt, wanted))
    if not outcome.questions:
        raise _ai_error(outcome.error or AIError("AI_NO_VALID_QUESTIONS", "The AI did not return usable questions. "
                                                 "Please try again.", status=502), attempt.id)

    replaced = added = 0
    next_pos = max([q.position for q in attempt.questions], default=-1) + 1
    fresh = list(outcome.questions)
    for old in targets:
        if not fresh:
            break
        db.session.refresh(old)
        if old.status not in allowed:          # changed by someone else meanwhile - leave it alone
            continue
        new = _new_question(attempt, fresh.pop(0), old.position, regenerated_from_id=old.id)
        db.session.flush()
        old.status, old.replaced_by_id = "replaced", new.id
        replaced += 1
    for data in fresh[:missing]:
        _new_question(attempt, data, next_pos)
        next_pos += 1
        added += 1

    attempt.generated_count += replaced + added
    attempt.discarded_count += outcome.discarded
    db.session.flush()
    active_now = sum(1 for q in attempt.questions if q.status != "replaced")
    attempt.status = "completed" if active_now >= attempt.requested_count else "partial"
    if outcome.error is None:
        attempt.error_code = attempt.error_message = None
    _commit()
    db.session.refresh(attempt)
    return {"replaced": replaced, "added": added, "requested": wanted,
            "attempt": attempt.to_dict(with_questions=True)}


# ---------------------------------------------------------------- question bank
# (query argument, allowed values, column, message for an unknown value)
_BANK_CHOICES = (
    ("level", LEVELS, Question.level, "Unknown level filter."),
    ("difficulty", DIFFICULTIES, Question.difficulty, "Unknown difficulty filter."),
    ("question_type", QUESTION_TYPES, Question.question_type, "Unknown question type filter."),
)


def _bank_choice_filters(q, args):
    for key, allowed, column, message in _BANK_CHOICES:
        value = args.get(key)
        if not value:
            continue
        if value not in allowed:
            raise ApiError("BAD_REQUEST", message, 400)
        q = q.filter(column == value)
    return q


def bank(institution_id: int, args) -> dict:
    """Approved questions ONLY - drafts, rejected and replaced questions never appear here."""
    base = Question.query.filter(Question.institution_id == institution_id, Question.status == "approved")
    q = base
    errors = {}
    if args.get("department_id"):
        dept_id = _int(args.get("department_id"), "department_id", "department_id", errors, 1, 2**31 - 1)
        if errors:
            raise ApiError("BAD_REQUEST", "department_id must be a number.", 400)
        q = q.filter(Question.department_id == dept_id)
    q = _bank_choice_filters(q, args)
    subject = (args.get("subject") or "").strip()
    if subject:
        q = q.filter(func.lower(Question.subject_name) == subject.lower())
    topic = (args.get("topic") or "").strip()
    if topic:
        q = q.filter(Question.topic.ilike(f"%{topic}%"))
    text = (args.get("q") or "").strip()
    if text:
        q = q.filter(Question.text.ilike(f"%{text}%"))
    q = q.order_by(Question.reviewed_at.desc(), Question.id.desc())
    result = _paged(q, args, lambda x: x.to_dict())

    def group(col):
        rows = db.session.query(col, func.count(Question.id)).filter(
            Question.institution_id == institution_id, Question.status == "approved").group_by(col).all()
        return dict(rows)

    result["summary"] = {"total": base.count(), "by_difficulty": group(Question.difficulty),
                         "by_level": group(Question.level), "by_subject": group(Question.subject_name),
                         "by_type": group(Question.question_type)}
    return result
