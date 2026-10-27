"""Synthetic MBCx source-page geometry, including actual Word/PDF output.

Corner/center color sentinels are visible pixels, not OCR or inferred text.
No real report, historical master, or client source is used.
"""
from dataclasses import replace
from io import BytesIO

import numpy as np
import pymupdf as fitz
import pytest
from docx import Document

from conftest import requires_libreoffice
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_docx import generate_report
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles,
)
from app.monthly_report_section_uploads import prepare_section_pages


# Unusual solid RGBs avoid accidental matches against standard report branding.
CORNERS = (
    (250, 18, 184), (18, 231, 34), (254, 200, 20), (23, 100, 251),
)
CENTERS = (
    (210, 26, 43), (10, 193, 200), (181, 32, 232), (11, 134, 82),
)
# Third source is stored portrait but displayed landscape by its PDF rotation.
PAGES = ((612, 792, 0), (792, 612, 0), (480, 920, 90), (376, 864, 0))


def _rgb(color):
    return tuple(component / 255 for component in color)


def _source_pdf(pages=PAGES):
    with fitz.open() as document:
        for index, (width, height, rotation) in enumerate(pages):
            page = document.new_page(width=width, height=height)
            page.insert_text(
                (50, 62),
                f"Synthetic MBCx inspection completed. Equipment DEMO-{index + 1}.",
                fontsize=12,
            )
            edge = 35
            for rect, color in zip((
                fitz.Rect(4, 4, edge, edge),
                fitz.Rect(width - edge, 4, width - 4, edge),
                fitz.Rect(4, height - edge, edge, height - 4),
                fitz.Rect(width - edge, height - edge, width - 4, height - 4),
            ), CORNERS):
                page.draw_rect(rect, color=None, fill=_rgb(color), overlay=True)
            center = fitz.Rect(width / 2 - 22, height / 2 - 22,
                               width / 2 + 22, height / 2 + 22)
            page.draw_rect(center, color=None, fill=_rgb(CENTERS[index]), overlay=True)
            if rotation:
                page.set_rotation(rotation)
        return document.tobytes()


def _prepared_report(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "isolated-store"))
    profile = synthetic_profiles()[0]
    library.save_profile(
        profile, expected_revision=0, actor="Synthetic Editor", confirmed=True,
    )
    original = _source_pdf()
    content, _ = sources.ingest(profile, "synthetic-MBCx-geometry.pdf", original)
    indexes = tuple(range(1, len(PAGES) + 1))
    assert tuple(content.source.selected_pages) == indexes
    checked = replace(content.source, client_page_reviews=tuple(
        (number, page_fingerprint(content.source, number)) for number in indexes
    ))
    content = replace(content, source=checked)
    assert all(page_allowed(checked, number) for number in indexes)
    prepared = prepare_section_pages(profile, (content,), "mbcx_report", {})
    mbcx = prepared["mbcx_report"]
    assert len(mbcx.asset_hashes) == len(PAGES)
    assert mbcx.references == tuple(sources.source_reference(checked, n) for n in indexes)
    assert sources.source_bytes(profile, checked) == original
    sections = default_sections()
    mbcx_section = next(s for s in sections if s.key == "mbcx")
    issues_section = next(s for s in sections if s.key == "issues")
    draft = ReportDraft(
        profile, ReportPeriod(2026, 10), "Synthetic Editor",
        (mbcx_section, issues_section),
        (
            ResolvedBlock("mbcx_status", "This month",
                          text="Synthetic monitoring results recorded for this month."),
            mbcx,
            ResolvedBlock("equipment_issues", "This month",
                          text="Synthetic following-section issue inspection completed."),
        ),
        synthetic=True, sources=(checked,),
    )
    def loader(reference):
        return library.read_asset(profile.contract, profile.key, reference)
    return draft, loader, original, content


def _matches(page, color):
    pix = page.get_pixmap(matrix=fitz.Matrix(0.85, 0.85), alpha=False)
    frame = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    difference = np.abs(frame[:, :, :3].astype(np.int16) -
                        np.asarray(color, dtype=np.int16))
    ys, xs = np.nonzero(np.all(difference <= 28, axis=2))
    return (xs, ys)


