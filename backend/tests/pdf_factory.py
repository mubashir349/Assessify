"""Builds small but real PDF files in memory for the Phase 3 tests (no sample files needed in the repo)."""
import io

from pypdf import PdfReader, PdfWriter

SAMPLE_TEXT = [
    "Chapter 3: Photosynthesis",
    "Photosynthesis is the process by which green plants make glucose from carbon dioxide and water.",
    "It takes place inside chloroplasts, which contain the green pigment chlorophyll.",
    "Light energy is absorbed by chlorophyll and converted into chemical energy.",
    "Oxygen is released as a by-product when water molecules are split during the light reactions.",
    "The Calvin cycle uses ATP and NADPH to fix carbon dioxide into sugars in the stroma.",
    "Factors that affect the rate of photosynthesis include light intensity, temperature and CO2 level.",
    "Stomata on the leaf surface allow carbon dioxide to enter and oxygen to leave the leaf.",
]


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines=None, pages: int = 1) -> bytes:
    """A valid text PDF (Helvetica) with the given lines on every page."""
    lines = SAMPLE_TEXT if lines is None else lines
    objs: list[bytes] = []
    page_ids = [3 + i * 2 for i in range(pages)]
    font_id = 3 + pages * 2
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(("<< /Type /Pages /Kids [" + " ".join(f"{p} 0 R" for p in page_ids) + f"] /Count {pages} >>").encode())
    for i in range(pages):
        content = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({_esc(line)}) '" for line in lines) + " ET"
        cbytes = content.encode("latin-1")
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 {font_id} 0 R >> >> "
                     f"/Contents {page_ids[i] + 1} 0 R >>").encode())
        objs.append(f"<< /Length {len(cbytes)} >>\nstream\n".encode() + cbytes + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def blank_pdf(pages: int = 2) -> bytes:
    """A real PDF with no text at all - what a scanned document looks like to a text extractor."""
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=842)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def encrypted_pdf(user_password: str = "secret") -> bytes:
    """A text PDF protected with a password (empty user_password = opens without a password)."""
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(make_pdf())))
    w.encrypt(user_password=user_password, owner_password="owner-pass", algorithm="RC4-128")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def photo_pdf(pages: int = 2, size=(1200, 1600)) -> bytes:
    """A PDF made only of pictures - like phone photos of book pages. No text layer at all."""
    from PIL import Image, ImageDraw
    imgs = []
    for i in range(pages):
        img = Image.new("RGB", size, (250, 248, 240))
        d = ImageDraw.Draw(img)
        for y in range(120, size[1] - 120, 60):              # dark "lines of text"
            d.rectangle([100, y, size[0] - 100 - (i * 37 + y) % 300, y + 18], fill=(40, 40, 40))
        imgs.append(img)
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=150)
    return buf.getvalue()


def mixed_pdf(layout: str) -> bytes:
    """Builds a PDF page by page. Letters:
    T = typed text page (each one has its own distinct text: 'Typed page N ...')
    P = photo of a page (picture only)
    F = typed text page that also contains a big figure / diagram
    W = photo page with a tiny scanner-app watermark text ('Scanned with CamScanner')"""
    w = PdfWriter()
    for no, kind in enumerate(layout, start=1):
        typed = [f"Typed page {no}: " + line for line in SAMPLE_TEXT]
        if kind == "T":
            w.append(PdfReader(io.BytesIO(make_pdf(typed))))
            continue
        page = w.add_page(PdfReader(io.BytesIO(photo_pdf(1))).pages[0])
        if kind in "FW":
            overlay = PdfReader(io.BytesIO(make_pdf(typed if kind == "F" else ["Scanned with CamScanner"]))).pages[0]
            page.merge_page(overlay)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
