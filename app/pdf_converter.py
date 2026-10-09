"""
DOCX → PDF conversion with multiple backend support.

LIVE, NOT DORMANT. This module renders the MSAPO form that is attached to every
purchase-order submission, reached through document_generator.build_msapo_pdf.
It sat unused between 2026-08-08 and 2026-08-12, when contract administration
reversed the attachment policy back to the full MSAPO form, and the README
described it as a "dormant historical compatibility module" for five days after
that. Do not remove it on the strength of an old comment.

Backends (configured via PDF_BACKEND env var):
  - "libreoffice"  : Uses LibreOffice headless CLI (recommended for Linux servers)
  - "gotenberg"    : Uses Gotenberg API (Docker container, good for containerised deploys)
  - "docx2pdf"     : Uses docx2pdf library (requires MS Word — Windows/macOS only)

Only "libreoffice" is exercised in production or in CI. The other two are
configuration-reachable but untested here: Gotenberg needs a sidecar container
and docx2pdf needs MS Word, so neither runs on Render or on the GitHub runner.
Treat a change to them as unverified regardless of a green suite.

Every backend returns a PATH under config.OUTPUT_DIR rather than bytes, and
NONE of them deletes that file. build_msapo_pdf owns the cleanup and unlinks
both intermediates in a finally block; document_generator._cleanup_old_outputs
sweeps anything a crash left behind, once per process. A new caller that reads
the path and forgets to unlink it will leak a PDF per generation onto the Render
persistent disk, where the symptom is a full disk weeks later rather than an
error here.
"""

from __future__ import annotations

import subprocess
import logging
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import requests

from app.config import PDF_BACKEND, GOTENBERG_URL, OUTPUT_DIR


class PDFConversionError(Exception):
    pass


class PDFConversionTimeout(PDFConversionError):
    pass


# ── LibreOffice headless ──────────────────────────────────────────────

def _convert_libreoffice(docx_path: Path) -> Path:
    # All Writer callers, including purchase orders, share the same slot as
    # monthly reports and Calc. Multiple 300+ MB office processes cannot fit
    # inside the testing service's 512 MB instance.
    from app.monthly_report_render_jobs import conversion_slot
    with conversion_slot(wait_seconds=130):
        return _convert_libreoffice_locked(docx_path)


def _convert_libreoffice_locked(docx_path: Path) -> Path:
    lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
    if lo_bin is None:
        raise PDFConversionError(
            "LibreOffice is not installed or not on PATH. "
            "Install it with: sudo apt install libreoffice-writer"
        )

    from app.office_limits import prepare_profile
    from app.office_process import run_office
    # Private output prevents a failed conversion from returning another job's
    # PDF. Keep it on the output filesystem for atomic, no-overwrite publication.
    with tempfile.TemporaryDirectory(prefix=".office-", dir=OUTPUT_DIR) as job_dir:
        job = Path(job_dir)
        profile_uri = prepare_profile(job / 'profile')
        try:
            result = run_office([
                lo_bin, "--headless", f"-env:UserInstallation={profile_uri}",
                "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(job),
                str(docx_path.resolve()),
            ], timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise PDFConversionTimeout(
                "PDF conversion took too long. The conversion was stopped."
            ) from exc

        produced = job / f"{docx_path.stem}.pdf"
        if result.returncode or not produced.is_file():
            logging.getLogger(__name__).warning(
                "Office conversion failed: exit=%s stdout=%s stderr=%s",
                result.returncode, result.stdout, result.stderr)
            raise PDFConversionError(
                "LibreOffice could not read or render this document. "
                "Check the starting report and recently added pages before trying again."
            )
        with produced.open('rb') as stream:
            valid = stream.read(5) == b'%PDF-'
        if not valid or produced.is_symlink():
            raise PDFConversionError("LibreOffice returned an invalid PDF file.")
        pdf_path = OUTPUT_DIR / f"{docx_path.stem}-{uuid4().hex}.pdf"
        try:
            # A hard link publishes only a complete file and refuses collisions.
            # Temporary-directory cleanup cannot remove the returned link.
            os.link(produced, pdf_path)
        except FileExistsError as exc:
            raise PDFConversionError(
                "PDF publication could not reserve a new output file. Try again."
            ) from exc
        return pdf_path


# ── Gotenberg (Docker API) ───────────────────────────────────────────

def _convert_gotenberg(docx_path: Path) -> Path:
    """Convert via a Gotenberg sidecar. NOT exercised by CI or production.

    Unlike the LibreOffice path, the response body is written out without being
    checked for a "%PDF-" magic number, so a 200 carrying an error page would be
    saved as a .pdf. build_msapo_pdf validates the magic number before returning,
    which is what stops that reaching the operator -- but the resulting message
    blames the DOCX renderer rather than Gotenberg. Add the check here if this
    backend is ever actually deployed.
    """
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

    The returned file is NOT the caller's to forget: see the module docstring.
    build_msapo_pdf unlinks it in a finally block.

    Raises PDFConversionError for an unknown PDF_BACKEND rather than silently
    falling back to LibreOffice. A typo in the environment variable must fail
    loudly -- a silent fallback would make the deployment work while reporting a
    configuration that is not what is running.
    """
    backend = PDF_BACKEND.lower()
    converter = _BACKENDS.get(backend)
    if converter is None:
        raise PDFConversionError(
            f"Unknown PDF_BACKEND '{backend}'. "
            f"Choose from: {', '.join(_BACKENDS)}"
        )
    return converter(docx_path)
