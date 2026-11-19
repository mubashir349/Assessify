"""Phase 11: what an admit card says - shared by the PDF and the email text, so the two never disagree.

Times are stored as naive UTC. Emails and PDFs have no browser to convert them, so they are written in APP_TIMEZONE
(Asia/Karachi by default) with the zone named next to them.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from app.modules.roster.service import display_code

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover  (Python < 3.9 is not supported anyway)
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception


def _zone(name: str):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):   # Windows without the tzdata package, or a typo in .env
        return timezone.utc


def local(dt: datetime | None, tz_name: str) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_zone(tz_name))


def zone_label(tz_name: str, sample: datetime | None = None) -> str:
    """'PKT, UTC+05:00' style label for the zone used in the text."""
    d = local(sample or datetime.now(timezone.utc).replace(tzinfo=None), tz_name)
    offset = d.strftime("%z")
    off = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    abbr = d.tzname() or ""
    return f"{abbr}, {off}" if abbr and not abbr.startswith(("+", "-")) and abbr != "UTC" else off


def fmt(dt: datetime | None, tz_name: str) -> str:
    d = local(dt, tz_name)
    return d.strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ") if d else "not set"


@dataclass
class Card:
    candidate_name: str
    roll_number: str | None
    department_term: str
    department: str
    email: str | None
    institution: str
    test_name: str
    level: str
    access_code: str
    login_with: str          # "dob" | "pin"
    pin: str | None
    timing_mode: str | None  # "flexible" | "fixed" | None
    starts: str
    ends: str
    duration_minutes: int | None
    zone: str
    login_url: str
    subjects: list[str]
    question_count: int


def build(c, login_url: str, tz_name: str, term: str) -> Card:
    t, s = c.test, c.test.schedule
    rows = [r for r in t.rows if r.department_id == c.department_id]
    return Card(
        candidate_name=c.full_name, roll_number=c.roll_number, department_term=term, department=c.department.name,
        email=c.email, institution=c.institution.display_name if c.institution else "", test_name=t.name,
        level=t.level, access_code=display_code(c.access_code), login_with=c.login_with, pin=c.pin,
        timing_mode=s.timing_mode if s else None, starts=fmt(s.starts_at if s else None, tz_name),
        ends=fmt(s.ends_at if s else None, tz_name), duration_minutes=s.duration_minutes if s else None,
        zone=zone_label(tz_name, s.starts_at if s else None), login_url=login_url,
        subjects=list(dict.fromkeys(r.subject_name for r in rows)), question_count=sum(r.question_count for r in rows))


def schedule_lines(card: Card) -> list[tuple[str, str]]:
    if card.timing_mode == "fixed":
        return [("Test starts", f"{card.starts} (everyone starts together)"),
                ("Test ends", f"{card.ends} (the test closes for everyone at this time)"),
                ("Duration", f"{card.duration_minutes} minutes"),
                ("Time zone", card.zone)]
    return [("Window opens", card.starts),
            ("Window closes", card.ends),
            ("Your time", f"{card.duration_minutes} minutes from the moment you start (start early enough to finish "
                          "before the window closes)"),
            ("Time zone", card.zone)]


def second_step(card: Card) -> str:
    return f"PIN {card.pin}" if card.login_with == "pin" else "your date of birth"


def instructions(card: Card) -> list[str]:
    return [
        "Keep this admit card private. Anyone with your access code and "
        + ("PIN" if card.login_with == "pin" else "date of birth") + " can sign in as you.",
        f"Sign in at {card.login_url} with your access code and {second_step(card)}.",
        "Sign in 10 to 15 minutes early and use a stable internet connection, a charged device and an up-to-date "
        "browser.",
        "You can take the test once. Do not close or refresh the test tab while answering.",
        f"If any detail on this card is wrong, contact {card.institution} before the test.",
    ]


def email_text(card: Card) -> tuple[str, str]:
    subject = f"Admit card: {card.test_name} ({card.institution})"
    sched = "\n".join(f"  {label}: {value}" for label, value in schedule_lines(card))
    lines = [
        f"Dear {card.candidate_name},",
        "",
        f"{card.institution} has registered you for the online test \"{card.test_name}\". You are receiving this "
        "email because it contains your admit card, which you need to sign in to the test.",
        "",
        "Test schedule:",
        sched,
        "",
        "How to sign in:",
        f"  Website: {card.login_url}",
        f"  Access code: {card.access_code}",
        f"  Second step: {second_step(card)}",
        "",
        "Your admit card is attached as a PDF. Keep it private: anyone with your access code and "
        + ("PIN" if card.login_with == "pin" else "date of birth") + " can sign in as you.",
        "",
        f"If any detail is wrong, please contact {card.institution} before the test.",
        "",
        "This email was sent automatically by Assessify. Please do not reply to it.",
    ]
    return subject, "\n".join(lines)
