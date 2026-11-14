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
from typing import Mapping, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from app.adapter_loader import AdapterConfigurationError, load_adapter
from app.config import PDF_BACKEND, GOTENBERG_URL, OUTPUT_DIR


class PDFConversionError(Exception):
    pass


class PDFConversionTimeout(PDFConversionError):
    pass


class PDFConverter(Protocol):
    name: str

    def convert(self, docx_path: Path, output_dir: Path) -> Path: ...

    def diagnostic(self) -> Mapping[str, object]: ...


def _validate_converted_pdf(path: Path) -> Path:
    if not path.is_file() or path.is_symlink():
        raise PDFConversionError("The converter did not return a valid PDF file.")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise PDFConversionError("The converter did not return a valid PDF file.")
    return path


class LibreOfficeConverter:
    """Portable CLI implementation for adapter contracts.

    The legacy default conversion below remains authoritative for production
    because it also holds the shared office-process budget and image-preservation
    rules used by monthly reports.
    """
    name = "libreoffice"

    def diagnostic(self) -> Mapping[str, object]:
        return {"name": self.name, "configured": bool(shutil.which("libreoffice") or shutil.which("soffice"))}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        exe = shutil.which("libreoffice") or shutil.which("soffice")
        if not exe:
            raise PDFConversionError("LibreOffice is not installed.")
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".epc-convert-", dir=output_dir) as tmp:
            staging = Path(tmp)
            profile = staging / "profile"
            target = staging / "out"
            target.mkdir()
            try:
                result = subprocess.run(
                    [
                        exe, "--headless", f"-env:UserInstallation={profile.as_uri()}",
                        "--convert-to", "pdf", "--outdir", str(target),
                        str(docx_path.resolve()),
                    ],
                    capture_output=True, text=True, timeout=120,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise PDFConversionTimeout("Portable LibreOffice conversion timed out.") from exc
            expected = target / f"{docx_path.stem}.pdf"
            if result.returncode or not expected.is_file():
                raise PDFConversionError("LibreOffice finished without the expected PDF.")
            _validate_converted_pdf(expected)
            published = output_dir / f"{docx_path.stem}-{uuid4().hex}.pdf"
            try:
                os.link(expected, published)
            except OSError as exc:
                raise PDFConversionError("Could not publish converted PDF safely.") from exc
            return _validate_converted_pdf(published)


class GotenbergConverter:
    name = "gotenberg"

    def __init__(self, *, base_url: str, timeout: int = 120) -> None:
        split = urlsplit(base_url)
        if split.scheme not in ("http", "https") or not split.hostname:
            raise PDFConversionError("Gotenberg requires an absolute HTTP(S) URL.")
        if split.scheme != "https" and split.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise PDFConversionError("Remote Gotenberg URLs must use HTTPS.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def diagnostic(self) -> Mapping[str, object]:
        return {"name": self.name, "configured": True, "endpoint": self.base_url}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        with docx_path.open("rb") as source:
            response = requests.post(
                f"{self.base_url}/forms/libreoffice/convert",
                files={"files": (
                    docx_path.name, source,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )},
                timeout=self.timeout,
            )
        if response.status_code != 200:
            raise PDFConversionError(f"Gotenberg returned HTTP {response.status_code}.")
        data = response.content
        if not isinstance(data, bytes) or not data.startswith(b"%PDF-"):
            raise PDFConversionError("Gotenberg did not return a valid PDF.")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{docx_path.stem}-{uuid4().hex}.pdf"
        path.write_bytes(data)
        return _validate_converted_pdf(path)


class Docx2PdfConverter:
    name = "docx2pdf"

    def diagnostic(self) -> Mapping[str, object]:
        try:
            import docx2pdf  # noqa: F401
        except ImportError:
            return {"name": self.name, "configured": False}
        return {"name": self.name, "configured": True}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        try:
            import docx2pdf
        except ImportError as exc:
            raise PDFConversionError("docx2pdf is not installed.") from exc
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{docx_path.stem}-{uuid4().hex}.pdf"
        docx2pdf.convert(str(docx_path), str(target))
        return _validate_converted_pdf(target)


class DisabledConverter:
    name = "none"

    def diagnostic(self) -> Mapping[str, object]:
        return {"name": self.name, "configured": True}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        raise PDFConversionError("PDF conversion is disabled; DOCX output remains available.")


def get_pdf_converter(env: Mapping[str, str] | None = None) -> PDFConverter:
    source = os.environ if env is None else env
    name = (source.get("EPC_PDF_CONVERTER") or source.get("PDF_BACKEND") or "libreoffice").strip().lower()
    if name == "libreoffice":
        return LibreOfficeConverter()
    if name == "gotenberg":
        return GotenbergConverter(base_url=source.get("EPC_GOTENBERG_URL") or source.get("GOTENBERG_URL") or "http://localhost:3000")
    if name == "docx2pdf":
        return Docx2PdfConverter()
    if name in ("none", "disabled"):
        return DisabledConverter()
    if name == "custom":
        return load_adapter(
            source.get("EPC_PDF_CONVERTER_ADAPTER", ""),
            kind="PDF converter",
            required_methods=("convert", "diagnostic"),
            env=source,
        )
    raise AdapterConfigurationError(f"Unknown EPC_PDF_CONVERTER {name!r}.")


# ── LibreOffice headless ──────────────────────────────────────────────

def _convert_libreoffice(docx_path: Path, *, lossless_images: bool = False) -> Path:
    # All Writer callers, including purchase orders, share the same slot as
    # monthly reports and Calc. Multiple 300+ MB office processes cannot fit
    # inside the testing service's 512 MB instance.
    from app.monthly_report_render_jobs import conversion_slot
    with conversion_slot(wait_seconds=130):
        return _convert_libreoffice_locked(docx_path, lossless_images=lossless_images)


def _convert_libreoffice_locked(docx_path: Path, *, lossless_images: bool = False) -> Path:
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
        # Final Monthly reports preserve the already-prepared source pixels.
        # Other callers retain the original Writer export defaults. Do not
        # change page geometry or reapply an image-resolution budget here.
        export_filter = 'pdf:writer_pdf_Export'
        if lossless_images:
            export_filter += (':{"UseLosslessCompression":{"type":"boolean","value":"true"},'
                              '"ReduceImageResolution":{"type":"boolean","value":"false"}}')
        try:
            result = run_office([
                lo_bin, "--headless", f"-env:UserInstallation={profile_uri}",
                "--convert-to", export_filter, "--outdir", str(job),
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


def convert_to_pdf(
    docx_path: Path,
    *,
    lossless_images: bool = False,
    converter: PDFConverter | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """
    Convert a .docx file to .pdf using the configured backend.
    Returns the Path to the generated PDF.

    Final Monthly reports opt into lossless image encoding without resampling.
    That guarantee requires LibreOffice; default callers keep their prior
    backend behavior and export settings.

    The returned file is NOT the caller's to forget: see the module docstring.
    build_msapo_pdf unlinks it in a finally block.

    Raises PDFConversionError for an unknown PDF_BACKEND rather than silently
    falling back to LibreOffice. A typo in the environment variable must fail
    loudly -- a silent fallback would make the deployment work while reporting a
    configuration that is not what is running.
    """
    if type(lossless_images) is not bool:
        raise PDFConversionError("The lossless image option must be a boolean.")
    source = os.environ if env is None else env
    if converter is not None or source.get("EPC_PDF_CONVERTER"):
        active = converter or get_pdf_converter(source)
        if lossless_images:
            # Never downgrade monthly lossless images by selecting another renderer.
            if getattr(active, "name", "") != "libreoffice":
                raise PDFConversionError("Requested lossless image export requires LibreOffice.")
            return _convert_libreoffice(docx_path, lossless_images=True)
        if converter is None and getattr(active, "name", "") == "libreoffice":
            # Preserve existing production process limits and PDF publication.
            return _convert_libreoffice(docx_path)
        return _validate_converted_pdf(active.convert(docx_path, docx_path.parent))
    backend = PDF_BACKEND.lower()
    converter = _BACKENDS.get(backend)
    if converter is None:
        raise PDFConversionError(
            f"Unknown PDF_BACKEND '{backend}'. "
            f"Choose from: {', '.join(_BACKENDS)}"
        )
    if lossless_images:
        # Untested alternative backends cannot silently claim this guarantee.
        # Monthly keeps the completed Word download on conversion failure.
        if backend != 'libreoffice':
            raise PDFConversionError("Requested lossless image export requires LibreOffice.")
        return converter(docx_path, lossless_images=True)
    return converter(docx_path)
