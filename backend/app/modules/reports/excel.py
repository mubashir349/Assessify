"""Phase 11: the test report as an Excel workbook (.xlsx), next to the existing CSV.

Sheets: Summary (the numbers at the top of the Reports page), Results (one row per candidate, same columns and
filters as the CSV), By field and By subject. Times are written in APP_TIMEZONE as real Excel dates.
Text that starts with = + - @ is stored as text, never as a formula (a name typed as "=HYPERLINK(...)" stays text).
"""
import io
from datetime import datetime

from flask import current_app
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.common.utils import utcnow
from app.modules.admit_cards.content import local, zone_label
from app.modules.reports.service import _filter_rows, load, mail_status, stats

HEAD_FILL = PatternFill("solid", fgColor="4F46E5")
HEAD_FONT = Font(bold=True, color="FFFFFF")
BOLD = Font(bold=True)


def _put(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        cell.data_type = "s"            # keep it as text, never a formula
    return cell


def _table(ws, header: list[str], rows: list[list], start_row: int = 1) -> None:
    for j, h in enumerate(header, 1):
        c = _put(ws, start_row, j, h)
        c.fill, c.font, c.alignment = HEAD_FILL, HEAD_FONT, Alignment(vertical="center", wrap_text=True)
    for i, r in enumerate(rows, start_row + 1):
        for j, v in enumerate(r, 1):
            _put(ws, i, j, v)
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    for j, h in enumerate(header, 1):
        width = max([len(str(h))] + [len(str(r[j - 1])) for r in rows if r[j - 1] is not None] or [10])
        ws.column_dimensions[get_column_letter(j)].width = min(max(width + 2, 9), 45)


def _when(iso_text: str | None, tz: str):
    if not iso_text:
        return None
    dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00")).replace(tzinfo=None)
    return local(dt, tz).replace(tzinfo=None)


def export_xlsx(institution_id: int, test_id, args) -> tuple[str, bytes]:
    tz = current_app.config.get("APP_TIMEZONE", "Asia/Karachi")
    test, candidates, rows = load(institution_id, test_id)
    data = stats(test, candidates, rows, utcnow())
    s = data["summary"]
    zone = zone_label(tz)
    wb = Workbook()

    # Summary ---------------------------------------------------------------------------------------------------
    ws = wb.active
    ws.title = "Summary"
    sched = test.schedule
    lines = [
        ("Test", test.name), ("Level", test.level),
        ("Window opens", local(sched.starts_at, tz).replace(tzinfo=None) if sched else None),
        ("Window closes", local(sched.ends_at, tz).replace(tzinfo=None) if sched else None),
        ("Duration (minutes)", sched.duration_minutes if sched else None),
        ("Times shown in", zone), (None, None),
        ("Candidates on roster", s["candidates"]), ("Submitted", s["submitted"]),
        ("In progress", s["in_progress"]), ("Not attempted", s["not_attempted"]),
        ("Submitted automatically (time up)", s["auto_submitted"]), (None, None),
        ("Average %", s["average_percent"]), ("Median %", s["median_percent"]),
        ("Highest %", s["highest_percent"]), ("Lowest %", s["lowest_percent"]), (None, None),
        ("Report created", local(utcnow(), tz).replace(tzinfo=None)),
    ]
    for i, (label, value) in enumerate(lines, 1):
        if label is None:
            continue
        _put(ws, i, 1, label).font = BOLD
        c = _put(ws, i, 2, value)
        if isinstance(value, datetime):
            c.number_format = "dd-mmm-yyyy hh:mm AM/PM"
    row = len(lines) + 2
    _put(ws, row, 1, "Score distribution").font = BOLD
    for i, b in enumerate(s["distribution"], row + 1):
        _put(ws, i, 1, b["label"])
        _put(ws, i, 2, b["count"])
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 34

    # Results (same columns and filters as the CSV) ----------------------------------------------------------------
    ws = wb.create_sheet("Results")
    header = ["Rank", "Name", "Roll number", "Email", "Field", "Status", "Score", "Max score", "Percent",
              "Answered", "Questions", f"Submitted at ({zone})", "Submitted by", "Locks", "Result email"]
    body = []
    for r in _filter_rows(rows, args):
        body.append([r["rank"], r["full_name"], r["roll_number"], r["email"], r["department"]["name"], r["status"],
                     r["score"], r["max_score"], r["percent"], r["answered"], r["questions"],
                     _when(r["submitted_at"], tz), r["submit_reason"], r["lock_count"],
                     mail_status(r) if r["status"] == "submitted" else ""])
    _table(ws, header, body)
    for i in range(2, len(body) + 2):
        ws.cell(row=i, column=12).number_format = "dd-mmm-yyyy hh:mm AM/PM"
    ws.column_dimensions["L"].width = 22
    ws.auto_filter.ref = ws.dimensions

    # By field / By subject ----------------------------------------------------------------------------------------
    ws = wb.create_sheet("By field")
    _table(ws, ["Field / department", "Candidates", "Submitted", "Average %", "Highest %"],
           [[d["name"], d["candidates"], d["submitted"], d["average_percent"], d["highest_percent"]]
            for d in data["by_department"]])
    ws = wb.create_sheet("By subject")
    _table(ws, ["Subject", "Questions answered", "Correct", "Unanswered", "Accuracy %"],
           [[x["subject"], x["questions"], x["correct"], x["unanswered"], x["accuracy_percent"]]
            for x in data["by_subject"]])

    buf = io.BytesIO()
    wb.save(buf)
    safe = "".join(ch if ch.isalnum() else "-" for ch in test.name).strip("-")[:60] or "test"
    return f"report-{safe}.xlsx", buf.getvalue()
