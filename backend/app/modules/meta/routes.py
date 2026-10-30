"""GET /meta  (public) - every dropdown / label list the frontend needs, so the frontend hardcodes none of them."""
from flask import Blueprint, current_app

from app.common.responses import ok
from app.models.aptitude_test import (ANY_DIFFICULTY, MAX_DURATION, MAX_PER_ROW, MIN_DURATION, POOL_FACTOR,
                                      RESULT_RELEASES, TIMING_MODES)
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
        # Phase 4
        "row_difficulties": [{"value": ANY_DIFFICULTY, "label": "Any"}] + [{"value": k, "label": v} for k, v in DIFFICULTIES.items()],
        "timing_modes": [{"value": k, **v} for k, v in TIMING_MODES.items()],
        "result_releases": [{"value": k, "label": v} for k, v in RESULT_RELEASES.items()],
        "pool_factor": POOL_FACTOR,
        "test_limits": {"max_per_row": MAX_PER_ROW, "min_duration": MIN_DURATION, "max_duration": MAX_DURATION},
    })
