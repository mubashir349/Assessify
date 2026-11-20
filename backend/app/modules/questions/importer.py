"""Document import helpers for existing question banks.

Extraction is deliberately separate from AI review. No provider is called in this module.
The uploaded source is retained inside Flask's instance directory and is only served back
through an authenticated, institution-scoped endpoint.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from flask import current_app

from app.common.errors import ApiError
from app.modules.questions.validation import normalised_key

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".csv", ".xlsx", ".xls"}
MAX_IMPORT_QUESTIONS = 100
MAX_TEXT_CHARS = 500_000

FIELD_SYNONYMS = {
    "text": ("question", "question text", "question statement", "statement", "question title", "problem"),
    "options": ("options", "choices", "answer choices", "answers options", "mcq options"),
    "option_a": ("a", "option a", "choice a", "answer a", "option 1", "choice 1", "answer 1"),
    "option_b": ("b", "option b", "choice b", "answer b", "option 2", "choice 2", "answer 2"),
    "option_c": ("c", "option c", "choice c", "answer c", "option 3", "choice 3", "answer 3"),
    "option_d": ("d", "option d", "choice d", "answer d", "option 4", "choice 4", "answer 4"),
    "option_e": ("e", "option e", "choice e", "answer e", "option 5", "choice 5", "answer 5"),
    "option_f": ("f", "option f", "choice f", "answer f", "option 6", "choice 6", "answer 6"),
    "correct_answer": ("correct answer", "correct option", "correct index", "answer key", "key", "correct", "right answer"),
    "marks": ("marks", "mark", "weightage", "points", "score"),
    "explanation": ("explanation", "rationale", "solution", "answer explanation"),
    "topic": ("topic", "category", "chapter", "unit", "tag"),
    "difficulty": ("difficulty", "level of difficulty"),
    "question_type": ("question type", "type", "format"),
}


def _clean_filename(name: str) -> str:
    name = (name or "question-bank").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.() -]+", "_", name, flags=re.UNICODE).strip(" .")
    return (name or "question-bank")[:180]


def _normal_header(value) -> str:
    value = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _detect_mapping(headers: list[str]) -> dict:
    norm = [_normal_header(h) for h in headers]
    mapping = {}
    for field, aliases in FIELD_SYNONYMS.items():
        aliases_norm = {_normal_header(x) for x in aliases}
        match = next((headers[i] for i, h in enumerate(norm) if h in aliases_norm), None)
        if match is None and field == "text":
            match = next((headers[i] for i, h in enumerate(norm) if "question" in h or h.endswith("statement")), None)
        if match is None and field == "correct_answer":
            match = next((headers[i] for i, h in enumerate(norm) if "answer" in h or "correct" in h or h == "key"), None)
        if match:
            mapping[field] = match
    return mapping


def _read_csv(data: bytes) -> tuple[list[str], list[dict]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ApiError("INVALID_FILE_ENCODING", "The CSV encoding could not be read. Save it as UTF-8 CSV and try again.", 422)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for row_index, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if row_index > MAX_IMPORT_QUESTIONS:
            break
        rows.append(row)
    if len(rows) < 2:
        raise ApiError("EMPTY_QUESTION_FILE", "The file needs a header row and at least one data row.", 422)
    headers = [str(c or "").strip() for c in rows[0]]
    if not any(headers):
        raise ApiError("MISSING_HEADERS", "The first row must contain column names.", 422)
    dict_rows = []
    for raw in rows[1:]:
        if not any(str(c or "").strip() for c in raw):
            continue
        dict_rows.append({headers[i] or f"Column {i + 1}": raw[i] if i < len(raw) else "" for i in range(len(headers))})
    return headers, dict_rows


def _read_xlsx(data: bytes) -> tuple[list[str], list[dict]]:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for row_index, row in enumerate(ws.iter_rows(values_only=True)):
            if row_index > MAX_IMPORT_QUESTIONS:
                break
            rows.append(row)
        wb.close()
    except Exception as exc:  # noqa: BLE001
        raise ApiError("INVALID_XLSX", "This Excel workbook is damaged or could not be read.", 422) from exc
    if len(rows) < 2:
        raise ApiError("EMPTY_QUESTION_FILE", "The workbook needs a header row and at least one data row.", 422)
    headers = [str(v or "").strip() for v in rows[0]]
    if not any(headers):
        raise ApiError("MISSING_HEADERS", "The first row must contain column names.", 422)
    dict_rows = []
    for raw in rows[1:]:
        if not any(v not in (None, "") for v in raw):
            continue
        dict_rows.append({headers[i] or f"Column {i + 1}": ("" if i >= len(raw) or raw[i] is None else str(raw[i]).strip())
                          for i in range(len(headers))})
    return headers, dict_rows


def _read_xls(data: bytes) -> tuple[list[str], list[dict]]:
    try:
        import xlrd
    except ImportError as exc:
        raise ApiError("XLS_READER_MISSING", "Legacy .xls files need xlrd. Run 'python -m pip install xlrd' in backend/ and retry, or save the workbook as .xlsx.", 503) from exc
    try:
        book = xlrd.open_workbook(file_contents=data, on_demand=True)
        sheet = book.sheet_by_index(0)
        headers = [str(v or "").strip() for v in sheet.row_values(0)]
        rows = []
        for r in range(1, min(sheet.nrows, MAX_IMPORT_QUESTIONS + 2)):
            values = sheet.row_values(r)
            if not any(v not in (None, "") for v in values):
                continue
            rows.append({headers[i] or f"Column {i + 1}": ("" if i >= len(values) else str(values[i]).strip())
                         for i in range(len(headers))})
        book.release_resources()
    except Exception as exc:  # noqa: BLE001
        raise ApiError("INVALID_XLS", "This legacy Excel workbook is damaged or could not be read.", 422) from exc
    if not headers or not rows:
        raise ApiError("EMPTY_QUESTION_FILE", "The workbook needs a header row and at least one data row.", 422)
    return headers, rows


def _docx_contents(data: bytes) -> tuple[list[str] | None, list[dict] | None, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise ValueError("not a Word document")
            info_total = sum(i.file_size for i in zf.infolist())
            if info_total > 40 * 1024 * 1024 or len(names) > 5000:
                raise ValueError("archive exceeds safe limits")
            root = ET.fromstring(zf.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001
        raise ApiError("INVALID_DOCX", "This Word document is damaged or could not be read.", 422) from exc
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for p in root.findall(".//w:p", ns):
        val = "".join(t.text or "" for t in p.findall(".//w:t", ns)).strip()
        if val:
            paragraphs.append(val)
    table_rows = []
    for tr in root.findall(".//w:tbl/w:tr", ns):
        cells = []
        for tc in tr.findall("./w:tc", ns):
            cells.append(" ".join("".join(t.text or "" for t in p.findall(".//w:t", ns)) for p in tc.findall(".//w:p", ns)).strip())
        if any(cells):
            table_rows.append(cells)
    if table_rows and len(table_rows) >= 2:
        headers = table_rows[0]
        if _detect_mapping(headers).get("text"):
            rows = [{headers[i] or f"Column {i + 1}": (r[i] if i < len(r) else "") for i in range(len(headers))}
                    for r in table_rows[1:]]
            return headers, rows, "\n".join(paragraphs)
    return None, None, "\n".join(paragraphs)


def _read_doc(data: bytes, filename: str) -> str:
    antiword = shutil.which("antiword")
    if not antiword:
        raise ApiError("DOC_READER_MISSING", "Legacy .doc files need Antiword installed. Save the document as .docx, or install Antiword and retry.", 415)
    suffix = ".doc"
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            path = tmp.name
        proc = subprocess.run([antiword, path], capture_output=True, timeout=30, check=False)
        if proc.returncode != 0:
            raise ValueError("antiword failed")
        return proc.stdout.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise ApiError("INVALID_DOC", "The legacy Word document could not be converted to text.", 422) from exc
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _read_pdf(data: bytes) -> tuple[str, list[str]]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ApiError("PDF_ENCRYPTED", "This PDF is password-protected. Remove the password and upload it again.", 422)
        if not reader.pages:
            raise ApiError("EMPTY_PDF", "The PDF has no pages.", 422)
        page_limit = min(300, int(current_app.config.get("PDF_MAX_PAGES", 300)))
        pages = list(reader.pages[:page_limit])
        text = "\n\n".join((page.extract_text() or "") for page in pages)
        page_warning = [f"Only the first {page_limit} pages were extracted from this {len(reader.pages)}-page PDF."] if len(reader.pages) > page_limit else []
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ApiError("INVALID_PDF", "This PDF is damaged or could not be read.", 422) from exc
    warnings = page_warning
    if len(re.sub(r"\W", "", text)) < 80:
        # Optional OCR: the OCR package and the local Tesseract executable are both required.
        try:
            import fitz
            import pytesseract
            from PIL import Image
            tesseract_cmd = current_app.config.get("TESSERACT_CMD") or os.getenv("TESSERACT_CMD")
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            ocr_pages = []
            with fitz.open(stream=data, filetype="pdf") as doc:
                for page in doc[:60]:
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr_pages.append(pytesseract.image_to_string(img))
            ocr_text = "\n\n".join(ocr_pages).strip()
            if len(re.sub(r"\W", "", ocr_text)) > len(re.sub(r"\W", "", text)):
                text = ocr_text
                warnings.append("OCR was used. Check extracted wording and answers against the original scan.")
        except Exception:  # noqa: BLE001
            warnings.append("This PDF appears to be scanned or image-based. OCR is not available on this computer; the text preview may be incomplete. Install Tesseract OCR and the optional PyMuPDF/pytesseract packages, or use a searchable PDF.")
    if not text.strip():
        warnings.append("No readable text was extracted. You can still add questions manually in the preview.")
    return text[:MAX_TEXT_CHARS], warnings


def _answer_index(raw, options: list[str]) -> int | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.isdigit():
        n = int(value)
        if 1 <= n <= len(options):
            return n - 1
        if 0 <= n < len(options):
            return n
    value = re.sub(r"^\s*option\s+", "", value, flags=re.I)
    match = re.match(r"^\(?([A-F])\)?[.)\s:-]*", value, re.I)
    if match:
        idx = ord(match.group(1).upper()) - 65
        if idx < len(options):
            return idx
    value_norm = re.sub(r"^[A-F][.)\s:-]*", "", value, flags=re.I).strip().lower()
    return next((i for i, opt in enumerate(options) if opt.strip().lower() == value_norm), None)


def _split_options(raw) -> list[str]:
    value = str(raw or "").strip()
    if not value:
        return []
    pieces = re.split(r"\s*(?:\||\n|\r\n|;\s*(?=[A-F][.)]))\s*", value)
    if len(pieces) == 1:
        # Also accept inline A) B) C) D) options.
        parts = re.split(r"(?=(?:^|\s)[A-F][.)]\s+)", value)
        if len(parts) > 1:
            pieces = parts
    clean = []
    for item in pieces:
        item = re.sub(r"^\s*\(?[A-F][.)]\s*", "", item.strip(), flags=re.I)
        if item:
            clean.append(item)
    return clean


def _cell(row: dict, mapping: dict, field: str) -> str:
    key = mapping.get(field)
    return str(row.get(key, "") if key else "").strip()


def _row_to_question(row: dict, mapping: dict, index: int) -> dict:
    text = _cell(row, mapping, "text")
    options = []
    for key in ("option_a", "option_b", "option_c", "option_d", "option_e", "option_f"):
        v = _cell(row, mapping, key)
        if v:
            options.append(v)
    if not options:
        options = _split_options(_cell(row, mapping, "options"))
    qtype_raw = _cell(row, mapping, "question_type").lower()
    qtype = "true_false" if any(x in qtype_raw for x in ("true", "false", "tf")) else "mcq"
    if qtype == "true_false" or (len(options) == 2 and {x.strip().lower() for x in options} == {"true", "false"}):
        qtype = "true_false"
        options = ["True", "False"]
    answer = _cell(row, mapping, "correct_answer")
    if qtype == "true_false" and answer.lower() in ("true", "false"):
        correct = 0 if answer.lower() == "true" else 1
    else:
        correct = _answer_index(answer, options)
    marks_raw = _cell(row, mapping, "marks")
    try:
        marks = max(1, min(100, int(float(marks_raw)))) if marks_raw else 1
    except (ValueError, TypeError):
        marks = 1
    difficulty = _cell(row, mapping, "difficulty").lower()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"
    topic = _cell(row, mapping, "topic")
    explanation = _cell(row, mapping, "explanation")
    warnings = []
    if not text:
        warnings.append("Question statement was not found.")
    if qtype == "mcq" and len(options) < 2:
        warnings.append("Fewer than two answer options were found.")
    if correct is None:
        warnings.append("Correct answer was not identified; select it manually.")
    if not marks_raw:
        warnings.append("Marks were not in the source; a default of 1 is shown for teacher review.")
    if len(options) > 6:
        warnings.append("More than six options were found; remove extra options before saving.")
    if len({x.lower() for x in options}) != len(options):
        warnings.append("Duplicate answer options were found.")
    return {"text": text, "options": options, "correct_index": correct, "question_type": qtype,
            "marks": marks, "difficulty": difficulty, "topic": topic, "explanation": explanation,
            "warnings": warnings, "source_row": index}


def extract_structured(headers: list[str], rows: list[dict], mapping: dict | None = None) -> dict:
    suggested = _detect_mapping(headers)
    mapping = mapping or suggested
    if not mapping.get("text"):
        return {"needs_mapping": True, "headers": headers, "suggested_mapping": suggested,
                "sample_rows": rows[:3], "questions": [], "warnings": ["Select the column that contains each question statement."]}
    questions = [_row_to_question(row, mapping, i + 2) for i, row in enumerate(rows)]
    warnings = []
    if len(questions) > MAX_IMPORT_QUESTIONS:
        questions = questions[:MAX_IMPORT_QUESTIONS]
        warnings.append(f"Only the first {MAX_IMPORT_QUESTIONS} rows were extracted because of the current question limit.")
    if not questions:
        warnings.append("No question rows were found in this file.")
    return {"needs_mapping": False, "headers": headers, "suggested_mapping": suggested, "mapping": mapping,
            "questions": questions, "warnings": warnings}


_Q_START = re.compile(r"^\s*(?:Q(?:uestion)?\s*)?(\d{1,3})\s*[.)\-:]\s*(.+)$", re.I)
_OPT = re.compile(r"^\s*(?:\(([A-F])\)|([A-F])[).:\-])\s*(.+?)\s*$", re.I)
_ANSWER = re.compile(r"^\s*(?:correct\s+)?(?:answer|ans|key)\s*[:=\-]\s*(.+)$", re.I)
_MARKS = re.compile(r"^\s*(?:marks?|weightage|points)\s*[:=\-]\s*(\d+)\s*$", re.I)
_EXPL = re.compile(r"^\s*(?:explanation|rationale|solution)\s*[:=\-]\s*(.*)$", re.I)
_TOPIC = re.compile(r"^\s*(?:topic|category|chapter)\s*[:=\-]\s*(.*)$", re.I)


def extract_unstructured(text: str) -> dict:
    lines = [line.strip() for line in (text or "").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    chunks: list[list[str]] = []
    current: list[str] = []
    has_numbered = any(_Q_START.match(line) for line in lines)
    if has_numbered:
        for line in lines:
            m = _Q_START.match(line)
            if m:
                if current:
                    chunks.append(current)
                current = [m.group(2).strip()]
            elif current:
                current.append(line)
        if current:
            chunks.append(current)
    else:
        # Try paragraphs first; question-like lines are separated from unrelated prose.
        para = re.split(r"\n\s*\n", text or "")
        chunks = [[ln.strip() for ln in block.splitlines() if ln.strip()] for block in para if block.strip()]
        # If the file is mostly line-wrapped, group each line ending in '?' with following options.
        if len(chunks) <= 1:
            chunks = []
            for line in lines:
                if line.endswith("?") and (not current or any(_OPT.match(x) for x in current)):
                    if current:
                        chunks.append(current)
                    current = [line]
                elif current:
                    current.append(line)
            if current:
                chunks.append(current)

    questions = []
    for qno, chunk in enumerate(chunks[:MAX_IMPORT_QUESTIONS], 1):
        qlines, options = [], []
        answer_raw, explanation, topic, marks = "", "", "", 1
        mode = "question"
        for line in chunk:
            m = _OPT.match(line)
            if m:
                options.append(m.group(3).strip())
                mode = "options"
                continue
            a = _ANSWER.match(line)
            if a:
                answer_raw = a.group(1).strip(); mode = "answer"; continue
            mk = _MARKS.match(line)
            if mk:
                marks = max(1, min(100, int(mk.group(1)))); continue
            ex = _EXPL.match(line)
            if ex:
                explanation = ex.group(1).strip(); mode = "explanation"; continue
            tp = _TOPIC.match(line)
            if tp:
                topic = tp.group(1).strip(); continue
            if mode == "explanation":
                explanation = (explanation + " " + line).strip()
            elif mode in ("question", "options") and not options:
                qlines.append(line)
            elif mode == "options":
                # Continuation of the most recent option if it does not look like a label.
                if options:
                    options[-1] = (options[-1] + " " + line).strip()
            elif mode == "answer":
                continue
        qtext = " ".join(qlines).strip()
        # Some documents put the first statement before the first option and then wrap it onto the next line.
        qtype = "true_false" if (re.search(r"\btrue\s*/\s*false\b", qtext, re.I) or
                                 (len(options) == 2 and {x.strip().lower() for x in options} == {"true", "false"})) else "mcq"
        if qtype == "true_false":
            options = ["True", "False"]
            correct = (0 if answer_raw.lower() == "true" else 1 if answer_raw.lower() == "false" else _answer_index(answer_raw, options))
        else:
            correct = _answer_index(answer_raw, options)
        warnings = []
        if not qtext:
            warnings.append("Question statement could not be confidently separated from surrounding text.")
        if qtype == "mcq" and len(options) < 2:
            warnings.append("Answer options could not be fully identified.")
        if correct is None:
            warnings.append("Correct answer was not identified; select it manually.")
        if not any(_MARKS.match(line) for line in chunk):
            warnings.append("Marks were not in the source; a default of 1 is shown for teacher review.")
        if len(options) > 6:
            warnings.append("More than six options were found; remove extra options before saving.")
        questions.append({"text": qtext, "options": options, "correct_index": correct, "question_type": qtype,
                          "marks": marks, "difficulty": "medium", "topic": topic, "explanation": explanation,
                          "warnings": warnings, "source_row": qno})
    all_warnings = []
    if not questions:
        all_warnings.append("No numbered question blocks were detected. Add or paste questions manually in the preview.")
    if len(chunks) > MAX_IMPORT_QUESTIONS:
        all_warnings.append(f"Only the first {MAX_IMPORT_QUESTIONS} question blocks were extracted.")
    return {"needs_mapping": False, "questions": questions, "warnings": all_warnings}


def _storage_root() -> Path:
    root = Path(current_app.instance_path) / "question_imports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _draft_dir(institution_id: int, token: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", token or ""):
        raise ApiError("IMPORT_NOT_FOUND", "Import session was not found. Upload the file again.", 404)
    root = (_storage_root() / str(institution_id) / token).resolve()
    base = (_storage_root() / str(institution_id)).resolve()
    if base not in root.parents:
        raise ApiError("IMPORT_NOT_FOUND", "Import session was not found.", 404)
    return root


def _write_manifest(folder: Path, manifest: dict) -> None:
    path = folder / "manifest.json"
    tmp = folder / "manifest.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_draft(institution_id: int, user_id: int, token: str) -> tuple[Path, dict]:
    folder = _draft_dir(institution_id, token)
    path = folder / "manifest.json"
    if not path.is_file():
        raise ApiError("IMPORT_NOT_FOUND", "Import session expired or was not found. Upload the file again.", 404)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ApiError("IMPORT_CORRUPT", "The saved import preview could not be read. Upload the file again.", 500) from exc
    if manifest.get("institution_id") != institution_id or manifest.get("user_id") != user_id:
        raise ApiError("IMPORT_NOT_FOUND", "Import session was not found.", 404)
    created = manifest.get("created_at")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(created)).total_seconds()
    except Exception:
        age = 0
    if age > 24 * 60 * 60 and manifest.get("saved_attempt_id") is None:
        raise ApiError("IMPORT_EXPIRED", "This import preview expired after 24 hours. Upload the file again.", 410)
    return folder, manifest


def create_import(user, file_storage) -> dict:
    if file_storage is None or not file_storage.filename:
        raise ApiError("VALIDATION_ERROR", "Choose a question-bank file to upload.", 422, {"file": "Choose a file."})
    filename = _clean_filename(file_storage.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError("UNSUPPORTED_FILE_TYPE", "Supported formats are PDF, DOCX, DOC, CSV, XLSX and XLS.", 415)
    data = file_storage.read(int(current_app.config.get("MAX_IMPORT_UPLOAD_MB", 25)) * 1024 * 1024 + 1)
    if not data:
        raise ApiError("EMPTY_FILE", "The uploaded file is empty.", 422)
    max_bytes = int(current_app.config.get("MAX_IMPORT_UPLOAD_MB", 25)) * 1024 * 1024
    if len(data) > max_bytes:
        raise ApiError("FILE_TOO_LARGE", f"Question-bank imports are limited to {max_bytes // (1024 * 1024)} MB.", 413)

    headers, rows, text, warnings = None, None, "", []
    if ext == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise ApiError("INVALID_PDF", "The file extension says PDF but the file is not a valid PDF.", 422)
        text, warnings = _read_pdf(data)
    elif ext == ".csv":
        try:
            headers, rows = _read_csv(data)
        except ApiError:
            raise
    elif ext == ".xlsx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ApiError("INVALID_XLSX", "The uploaded file is not a valid Excel workbook.", 422)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "xl/workbook.xml" not in zf.namelist() or sum(i.file_size for i in zf.infolist()) > 40 * 1024 * 1024:
                raise ApiError("INVALID_XLSX", "The Excel workbook is invalid or exceeds safe processing limits.", 422)
        headers, rows = _read_xlsx(data)
    elif ext == ".xls":
        if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ApiError("INVALID_XLS", "The file extension says XLS but the file is not a valid legacy Excel workbook.", 422)
        headers, rows = _read_xls(data)
    elif ext == ".docx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ApiError("INVALID_DOCX", "The uploaded file is not a valid Word document.", 422)
        headers, rows, text = _docx_contents(data)
    elif ext == ".doc":
        if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ApiError("INVALID_DOC", "The file extension says DOC but the file is not a valid legacy Word document.", 422)
        text = _read_doc(data, filename)

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        warnings.append(f"Only the first {MAX_TEXT_CHARS:,} characters of the document were extracted.")

    if headers is not None:
        suggested = _detect_mapping(headers)
        parsed = {"needs_mapping": True, "headers": headers, "suggested_mapping": suggested,
                  "sample_rows": rows[:3], "mapping": {}, "questions": [],
                  "warnings": warnings + ["Confirm the column mapping before extraction. Auto-detected columns are suggestions only."]}
    else:
        parsed = extract_unstructured(text)
        parsed["warnings"] = warnings + parsed.get("warnings", [])
    question_limit = min(MAX_IMPORT_QUESTIONS, int(current_app.config.get("MAX_QUESTIONS_PER_ATTEMPT", MAX_IMPORT_QUESTIONS)))
    if len(parsed.get("questions", [])) > question_limit:
        parsed["questions"] = parsed["questions"][:question_limit]
        parsed.setdefault("warnings", []).append(f"Only the first {question_limit} questions were extracted to match this institution's question-bank limit.")

    token = uuid.uuid4().hex
    folder = _draft_dir(user.institution_id, token)
    folder.mkdir(parents=True, exist_ok=False)
    source_name = "source" + ext
    (folder / source_name).write_bytes(data)
    manifest = {"token": token, "institution_id": user.institution_id, "user_id": user.id,
                "filename": filename, "source_file": source_name, "sha256": hashlib.sha256(data).hexdigest(),
                "source_text": text[:MAX_TEXT_CHARS], "created_at": datetime.now(timezone.utc).isoformat(),
                "saved_attempt_id": None, **parsed}
    _write_manifest(folder, manifest)
    return _public_manifest(manifest)


def _public_manifest(manifest: dict) -> dict:
    return {"token": manifest["token"], "filename": manifest["filename"], "sha256": manifest["sha256"],
            "created_at": manifest["created_at"], "needs_mapping": bool(manifest.get("needs_mapping")),
            "headers": manifest.get("headers", []), "suggested_mapping": manifest.get("suggested_mapping", {}),
            "sample_rows": manifest.get("sample_rows", []), "mapping": manifest.get("mapping", {}),
            "questions": manifest.get("questions", []), "warnings": manifest.get("warnings", []),
            "source_url": f"/api/v1/questions/imports/{manifest['token']}/source",
            "saved_attempt_id": manifest.get("saved_attempt_id")}


def apply_mapping(institution_id: int, user_id: int, token: str, mapping: dict) -> dict:
    folder, manifest = load_draft(institution_id, user_id, token)
    headers = manifest.get("headers") or []
    # Reconstruct every row from the protected original; the preview only exposes a small sample.
    source = (folder / manifest["source_file"]).read_bytes()
    ext = Path(manifest["filename"]).suffix.lower()
    if ext == ".csv": headers, rows = _read_csv(source)
    elif ext == ".xlsx": headers, rows = _read_xlsx(source)
    elif ext == ".xls": headers, rows = _read_xls(source)
    elif ext == ".docx":
        headers, rows, _ = _docx_contents(source)
        if headers is None or rows is None:
            raise ApiError("IMPORT_INVALID_STATE", "This Word document does not contain a structured table to map.", 409)
    else: raise ApiError("IMPORT_INVALID_STATE", "This import does not need column mapping.", 409)
    if not isinstance(mapping, dict):
        raise ApiError("VALIDATION_ERROR", "Choose a column mapping.", 422)
    valid_fields = set(FIELD_SYNONYMS)
    clean = {k: str(v) for k, v in mapping.items() if k in valid_fields and v}
    if clean.get("text") not in headers:
        raise ApiError("VALIDATION_ERROR", "Select the column containing the question statement.", 422, {"text": "Question column is required."})
    parsed = extract_structured(headers, rows, clean)
    if parsed.get("needs_mapping"):
        raise ApiError("VALIDATION_ERROR", "The question column is required.", 422)
    question_limit = min(MAX_IMPORT_QUESTIONS, int(current_app.config.get("MAX_QUESTIONS_PER_ATTEMPT", MAX_IMPORT_QUESTIONS)))
    if len(parsed.get("questions", [])) > question_limit:
        parsed["questions"] = parsed["questions"][:question_limit]
        parsed.setdefault("warnings", []).append(f"Only the first {question_limit} questions were extracted to match this institution's question-bank limit.")
    manifest.update(parsed)
    manifest["headers"] = headers
    _write_manifest(folder, manifest)
    return _public_manifest(manifest)


def get_source(institution_id: int, user_id: int, token: str) -> tuple[Path, str]:
    folder, manifest = load_draft(institution_id, user_id, token)
    source = folder / manifest["source_file"]
    if not source.is_file():
        raise ApiError("SOURCE_NOT_FOUND", "The original uploaded file is no longer available.", 404)
    return source, manifest["filename"]


def update_recommendations(institution_id: int, user_id: int, token: str, recommendations: list) -> dict:
    folder, manifest = load_draft(institution_id, user_id, token)
    manifest["recommendations"] = recommendations
    _write_manifest(folder, manifest)
    return _public_manifest(manifest)


def get_recommendations(institution_id: int, user_id: int, token: str) -> list:
    _, manifest = load_draft(institution_id, user_id, token)
    return manifest.get("recommendations", [])


def save_import_metadata(institution_id: int, user_id: int, token: str, attempt_id: int) -> None:
    folder, manifest = load_draft(institution_id, user_id, token)
    manifest["saved_attempt_id"] = attempt_id
    _write_manifest(folder, manifest)


def annotate_duplicates(institution_id: int, questions: list, existing_texts: set[str]) -> list:
    seen = set(existing_texts)
    for q in questions:
        key = normalised_key(q.get("text", ""))
        duplicate = bool(key and key in seen)
        q["possible_duplicate"] = duplicate
        if duplicate:
            q.setdefault("warnings", []).append("This question closely matches a question already in the Question Bank. It will be skipped when saving to prevent duplicates.")
        elif key:
            seen.add(key)
    return questions
