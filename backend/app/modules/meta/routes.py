"""GET /meta  (public) - every dropdown / label list the frontend needs, so the frontend hardcodes none of them."""
from flask import Blueprint

from app.common.responses import ok
from app.models.department import DEFAULT_LEVEL, DEFAULT_MODE, LEVELS, MODES
from app.models.institution import INSTITUTION_TYPES, STATUSES

bp = Blueprint("meta", __name__)


@bp.get("")
def meta():
    return ok({
        "institution_types": list(INSTITUTION_TYPES),
        "institution_statuses": list(STATUSES),
        "levels": [{"value": k, **v} for k, v in LEVELS.items()],
        "modes": [{"value": k, **v} for k, v in MODES.items()],
        "defaults": {"level": DEFAULT_LEVEL, "mode": DEFAULT_MODE},
    })
