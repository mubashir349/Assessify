"""GET /meta  (public) - every dropdown / label list the frontend needs, so the frontend hardcodes none of them."""
from flask import Blueprint, current_app

from app.common.responses import ok
from app.models.department import DEFAULT_LEVEL, DEFAULT_MODE, LEVELS, MODES
from app.models.institution import INSTITUTION_TYPES, STATUSES
from app.models.question import DIFFICULTIES, QUESTION_STATUSES, QUESTION_TYPES

bp = Blueprint("meta", __name__)


@bp.get("")
def meta():
    return ok({
        "institution_types": list(INSTITUTION_TYPES),
        "institution_statuses": list(STATUSES),
        "levels": [{"value": k, **v} for k, v in LEVELS.items()],
        "modes": [{"value": k, **v} for k, v in MODES.items()],
        "defaults": {"level": DEFAULT_LEVEL, "mode": DEFAULT_MODE},
        # Phase 3
        "question_types": [{"value": k, "label": v} for k, v in QUESTION_TYPES.items()],
        "difficulties": [{"value": k, "label": v} for k, v in DIFFICULTIES.items()],
        "question_statuses": list(QUESTION_STATUSES),
        "generation_limits": {"max_upload_mb": current_app.config["MAX_UPLOAD_MB"],
                              "max_questions": current_app.config["MAX_QUESTIONS_PER_ATTEMPT"],
                              "max_files": current_app.config["MAX_PDFS_PER_GENERATION"],
                              "description_min_words": current_app.config["DESCRIPTION_MIN_WORDS"]},
    })
