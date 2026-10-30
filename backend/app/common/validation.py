"""Tiny request-validation helpers (kept dependency-free)."""
import re

from flask import request

from app.common.errors import ApiError

FIX_FIELDS = "Please fix the highlighted fields."
# Domain part is "label(.label)+" with no dots inside a label, so the regex never backtracks.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("BAD_REQUEST", "Request body must be a JSON object.", 400)
    return data


def text(data: dict, key: str, label: str, errors: dict, *, required=True, min_len=1, max_len=255) -> str:
    """Reads a trimmed string field and records a message in `errors` if it is invalid."""
    value = data.get(key)
    value = value.strip() if isinstance(value, str) else ""
    if not value:
        if required:
            errors[key] = f"{label} is required."
        return ""
    if len(value) < min_len:
        errors[key] = f"{label} must be at least {min_len} characters."
    elif len(value) > max_len:
        errors[key] = f"{label} must be at most {max_len} characters."
    return value


def raise_if(errors: dict) -> None:
    if errors:
        raise ApiError("VALIDATION_ERROR", FIX_FIELDS, 422, errors)
