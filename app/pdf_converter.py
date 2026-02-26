"""
DOCX → PDF conversion with multiple backend support.

Backends (configured via PDF_BACKEND env var):
  - "libreoffice"  : Uses LibreOffice headless CLI (recommended for Linux servers)
  - "gotenberg"    : Uses Gotenberg API (Docker container, good for containerised deploys)
  - "docx2pdf"     : Uses docx2pdf library (requires MS Word — Windows/macOS only)
"""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import requests

from app.config import PDF_BACKEND, GOTENBERG_URL, OUTPUT_DIR


class PDFConversionError(Exception):
    pass


# ── LibreOffice headless ──────────────────────────────────────────────

def _convert_libreoffice(docx_path: Path) -> Path:
    lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
    if lo_bin is None:
        raise PDFConversionError(
            "LibreOffice is not installed or not on PATH. "
            "Install it with: sudo apt install libreoffice-writer"
        )

    result = subprocess.run(
        [
            lo_bin,
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(OUTPUT_DIR),
            str(docx_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise PDFConversionError(
            f"LibreOffice conversion failed:\n{result.stderr}"
        )

    pdf_path = OUTPUT_DIR / f"{docx_path.stem}.pdf"

    # LibreOffice sometimes outputs .htm instead of .pdf — detect and clean up
    htm_path = OUTPUT_DIR / f"{docx_path.stem}.htm"
    if not pdf_path.exists() and htm_path.exists():
        htm_path.unlink()
        raise PDFConversionError(
            "LibreOffice produced HTML instead of PDF. "
            "The .docx file is still available for download."
        )

    if not pdf_path.exists():
        raise PDFConversionError(
            "LibreOffice ran but the PDF was not found at the expected path."
        )
    return pdf_path


# ── Gotenberg (Docker API) ───────────────────────────────────────────

def _convert_gotenberg(docx_path: Path) -> Path:
    url = f"{GOTENBERG_URL}/forms/libreoffice/convert"
    with open(docx_path, "rb") as f:
        resp = requests.post(
            url,
            files={"files": (docx_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            timeout=120,
        )

    if resp.status_code != 200:
        raise PDFConversionError(
            f"Gotenberg returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    pdf_path = OUTPUT_DIR / f"{docx_path.stem}.pdf"
    pdf_path.write_bytes(resp.content)
    return pdf_path


# ── docx2pdf (Windows/macOS with MS Word) ────────────────────────────

def _convert_docx2pdf(docx_path: Path) -> Path:
    try:
        from docx2pdf import convert  # type: ignore
    except ImportError:
        raise PDFConversionError(
            "docx2pdf is not installed. Run: pip install docx2pdf"
        )

    # docx2pdf uses COM automation on Windows, which requires CoInitialize
    # in threads other than the main thread (e.g. Streamlit's script runner).
    import sys
    _co_initialized = False
    if sys.platform == "win32":
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _co_initialized = True
        except Exception:
            pass

    pdf_path = OUTPUT_DIR / f"{docx_path.stem}.pdf"
    try:
        convert(str(docx_path), str(pdf_path))
    finally:
        if _co_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    if not pdf_path.exists():
        raise PDFConversionError("docx2pdf ran but the PDF was not created.")
    return pdf_path


# ── Public interface ─────────────────────────────────────────────────

_BACKENDS = {
    "libreoffice": _convert_libreoffice,
    "gotenberg": _convert_gotenberg,
    "docx2pdf": _convert_docx2pdf,
}


def convert_to_pdf(docx_path: Path) -> Path:
    """
    Convert a .docx file to .pdf using the configured backend.
    Returns the Path to the generated PDF.
    """
    backend = PDF_BACKEND.lower()
    converter = _BACKENDS.get(backend)
    if converter is None:
        raise PDFConversionError(
            f"Unknown PDF_BACKEND '{backend}'. "
            f"Choose from: {', '.join(_BACKENDS)}"
        )
    return converter(docx_path)
