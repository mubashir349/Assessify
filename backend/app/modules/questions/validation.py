"""Checks one question - used for AI output, for admin edits and again right before approval.

clean_question(...) returns a tidy dict or raises QuestionInvalid({field: message}).
"""
import re

from app.models.question import DIFFICULTIES, QUESTION_TYPES, TRUE_FALSE_OPTIONS

TEXT_MIN, TEXT_MAX = 10, 2000
OPTION_MAX = 300
EXPLANATION_MAX = 2000
TOPIC_MAX = 120
AI_MCQ_OPTIONS = 4                 # the AI must return exactly 4 options
EDIT_MCQ_MIN, EDIT_MCQ_MAX = 2, 6  # an admin may edit an MCQ to have 2-6 options
MARKS_MIN, MARKS_MAX = 1, 100
LETTERS = "ABCDEF"
_LABEL = re.compile(r"^\s*(?:\(?[A-Fa-f][\).:]|[A-Fa-f]\s*[-–])\s+")   # "A) ", "(b) ", "C. ", "D - "


class QuestionInvalid(Exception):
    def __init__(self, errors: dict):
        super().__init__("invalid question")
        self.errors = errors


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _in_range(i: int, options: list[str]) -> int | None:
    return i if 0 <= i < len(options) else None


def _answer_index(raw, options: list[str]) -> int | None:
    """Accepts 0-based int, a letter ('B'), the option text, or True/False for true/false questions."""
    if isinstance(raw, bool):
        raw = "True" if raw else "False"
    if isinstance(raw, int):
        return _in_range(raw, options)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.isdigit():
        return _in_range(int(s), options)
    if len(s) == 1 and s.upper() in LETTERS[:len(options)]:
        return LETTERS.index(s.upper())
    s = _LABEL.sub("", s).strip().lower()
    return next((i for i, opt in enumerate(options) if opt.lower() == s), None)


def clean_question(data: dict, question_type: str, *, from_ai: bool) -> dict:
    """Validate + normalise. `from_ai=True` is stricter on options and more forgiving on field names."""
    if not isinstance(data, dict):
        raise QuestionInvalid({"question": "Not a question object."})
    errors: dict = {}

    text = _str(data.get("text") if "text" in data else data.get("question"))
    if len(text) < TEXT_MIN:
        errors["text"] = f"Question text must be at least {TEXT_MIN} characters."
    elif len(text) > TEXT_MAX:
        errors["text"] = f"Question text must be at most {TEXT_MAX} characters."

    options = list(TRUE_FALSE_OPTIONS) if question_type == "true_false" else _clean_options(data, from_ai, errors)

    correct = None
    if "options" not in errors:
        raw_answer = next((data[k] for k in ("correct_index", "correct_answer", "answer") if k in data), None)
        correct = _answer_index(raw_answer, options)
        if correct is None:
            errors["correct_index"] = "Choose which option is correct."

    explanation = _str(data.get("explanation"))
    if len(explanation) > EXPLANATION_MAX:
        errors["explanation"] = f"Explanation must be at most {EXPLANATION_MAX} characters."
    topic = _str(data.get("topic"))
    if len(topic) > TOPIC_MAX:
        if from_ai:
            topic = topic[:TOPIC_MAX]
        else:
            errors["topic"] = f"Topic must be at most {TOPIC_MAX} characters."

    cleaned = {"text": text, "options": options, "correct_index": correct,
               "explanation": explanation or None, "topic": topic or None}

    if not from_ai:   # extra fields an admin may change while editing
        _clean_admin_extras(data, cleaned, errors)

    if question_type not in QUESTION_TYPES:
        errors["question_type"] = "Unknown question type."
    if errors:
        raise QuestionInvalid(errors)
    return cleaned


def _clean_options(data: dict, from_ai: bool, errors: dict) -> list[str]:
    raw = data.get("options")
    if from_ai:
        if raw is None:                                   # some models call the field "choices"
            raw = data.get("choices")
        if isinstance(raw, dict):                         # {"A": "...", "B": "..."} -> list in A, B, C order
            raw = [v for _, v in sorted(raw.items(), key=lambda kv: str(kv[0]))]
    if not isinstance(raw, list):
        errors["options"] = "Options must be a list."
        return []
    options = [_str(o) for o in raw]
    if from_ai:
        options = [_LABEL.sub("", o).strip() for o in options]
    problem = _options_problem(options, from_ai)
    if problem:
        errors["options"] = problem
    return options


def _options_problem(options: list[str], from_ai: bool) -> str | None:
    lo, hi = (AI_MCQ_OPTIONS, AI_MCQ_OPTIONS) if from_ai else (EDIT_MCQ_MIN, EDIT_MCQ_MAX)
    if any(not o for o in options):
        return "Options cannot be empty."
    if not lo <= len(options) <= hi:
        return f"Exactly {lo} options are required." if lo == hi else f"Give between {lo} and {hi} options."
    if any(len(o) > OPTION_MAX for o in options):
        return f"Each option must be at most {OPTION_MAX} characters."
    if len({o.lower() for o in options}) != len(options):
        return "Options must all be different."
    return None


def _clean_admin_extras(data: dict, cleaned: dict, errors: dict) -> None:
    if "difficulty" in data:
        if data["difficulty"] not in DIFFICULTIES:
            errors["difficulty"] = "Choose one of: " + ", ".join(DIFFICULTIES) + "."
        else:
            cleaned["difficulty"] = data["difficulty"]
    if "marks" in data:
        m = data["marks"]
        if isinstance(m, bool) or not isinstance(m, int) or not MARKS_MIN <= m <= MARKS_MAX:
            errors["marks"] = f"Marks must be a whole number from {MARKS_MIN} to {MARKS_MAX}."
        else:
            cleaned["marks"] = m


def normalised_key(text: str) -> str:
    """Used to spot duplicate questions: lowercase letters/digits only."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())
