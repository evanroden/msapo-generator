"""Generate the lightweight Scope/Inclusions/Exclusions PO attachment.

DORMANT since 2026-08-12. Reached only by tests/test_scope_pdf.py.

This built the PO attachment between 2026-08-08 and 2026-08-12. Contract
administration then reversed the policy back to the full MSAPO form, so the live
attachment is built by document_generator.build_msapo_pdf via pdf_converter, and
build_scope_pdf has no production caller. The paragraph below describes the
policy as it stood while this was live; read it as history.

DO NOT DELETE without asking. Three reasons, in order:

1. The policy it implements has already been reversed ONCE, in this direction.
   This module went dormant and document_generator -- which it had itself
   replaced -- came back. A second reversal is a business decision, not a code
   smell, and this file is what makes it cheap.
2. tests/test_smartsheet_handoff_entrypoint.py asserts
   `source.count("build_scope_pdf(") == 0` in app/web_ui.py. That encodes "the
   scope PDF is not the attachment", so it passes today AND would keep passing
   after a deletion. It does not guard this module and will not warn you.
3. Deleting it also deletes tests/test_scope_pdf.py, the only remaining record of
   the simplified layout that contract administration approved at the time.

If it does get removed, that belongs in its own commit with the reversal
documented -- not folded into a cleanup.

--- history, accurate while this was the live attachment ---

This PDF intentionally contains no MSAPO agreement language and replaces the
former DOCX-plus-converted-PDF package.  It is built directly with PyMuPDF,
which is already required for quote extraction, so every PO route receives the
same two-file package: the unchanged vendor quote and this reviewed PDF.
"""

from __future__ import annotations

import re
from typing import Iterable

import fitz


_PAGE_WIDTH = 612.0  # US Letter, points
_PAGE_HEIGHT = 792.0
_LEFT = 54.0
_RIGHT = 54.0
_TOP = 54.0
_BOTTOM = 54.0
_BODY_SIZE = 10.5
_BODY_LEADING = 15.0
_OCEAN_STEEL = (9 / 255, 43 / 255, 36 / 255)
_BLUE_STEEL = (85 / 255, 127 / 255, 127 / 255)
_SAFETY_YELLOW = (214 / 255, 239 / 255, 75 / 255)
_DARK_IRON = (0.0, 0.0, 0.0)


def _pdf_text(value: object) -> str:
    """Normalize common typography for the built-in Helvetica font."""
    text = str(value or "")
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "-",
        "\u00a0": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _wrap(text: str, width: float, *, size: float, font: str) -> list[str]:
    """Wrap one logical line to the available point width."""
    words = _pdf_text(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if fitz.get_text_length(candidate, fontname=font, fontsize=size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        # Split a single pathological token rather than allowing it past the
        # margin or dropping it from the PDF.
        chunk = ""
        for character in word:
            candidate = chunk + character
            if chunk and fitz.get_text_length(
                candidate, fontname=font, fontsize=size
            ) > width:
                lines.append(chunk)
                chunk = character
            else:
                chunk = candidate
        current = chunk
    if current:
        lines.append(current)
    return lines


class _Writer:
    def __init__(self, document: fitz.Document):
        self.document = document
        self.page: fitz.Page | None = None
        self.y = _TOP
        self.page_number = 0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        self.page_number += 1
        self.y = _TOP
        self.page.draw_rect(
            fitz.Rect(_LEFT, 31, _PAGE_WIDTH - _RIGHT, 36),
            color=_SAFETY_YELLOW,
            fill=_SAFETY_YELLOW,
            width=0,
        )
        self.page.insert_text(
            (_LEFT, 47),
            "PURCHASE ORDER SUPPORT",
            fontname="helv",
            fontsize=7.5,
            color=_BLUE_STEEL,
        )
        self.page.insert_text(
            (_PAGE_WIDTH - _RIGHT - 38, _PAGE_HEIGHT - 24),
            f"Page {self.page_number}",
            fontname="helv",
            fontsize=8,
            color=_BLUE_STEEL,
        )

    def _ensure(self, height: float) -> None:
        if self.y + height > _PAGE_HEIGHT - _BOTTOM:
            self._new_page()

    def spacer(self, height: float = 7.0) -> None:
        self._ensure(height)
        self.y += height

    def paragraph(
        self,
        text: object,
        *,
        size: float = _BODY_SIZE,
        font: str = "helv",
        color: tuple[float, float, float] = _DARK_IRON,
        leading: float = _BODY_LEADING,
        prefix: str = "",
    ) -> None:
        logical_lines = _pdf_text(text).splitlines() or [""]
        for logical in logical_lines:
            rendered = f"{prefix}{logical}" if logical.strip() else ""
            wrapped = _wrap(
                rendered,
                _PAGE_WIDTH - _LEFT - _RIGHT,
                size=size,
                font=font,
            )
            for line in wrapped:
                self._ensure(leading)
                if line:
                    assert self.page is not None
                    self.page.insert_text(
                        (_LEFT, self.y + size),
                        line,
                        fontname=font,
                        fontsize=size,
                        color=color,
                    )
                self.y += leading

    def section(self, title: str, content: str | Iterable[str], *, bullets: bool) -> None:
        self._ensure(30)
        self.paragraph(
            title,
            size=13,
            font="hebo",
            color=_OCEAN_STEEL,
            leading=18,
        )
        self.spacer(2)
        if bullets:
            items = [str(item).strip() for item in content if str(item).strip()]
            if not items:
                self.paragraph("None stated.", color=_BLUE_STEEL)
            for item in items:
                self.paragraph(item, prefix="- ")
                self.spacer(2)
        else:
            text = str(content or "").strip()
            self.paragraph(text or "None stated.")
        self.spacer(10)


def build_scope_pdf(
    *,
    scope: str,
    inclusions: Iterable[str],
    exclusions: Iterable[str],
    vendor: str = "",
    site: str = "",
) -> bytes:
    """Return a reviewable PDF containing only scope, inclusions, and exclusions."""
    document = fitz.open()
    try:
        document.set_metadata(
            {
                "title": "Scope, Inclusions, and Exclusions",
                "subject": "Purchase order supporting attachment",
                "creator": "Purchase Order Process Control",
            }
        )
        writer = _Writer(document)
        writer.paragraph(
            "Scope, Inclusions, and Exclusions",
            size=18,
            font="hebo",
            color=_OCEAN_STEEL,
            leading=23,
        )
        if vendor:
            writer.paragraph(f"Vendor: {vendor}", font="hebo")
        if site:
            writer.paragraph(f"Site: {site}", font="hebo")
        writer.spacer(12)
        writer.section("Scope", scope, bullets=False)
        writer.section("Inclusions", list(inclusions), bullets=True)
        writer.section("Exclusions", list(exclusions), bullets=True)
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()