def _box(page, color):
    xs, ys = _matches(page, color)
    assert len(xs) >= 30, f"Sentinel {color} was cropped or disappeared"
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def test_mixed_source_page_raster_keeps_rotated_dimensions_and_all_four_edges(tmp_path, monkeypatch):
    draft, loader, original, content = _prepared_report(tmp_path, monkeypatch)
    with fitz.open(stream=original, filetype="pdf") as source:
        for number, page in enumerate(source, 1):
            prepared = sources.page_image(draft.profile, content, number)
            with fitz.open() as irrelevant:
                assert irrelevant.page_count == 0
            from PIL import Image
            with Image.open(BytesIO(prepared.data)) as image:
                actual = image.width / image.height
            expected = page.rect.width / page.rect.height
            assert abs(actual / expected - 1) <= 0.015, (number, actual, expected)
    # A second load returns verified cached derivatives without changing sources.
    assert sources.source_bytes(draft.profile, content.source) == original
    assert all(loader(reference) for reference in draft.block("mbcx_report").asset_hashes)


@requires_libreoffice
def test_real_word_pdf_preserves_every_mbcx_corner_and_next_section(tmp_path, monkeypatch):
    draft, loader, original, content = _prepared_report(tmp_path, monkeypatch)
    package = generate_report(
        draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader,
    )
    assert package.docx and package.pdf, package.pdf_error
    word = Document(BytesIO(package.docx))
    assert len(word.inline_shapes) == len(PAGES)
    with fitz.open(stream=original, filetype="pdf") as source:
        for inline, page in zip(word.inline_shapes, source):
            actual = inline.width / inline.height
            expected = page.rect.width / page.rect.height
            assert abs(actual / expected - 1) <= 0.015, (actual, expected)

    with fitz.open(stream=package.pdf, filetype="pdf") as document:
        page_for_source = []
        for color in CENTERS:
            matching = [n for n, page in enumerate(document)
                        if len(_matches(page, color)[0]) >= 30]
            assert len(matching) == 1, (color, matching)
            page_for_source.append(matching[0])
        assert page_for_source == list(range(page_for_source[0],
                                             page_for_source[0] + len(PAGES)))
        for index, output_page in enumerate(page_for_source):
            pdf_page = document[output_page]
            boxes = [_box(pdf_page, color) for color in CORNERS]
            centers = [((left + right) / 2, (top + bottom) / 2)
                       for left, top, right, bottom in boxes]
            midpoint_x = sum(x for x, _ in centers) / 4
            midpoint_y = sum(y for _, y in centers) / 4
            assert len({(x < midpoint_x, y < midpoint_y)
                        for x, y in centers}) == 4, index
            extent_x = max(x for x, _ in centers) - min(x for x, _ in centers)
            extent_y = max(y for _, y in centers) - min(y for _, y in centers)
            width, height, rotation = PAGES[index]
            expected = (height / width) if rotation in (90, 270) else (width / height)
            assert 0.76 <= (extent_x / extent_y) / expected <= 1.24, index
        following = [n for n, page in enumerate(document)
                     if "Synthetic following-section issue inspection completed." in page.get_text()]
        assert following and min(following) > page_for_source[-1]
    assert sources.source_bytes(draft.profile, content.source) == original


def test_oversized_source_refuses_raster_without_truncating_or_changing_original(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "isolated-store"))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor",
                         confirmed=True)
    with fitz.open() as pdf:
        page = pdf.new_page(width=4000, height=8000)
        page.insert_text((60, 70), "Synthetic MBCx equipment inspection performed.")
        original = pdf.tobytes()
    content, _ = sources.ingest(profile, "synthetic-oversized-MBCx.pdf", original)
    with pytest.raises(ValueError, match="too large to rasterize safely"):
        sources.page_image(profile, content, 1)
    assert sources.source_bytes(profile, content.source) == original
    prepared_path = sources._path(profile, content.source.sha256, content.source.suffix).parent / "prepared" / content.source.sha256
    assert not list(prepared_path.glob("1-print.*")) if prepared_path.exists() else True
