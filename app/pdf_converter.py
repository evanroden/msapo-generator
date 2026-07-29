"""Pluggable DOCX-to-PDF conversion backends."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Protocol
from urllib.parse import urlsplit

import requests

from app.adapter_loader import AdapterConfigurationError, load_adapter


class PDFConversionError(Exception):
    pass


class PDFConverter(Protocol):
    name: str

    def convert(self, docx_path: Path, output_dir: Path) -> Path: ...

    def diagnostic(self) -> Mapping[str, object]: ...


def _validated_pdf(data: bytes, *, source: str) -> bytes:
    if not data.startswith(b"%PDF-"):
        raise PDFConversionError(
            f"{source} did not return a valid PDF file. The DOCX remains available."
        )
    return data


def _safe_target(docx_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{docx_path.stem}.pdf"


class LibreOfficeConverter:
    name = "libreoffice"

    def diagnostic(self) -> Mapping[str, object]:
        binary = shutil.which("libreoffice") or shutil.which("soffice")
        return {"name": self.name, "configured": bool(binary), "binary": binary}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        binary = shutil.which("libreoffice") or shutil.which("soffice")
        if not binary:
            raise PDFConversionError(
                "LibreOffice is not installed or not on PATH. Select another converter or install it."
            )
        if not docx_path.exists():
            raise PDFConversionError(f"DOCX file does not exist: {docx_path}")

        target = _safe_target(docx_path, output_dir)
        # A unique LibreOffice profile prevents concurrent conversions from
        # sharing a lock file. A unique output directory prevents an old PDF from
        # being mistaken for a newly generated one.
        with tempfile.TemporaryDirectory(prefix="epc-lo-") as temp_root:
            temp = Path(temp_root)
            profile = temp / "profile"
            converted_dir = temp / "converted"
            profile.mkdir()
            converted_dir.mkdir()
            profile_uri = profile.resolve().as_uri()
            try:
                result = subprocess.run(
                    [
                        binary,
                        f"-env:UserInstallation={profile_uri}",
                        "--headless",
                        "--convert-to",
                        "pdf:writer_pdf_Export",
                        "--outdir",
                        str(converted_dir),
                        str(docx_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except subprocess.TimeoutExpired as exc:
                raise PDFConversionError(
                    "LibreOffice conversion timed out after 120 seconds."
                ) from exc
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "unknown error").strip()[:800]
                raise PDFConversionError(f"LibreOffice conversion failed: {detail}")
            generated = converted_dir / f"{docx_path.stem}.pdf"
            if not generated.exists():
                alternatives = (
                    ", ".join(path.name for path in converted_dir.iterdir()) or "none"
                )
                raise PDFConversionError(
                    "LibreOffice completed without the expected PDF. Produced files: "
                    + alternatives
                )
            target.write_bytes(
                _validated_pdf(generated.read_bytes(), source="LibreOffice")
            )
        return target


class GotenbergConverter:
    name = "gotenberg"

    def __init__(
        self,
        *,
        base_url: str,
        allow_insecure: bool = False,
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.allow_insecure = allow_insecure
        self.timeout = timeout
        split = urlsplit(self.base_url)
        local = split.hostname in {"localhost", "127.0.0.1", "::1", "gotenberg"}
        if split.scheme not in {"http", "https"} or not split.hostname:
            raise AdapterConfigurationError(
                "GOTENBERG_URL must be an absolute HTTP(S) URL."
            )
        if split.scheme != "https" and not (allow_insecure or local):
            raise AdapterConfigurationError(
                "Remote Gotenberg endpoints must use HTTPS unless "
                "EPC_ALLOW_INSECURE_CONVERTER=true."
            )

    def diagnostic(self) -> Mapping[str, object]:
        return {"name": self.name, "configured": True, "base_url": self.base_url}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        if not docx_path.exists():
            raise PDFConversionError(f"DOCX file does not exist: {docx_path}")
        endpoint = f"{self.base_url}/forms/libreoffice/convert"
        with docx_path.open("rb") as handle:
            response = requests.post(
                endpoint,
                files={
                    "files": (
                        docx_path.name,
                        handle,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                timeout=self.timeout,
            )
        if response.status_code != 200:
            raise PDFConversionError(
                f"Gotenberg returned HTTP {response.status_code}: {response.text[:500]}"
            )
        content_length = response.headers.get("Content-Length")
        try:
            declared_length = int(content_length) if content_length else None
        except (TypeError, ValueError):
            declared_length = None
        if declared_length and declared_length > 50 * 1024 * 1024:
            raise PDFConversionError(
                "Gotenberg response exceeds the 50 MB safety limit."
            )
        if len(response.content) > 50 * 1024 * 1024:
            raise PDFConversionError(
                "Gotenberg response exceeds the 50 MB safety limit."
            )
        data = _validated_pdf(response.content, source="Gotenberg")
        target = _safe_target(docx_path, output_dir)
        target.write_bytes(data)
        return target


class Docx2PdfConverter:
    name = "docx2pdf"

    def diagnostic(self) -> Mapping[str, object]:
        try:
            import docx2pdf  # noqa: F401

            return {"name": self.name, "configured": True}
        except ImportError:
            return {
                "name": self.name,
                "configured": False,
                "error": "docx2pdf is not installed",
            }

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        try:
            from docx2pdf import convert
        except ImportError as exc:
            raise PDFConversionError("docx2pdf is not installed.") from exc
        target = _safe_target(docx_path, output_dir)
        import sys

        co_initialized = False
        if sys.platform == "win32":
            try:
                import pythoncom

                pythoncom.CoInitialize()
                co_initialized = True
            except Exception:
                pass
        try:
            convert(str(docx_path), str(target))
        finally:
            if co_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        if not target.exists():
            raise PDFConversionError("docx2pdf ran but did not create a PDF.")
        target.write_bytes(_validated_pdf(target.read_bytes(), source="docx2pdf"))
        return target


class DisabledConverter:
    name = "none"

    def diagnostic(self) -> Mapping[str, object]:
        return {"name": self.name, "configured": True}

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        raise PDFConversionError(
            "PDF conversion is disabled; the DOCX remains available."
        )


def _validate_converter(converter: object) -> PDFConverter:
    if not getattr(converter, "name", None):
        raise AdapterConfigurationError("PDF converter must expose a name.")
    for method in ("convert", "diagnostic"):
        if not callable(getattr(converter, method, None)):
            raise AdapterConfigurationError(
                f"PDF converter must implement {method}()."
            )
    return converter  # type: ignore[return-value]


def get_pdf_converter(env: Mapping[str, str] | None = None) -> PDFConverter:
    source = os.environ if env is None else env
    name = (
        source.get("EPC_PDF_CONVERTER")
        or source.get("PDF_BACKEND")
        or "libreoffice"
    ).strip().lower()
    if name == "libreoffice":
        return _validate_converter(LibreOfficeConverter())
    if name == "gotenberg":
        allow_insecure = str(
            source.get("EPC_ALLOW_INSECURE_CONVERTER", "false")
        ).lower() in {"1", "true", "yes", "on"}
        return _validate_converter(
            GotenbergConverter(
                base_url=source.get("GOTENBERG_URL", "http://localhost:3000"),
                allow_insecure=allow_insecure,
            )
        )
    if name == "docx2pdf":
        return _validate_converter(Docx2PdfConverter())
    if name in {"none", "disabled"}:
        return _validate_converter(DisabledConverter())
    if name == "custom":
        converter = load_adapter(
            source.get("EPC_PDF_CONVERTER_ADAPTER", ""),
            kind="PDF converter",
            required_methods=("convert", "diagnostic"),
            env=source,
        )
        return _validate_converter(converter)
    raise AdapterConfigurationError(
        f"Unknown PDF converter {name!r}. Use libreoffice, gotenberg, "
        "docx2pdf, none, or custom."
    )


def convert_to_pdf(
    docx_path: Path,
    *,
    converter: PDFConverter | None = None,
    output_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    active = converter or get_pdf_converter(env)
    return active.convert(docx_path, output_dir or docx_path.parent)


# Backward-compatible private helpers retained for older imports/tests.
def _convert_libreoffice(docx_path: Path) -> Path:
    return LibreOfficeConverter().convert(docx_path, docx_path.parent)


def _convert_gotenberg(docx_path: Path) -> Path:
    return GotenbergConverter(
        base_url=os.getenv("GOTENBERG_URL", "http://localhost:3000"),
        allow_insecure=True,
    ).convert(docx_path, docx_path.parent)


def _convert_docx2pdf(docx_path: Path) -> Path:
    return Docx2PdfConverter().convert(docx_path, docx_path.parent)


_BACKENDS = {
    "libreoffice": _convert_libreoffice,
    "gotenberg": _convert_gotenberg,
    "docx2pdf": _convert_docx2pdf,
}
