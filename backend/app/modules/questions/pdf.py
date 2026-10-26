"""PDF upload checks + text extraction (pypdf).

The upload is read straight into memory (Flask already caps its size with MAX_CONTENT_LENGTH), so the file is never
written to disk: no temporary files to clean up, no server paths, nothing executable. Only the extracted text and
some safe metadata (name, pages, length) are kept.

Every page is classified on its own:
  * typed page  - has a real text layer (normal PDFs, also scans that already went through a scanner app's OCR)
  * photo page  - (almost) no text, but a big picture: a phone photo / scan of a book page or handwritten notes
Typed pages are read here. Photo pages are handed to the AI as pictures (only if the provider can see images - Gemini can),
and service.py puts everything back together in page order. Pictures inside typed pages (diagrams, figures) are ignored.
Without an image-capable provider, photo pages are skipped and the caller is told how many - nothing is invented.
"""
import hashlib
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.common.errors import ApiError

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)   # pypdf warns loudly about slightly broken files

MIN_IMAGE_SIDE = 300           # smaller pictures are logos / icons, not photographed pages
PHOTO_PAGE_MAX_TEXT = 80       # a page with less typed text than this (letters/digits) + a big picture = photo page
EST_CHARS_PER_PHOTO_PAGE = 1000  # rough guess, used to stop collecting pages once the AI text limit is surely filled


@dataclass
class ExtractedPdf:
    filename: str            # cleaned original name, for display only
    pages: int               # pages in the document
    text: str                # typed text only (normalised, cut to the AI limit) - final text if no photo pages
    total_chars: int         # typed characters extracted before cutting
    truncated: bool          # not every page / character will reach the AI
    sha256: str              # fingerprint of the uploaded bytes (duplicate-request check)
    typed_pages: int = 0
    # page order of the document: ("text", page_no, text) or ("photo", page_no, jpeg_bytes)
    parts: list[tuple] = field(default_factory=list)
    skipped_photo_pages: int = 0   # photo pages that will NOT be read (provider can't see images / page limit)

    @property
    def images(self) -> list[bytes]:
        return [p[2] for p in self.parts if p[0] == "photo"]

    @property
    def needs_ocr(self) -> bool:
        return any(p[0] == "photo" for p in self.parts)


class PillowMissing(Exception):
    """Pillow (needed to read pictures inside PDFs) is not installed - see pillow_available()."""


def pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def page_picture(page, max_side: int) -> bytes | None:
    """The biggest picture on a page, resized to at most `max_side` px, as JPEG. None if there is no big picture.
    Raises PillowMissing if Pillow is not installed. Any problem with the picture itself just returns None."""
    try:
        from PIL import Image   # imported here so plain text PDFs never touch Pillow
    except Exception as exc:  # noqa: BLE001
        raise PillowMissing() from exc
    try:
        pics = [img.image for img in page.images if img.image is not None]
        pics = [p for p in pics if max(p.size) >= MIN_IMAGE_SIDE]
        if not pics:
            return None
        pic = max(pics, key=lambda p: p.size[0] * p.size[1]).convert("RGB")
        pic.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        pic.save(buf, "JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception:  # noqa: BLE001  unsupported / broken picture on this page: treat as "no picture"
        log.info("Could not read the pictures on a page", exc_info=True)
        return None


def _letters(text: str) -> int:
    return len(re.sub(r"\W+", "", text))


def display_name(raw: str | None) -> str:
    """Original file name for display only: drop any folder part and odd characters, cap the length."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip() or "document.pdf"
    return name[-200:]


def normalise(text: str) -> str:
    """Tidy extracted text but keep paragraphs: unify line endings, re-join hyphenated words, squeeze spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # "exam-\nple" -> "example"
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def cut(text: str, limit: int) -> tuple[str, bool]:
    """Shorten to `limit` characters, preferably at a paragraph or sentence end."""
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    for sep in ("\n\n", ". ", "\n"):
        pos = head.rfind(sep)
        if pos > limit * 0.6:
            return head[:pos + len(sep)].strip(), True
    return head.strip(), True


def extract(file_storage, *, max_pages: int, min_chars: int, max_chars: int, allow_images: bool = False,
            max_image_pages: int = 20, image_max_side: int = 1600) -> ExtractedPdf:
    """Validate an uploaded PDF (werkzeug FileStorage) and classify its pages. Raises ApiError with a clear code.
    allow_images=True: photo pages are returned as pictures (in `parts`) for the AI to read."""
    if file_storage is None or not file_storage.filename:
        raise ApiError("VALIDATION_ERROR", "Please fix the highlighted fields.", 422, {"file": "Choose a PDF file to upload."})

    name = display_name(file_storage.filename)
    if not name.lower().endswith(".pdf"):
        raise ApiError("UNSUPPORTED_FILE_TYPE", "Only PDF files are supported.", 415, {"file": "Upload a .pdf file."})

    data = file_storage.read()          # size already limited by MAX_CONTENT_LENGTH
    if not data:
        raise ApiError("EMPTY_FILE", "The uploaded file is empty.", 422, {"file": "The file is empty."})
    # Do not trust the extension or the browser's MIME type: a real PDF starts with "%PDF-" near the top.
    if b"%PDF-" not in data[:1024]:
        raise ApiError("INVALID_PDF", "This file is not a valid PDF.", 422, {"file": "The file is not a real PDF."})

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            # Many "protected" PDFs only block printing/copying and open with an empty password - try that.
            try:
                opened = reader.decrypt("")
            except Exception:   # noqa: BLE001  (e.g. unsupported encryption)
                opened = 0
            if not opened:
                raise ApiError("PDF_ENCRYPTED", "This PDF is password-protected. Remove the password and upload it again.",
                               422, {"file": "Password-protected PDFs are not supported."})
        page_count = len(reader.pages)
    except ApiError:
        raise
    except (PdfReadError, Exception):  # noqa: BLE001  any parser failure = unreadable file
        log.info("PDF could not be parsed", exc_info=True)
        raise ApiError("INVALID_PDF", "This PDF is damaged or could not be read.", 422, {"file": "The PDF could not be read."})

    if page_count == 0:
        raise ApiError("INVALID_PDF", "This PDF has no pages.", 422, {"file": "The PDF has no pages."})

    parts: list[tuple] = []
    typed_pages = photos_read = skipped = 0
    no_pillow = False
    estimate = 0                    # characters the AI will get, counting a photo page as EST_CHARS_PER_PHOTO_PAGE
    stopped_early = False
    for no, page in enumerate(reader.pages[:max_pages], start=1):
        if estimate > max_chars:     # the AI text limit is already full - later pages would be cut anyway
            stopped_early = True
            break
        try:
            chunk = page.extract_text() or ""
        except Exception:  # noqa: BLE001  one bad page should not fail the whole document
            log.info("Skipping page %s: text could not be read", no, exc_info=True)
            chunk = ""
        if _letters(chunk) >= PHOTO_PAGE_MAX_TEXT:
            parts.append(("text", no, chunk))
            typed_pages += 1
            estimate += len(chunk)
            continue
        try:
            picture = page_picture(page, image_max_side)
        except PillowMissing:
            no_pillow = True         # can't look at pictures - a typed PDF still works, photo pages can't
            picture = None
        if picture is None:          # little text and no picture: a blank page, title or divider
            if chunk.strip():
                parts.append(("text", no, chunk))
                estimate += len(chunk)
            continue
        if allow_images and photos_read < max_image_pages:
            parts.append(("photo", no, picture))
            photos_read += 1
            estimate += EST_CHARS_PER_PHOTO_PAGE
        else:
            skipped += 1
            if chunk.strip():
                parts.append(("text", no, chunk))

    typed = normalise("\n\n".join(p[2] for p in parts if p[0] == "text"))
    sha = hashlib.sha256(data).hexdigest()
    reached_all = not stopped_early and page_count <= max_pages

    if photos_read == 0 and _letters(typed) < min_chars:
        if no_pillow:
            log.error("Pillow is not installed: photo / scanned PDF pages cannot be read. Run: pip install -r requirements.txt")
            raise ApiError("SERVER_SETUP", "This PDF looks like photos or scans, but the server cannot read pictures yet: "
                           "the Pillow package is missing. Ask the administrator to run 'pip install -r requirements.txt' "
                           "in backend/ and restart the server.", 503,
                           {"file": "Server setup: Pillow is not installed."})
        if skipped:
            raise ApiError("PDF_NO_TEXT", "This PDF contains photos or scans instead of typed text. Reading pictures needs "
                           "an AI provider that understands images - set AI_PROVIDER=gemini in backend/.env, or upload a "
                           "PDF with selectable text.", 422, {"file": "Photos / scans need AI_PROVIDER=gemini."})
        raise ApiError("PDF_NO_TEXT", "Not enough readable text or page pictures were found in this PDF. "
                       "Please upload another PDF.", 422, {"file": "No usable text or page pictures found."})

    short, was_cut = cut(typed, max_chars)
    return ExtractedPdf(filename=name, pages=page_count, text=short, total_chars=len(typed),
                        truncated=was_cut or not reached_all or skipped > 0, sha256=sha, typed_pages=typed_pages,
                        parts=parts, skipped_photo_pages=skipped)


_HEADING = re.compile(
    r"^(?:(?i:chapter|unit|lesson|section|topic|part|module|week)\s*[\dIVXivx]+[\s.:\-–]*.{2,60}"   # "Chapter 3: Photosynthesis"
    r"|\d{1,2}(?:\.\d{1,2}){0,2}[.)]?\s+[A-Z][A-Za-z][^.!?]{1,60})$")                             # "3.2 The Calvin Cycle"


def headings(text: str, limit: int = 8) -> list[str]:
    """Chapter / section titles found in the text - shown as one-click 'Focus on ...' suggestions. No AI used."""
    found, seen = [], set()
    for line in text.splitlines():
        line = line.strip(" .:-–\t")
        if 4 <= len(line) <= 70 and _HEADING.match(line) and sum(c.isalpha() for c in line) >= 4:
            key = line.lower()
            if key not in seen:
                seen.add(key)
                found.append(line)
        if len(found) >= limit:
            break
    return found
