"""Pluggable PDF text extraction and page rendering."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from app.adapter_loader import AdapterConfigurationError, load_adapter


class PDFReaderError(RuntimeError):
    """Raised when a PDF cannot be opened, read, or safely rendered."""


@dataclass(frozen=True)
class PDFReadResult:
    text: str
    analysis_bytes: bytes
    page_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("PDF reader text must be a string.")
        if not isinstance(self.analysis_bytes, bytes) or not self.analysis_bytes:
            raise ValueError("PDF reader must return non-empty analysis bytes.")
        if self.page_count < 1:
            raise ValueError("PDF reader page_count must be at least 1.")


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    data: bytes
    media_type: str = "image/png"

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("Rendered page numbers must start at 1.")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("Rendered pages must contain non-empty bytes.")
        if not self.media_type.startswith("image/"):
            raise ValueError("Rendered page media_type must be an image type.")


class PDFReader(Protocol):
    name: str

    def extract_text(self, data: bytes) -> PDFReadResult: ...

    def render_pages(
        self,
        data: bytes,
        *,
        dpi: int,
        max_pages: int,
        max_pixels_per_page: int,
    ) -> Sequence[RenderedPage]: ...

    def diagnostic(self) -> Mapping[str, object]: ...


class PyMuPDFReader:
    name = "pymupdf"

    @staticmethod
    def _fitz():
        try:
            import fitz
        except ImportError as exc:
            raise PDFReaderError(
                "PyMuPDF is selected but the PyMuPDF package is not installed."
            ) from exc
        return fitz

    def diagnostic(self) -> Mapping[str, object]:
        try:
            fitz = self._fitz()
            version = getattr(fitz, "VersionBind", "unknown")
            return {"name": self.name, "configured": True, "version": version}
        except PDFReaderError as exc:
            return {"name": self.name, "configured": False, "error": str(exc)}

    def extract_text(self, data: bytes) -> PDFReadResult:
        fitz = self._fitz()
        try:
            text_parts: list[str] = []
            analysis_bytes = data
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass and not pdf.authenticate(""):
                    raise PDFReaderError(
                        "This PDF requires a password to open; password-protected files are unsupported."
                    )
                if pdf.is_encrypted:
                    analysis_bytes = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)
                for page in pdf:
                    text_parts.append(page.get_text())
                return PDFReadResult(
                    text="\n".join(text_parts).strip(),
                    analysis_bytes=analysis_bytes,
                    page_count=pdf.page_count,
                )
        except PDFReaderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PDFReaderError(f"PyMuPDF could not read the PDF: {exc}") from exc

    def render_pages(
        self,
        data: bytes,
        *,
        dpi: int,
        max_pages: int,
        max_pixels_per_page: int,
    ) -> Sequence[RenderedPage]:
        fitz = self._fitz()
        try:
            pages: list[RenderedPage] = []
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass and not pdf.authenticate(""):
                    raise PDFReaderError(
                        "This PDF requires a password to open; password-protected files are unsupported."
                    )
                if pdf.page_count > max_pages:
                    raise PDFReaderError(
                        f"The PDF has {pdf.page_count} pages; the configured OCR maximum is {max_pages}."
                    )
                for index, page in enumerate(pdf):
                    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                    if pixmap.width * pixmap.height > max_pixels_per_page:
                        raise PDFReaderError(
                            f"PDF page {index + 1} renders above the configured pixel limit."
                        )
                    pages.append(
                        RenderedPage(index + 1, pixmap.tobytes("png"), "image/png")
                    )
            return pages
        except PDFReaderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PDFReaderError(f"PyMuPDF could not render the PDF: {exc}") from exc


def _validate_reader(reader: object) -> PDFReader:
    missing = [
        name
        for name in ("extract_text", "render_pages", "diagnostic")
        if not callable(getattr(reader, name, None))
    ]
    if missing or not getattr(reader, "name", None):
        raise AdapterConfigurationError(
            "PDF reader must expose name and methods: extract_text, render_pages, diagnostic."
        )
    return reader  # type: ignore[return-value]


def get_pdf_reader(env: Mapping[str, str] | None = None) -> PDFReader:
    source = os.environ if env is None else env
    name = (source.get("EPC_PDF_READER") or "pymupdf").strip().lower()
    if name == "pymupdf":
        return _validate_reader(PyMuPDFReader())
    if name == "custom":
        reader = load_adapter(
            source.get("EPC_PDF_READER_ADAPTER", ""),
            kind="PDF reader",
            required_methods=("extract_text", "render_pages", "diagnostic"),
            env=source,
        )
        return _validate_reader(reader)
    raise AdapterConfigurationError(
        f"Unknown EPC_PDF_READER {name!r}. Use 'pymupdf' or 'custom'."
    )
