"""Phase 11: draws one admit card as an A4 PDF with fpdf2 (pure Python, nothing to install on the system).

Fonts: the built-in PDF fonts only cover English letters. For names in Urdu, Arabic or other scripts a Unicode .ttf
is needed: ADMIT_CARD_FONT in .env, else Arial on Windows / DejaVu on Linux when present. Without one, letters the
font cannot show are replaced by "?" instead of crashing.
"""
import os
from datetime import datetime, timezone

from fpdf import FPDF

from app.modules.admit_cards.content import Card, fmt, instructions, schedule_lines, second_step

_CANDIDATE_FONTS = [
    ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
    ("C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\segoeuib.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
]

INK = (17, 24, 39)
MUTED = (100, 110, 125)
ACCENT = (79, 70, 229)
SOFT = (238, 240, 255)
LINE = (220, 224, 232)


def _pick_font(configured: str) -> tuple[str | None, str | None]:
    if configured and os.path.isfile(configured):
        return configured, None
    for regular, bold in _CANDIDATE_FONTS:
        if os.path.isfile(regular):
            return regular, bold if bold and os.path.isfile(bold) else None
    return None, None


class _Doc(FPDF):
    def __init__(self, font_path: str):
        super().__init__(format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(16, 16, 16)
        regular, bold = _pick_font(font_path)
        if regular:
            self.add_font("Body", "", regular)
            self.add_font("Body", "B", bold or regular)
            self.family, self.unicode = "Body", True
            try:      # joins and orders Urdu / Arabic letters correctly (needs the uharfbuzz package)
                self.set_text_shaping(True)
            except Exception:  # noqa: BLE001  uharfbuzz missing: names still print, just not joined
                pass
        else:
            self.family, self.unicode = "Helvetica", False

    def t(self, text) -> str:
        text = "" if text is None else str(text)
        return text if self.unicode else text.encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False, color=INK):
        self.set_font(self.family, "B" if bold else "", size)
        self.set_text_color(*color)


def fit(pdf, text: str, width: float, size: float, smallest: float, bold: bool, color) -> None:
    """Sets the largest font size (down to `smallest`) at which the text fits on one line."""
    while True:
        pdf.font(size, bold, color)
        if size <= smallest or pdf.get_string_width(pdf.t(text)) <= width:
            return
        size -= 0.5


def render(card: Card, font_path: str = "") -> bytes:
    pdf = _Doc(font_path)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    # header band
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, pdf.w, 34, style="F")
    pdf.set_xy(pdf.l_margin, 9)
    fit(pdf, card.institution, w, 17, 11, True, (255, 255, 255))      # long names shrink instead of running off the page
    pdf.cell(w, 8, pdf.t(card.institution), new_x="LMARGIN", new_y="NEXT")
    sub = f"ADMIT CARD  |  {card.test_name}  |  {card.level}"
    fit(pdf, sub, w, 11, 8, False, (225, 228, 255))
    pdf.cell(w, 7, pdf.t(sub), new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(42)

    # candidate
    pdf.font(9, True, MUTED)
    pdf.cell(w, 5, "CANDIDATE", new_x="LMARGIN", new_y="NEXT")
    pdf.font(18, True)
    pdf.multi_cell(w, 9, pdf.t(card.candidate_name), align="L", new_x="LMARGIN", new_y="NEXT")
    details = [("Roll number", card.roll_number or "not given"), (card.department_term, card.department)]
    if card.email:
        details.append(("Email", card.email))
    _pairs(pdf, details, w)
    pdf.ln(3)

    # sign-in box
    top = pdf.get_y()
    pdf.set_fill_color(*SOFT)
    pdf.set_draw_color(*ACCENT)
    pdf.rect(pdf.l_margin, top, w, 34, style="DF")
    pdf.set_xy(pdf.l_margin + 6, top + 5)
    pdf.font(9, True, MUTED)
    pdf.cell(w / 2 - 6, 5, "ACCESS CODE")
    pdf.cell(w / 2 - 6, 5, "SECOND STEP", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 6)
    pdf.font(22, True, ACCENT)
    pdf.cell(w / 2 - 6, 13, pdf.t(card.access_code))
    pdf.font(15 if card.login_with == "pin" else 12, True, INK)
    pdf.cell(w / 2 - 6, 13, pdf.t(second_step(card).replace("PIN ", "PIN  ")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 6)
    pdf.font(9.5, False, MUTED)
    pdf.multi_cell(w - 12, 5, pdf.t(f"Sign in at: {card.login_url}"), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(top + 40)

    # schedule
    _heading(pdf, "TEST SCHEDULE", w)
    mode = "Fixed time: everyone starts and ends together" if card.timing_mode == "fixed" else \
        "Flexible window: start any time inside the window"
    pdf.font(10, False, MUTED)
    pdf.cell(w, 6, pdf.t(mode), new_x="LMARGIN", new_y="NEXT")
    _pairs(pdf, schedule_lines(card), w)
    if card.subjects:
        _pairs(pdf, [("Paper", f"{card.question_count} questions: {', '.join(card.subjects)}")], w)
    pdf.ln(3)

    # instructions
    _heading(pdf, "INSTRUCTIONS", w)
    pdf.font(10)
    for i, line in enumerate(instructions(card), 1):
        pdf.multi_cell(w, 5.6, pdf.t(f"{i}.  {line}"), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)

    # footer (auto page break off, so the footer never spills onto a second page)
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(-26)
    pdf.set_draw_color(*LINE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)
    pdf.font(8.5, False, MUTED)
    issued = fmt(datetime.now(timezone.utc).replace(tzinfo=None), "UTC")
    pdf.multi_cell(w, 4.5, pdf.t(f"Issued by {card.institution} through Assessify on {issued} (UTC). This card is "
                                 "only valid for the test named above."), align="L", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _heading(pdf: _Doc, text: str, w: float) -> None:
    pdf.font(9, True, ACCENT)
    pdf.cell(w, 6, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*LINE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(2)


def _pairs(pdf: _Doc, pairs, w: float) -> None:
    label_w = 38
    for label, value in pairs:
        pdf.font(10, True, MUTED)
        y = pdf.get_y()
        pdf.cell(label_w, 6, pdf.t(label))
        pdf.set_xy(pdf.l_margin + label_w, y)
        pdf.font(10.5)
        pdf.multi_cell(w - label_w, 6, pdf.t(value), align="L", new_x="LMARGIN", new_y="NEXT")
