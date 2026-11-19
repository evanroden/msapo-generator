"""Server-side quote and receipt upload checks with actionable operator guidance.

Streamlit's file type filter displays MIME types before Python can explain the
problem. Both uploaders allow selection first and validate extension and bytes
here, before extraction, receipt mirroring or any model call.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from app.smartsheet import MAX_ATTACHMENT_BYTES, preflight_attachments

QUOTE_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp",
    ".tif", ".tiff", ".bmp", ".heic", ".heif", ".hif",
})
RECEIPT_EXTENSIONS = QUOTE_EXTENSIONS - {".docx", ".txt"}
QUOTE_NEXT_STEP = (
    "Upload the quote as a PDF, Word document (.docx), photo or .txt file, "
    "or paste its text."
)
RECEIPT_NEXT_STEP = (
    "Upload the receipt as a PDF or photo (JPG, PNG, WebP, TIFF, BMP or HEIC)."
)


def _docx_container_ok(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            return (
                "word/document.xml" in names
                and "[Content_Types].xml" in names
                and not any(entry.flag_bits & 1 for entry in archive.infolist())
            )
    except (BadZipFile, OSError, ValueError):
        return False


def _matches_header(suffix: str, data: bytes) -> bool:
    if not data:
        return False
    if suffix == ".pdf":
        return data[:1024].lstrip().startswith(b"%PDF-")
    if suffix == ".docx":
        return _docx_container_ok(data)
    if suffix == ".txt":
        # Preserve existing decoding for legacy single-byte text documents.
        # Binary data with a misleading .txt name must not reach the analyzer.
        return b"\x00" not in data[:4096]
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if suffix in {".tif", ".tiff"}:
        return data.startswith((b"II*\x00", b"MM\x00*"))
    if suffix == ".bmp":
        return data.startswith(b"BM")
    if suffix in {".heic", ".heif", ".hif"}:
        return data[4:8] == b"ftyp" and data[8:12] in {
            b"heic", b"heix", b"hevc", b"hevx", b"heif",
            b"mif1", b"msf1", b"heim", b"heis",
        }
    return False


def _unsupported_message(suffix: str, *, quote: bool) -> str:
    next_step = QUOTE_NEXT_STEP if quote else RECEIPT_NEXT_STEP
    if suffix in {".xls", ".xlsx", ".xlsm", ".xlsb"}:
        return "Excel files can't be read here. " + next_step
    if suffix == ".doc":
        return "Older Word .doc files can't be read here. " + next_step
    if suffix == ".docx":
        return "Word documents cannot be used as receipts. " + next_step
    return "This file type can't be read here. " + next_step


def quote_upload_problem(filename: str, data: bytes) -> str | None:
    """Return an actionable issue; never trust a browser-supplied MIME type."""
    suffix = Path(filename).suffix.casefold()
    if len(data) > MAX_ATTACHMENT_BYTES:
        # Preserve the same 30 MB wording used by the submission preflight.
        return preflight_attachments(((filename, data),))[0] + " " + QUOTE_NEXT_STEP
    if suffix not in QUOTE_EXTENSIONS:
        return _unsupported_message(suffix, quote=True)
    if not _matches_header(suffix, data):
        if suffix == ".docx":
            return "This Word document is unreadable or protected. " + QUOTE_NEXT_STEP
        return "This quote file is empty or does not match its extension. " + QUOTE_NEXT_STEP
    return None


def receipt_upload_problem(filename: str, data: bytes) -> str | None:
    """Validate a receipt before it becomes part of the byte mirror."""
    suffix = Path(filename).suffix.casefold()
    if suffix not in RECEIPT_EXTENSIONS:
        return _unsupported_message(suffix, quote=False)
    if not _matches_header(suffix, data):
        return "This receipt file is empty or does not match its extension. " + RECEIPT_NEXT_STEP
    return None
