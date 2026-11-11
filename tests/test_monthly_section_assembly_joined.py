"""Joined synthetic section assembly acceptance.

This exercises a single saved report with three independent full-page sources,
rather than counting a source one section at a time. No customer originals,
remote AI, shared master, or live production writes are used.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import numpy as np
import pymupdf as fitz
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import generate_report
from app.monthly_report_mbcx_pdf import prepare_whole_pdf
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles,
)
from app.monthly_report_section_uploads import prepare_section_pages
from app.monthly_report_source_scope import correct_scope
from tests.conftest import requires_libreoffice


# Same four edge sentinels on every page; unique center per physical occurrence.
CORNERS = ((250, 18, 184), (18, 231, 34), (254, 200, 20), (23, 100, 251))
CENTERS = (
    (210, 26, 43), (10, 193, 200), (181, 32, 232),
    (227, 121, 16), (32, 147, 229), (185, 53, 188),
    (117, 201, 24), (246, 74, 136), (36, 204, 215),
)
PAGES = ((612, 792, 0), (792, 612, 0), (480, 920, 90))


def _rgb(value):
    return tuple(part / 255 for part in value)


def _source_pdf(label, colors):
    with fitz.open() as document:
        for number, ((width, height, rotation), color) in enumerate(zip(PAGES, colors), 1):
            page = document.new_page(width=width, height=height)
            page.insert_text(
                (50, 64),
                f"Synthetic {label} inspection completed. Checked page {number}.",
                fontsize=12,
            )
            edge = 35
            boxes = (
                fitz.Rect(4, 4, edge, edge),
                fitz.Rect(width - edge, 4, width - 4, edge),
                fitz.Rect(4, height - edge, edge, height - 4),
                fitz.Rect(width - edge, height - edge, width - 4, height - 4),
            )
            for rectangle, corner in zip(boxes, CORNERS):
                page.draw_rect(rectangle, color=None, fill=_rgb(corner), overlay=True)
            page.draw_rect(
                fitz.Rect(width / 2 - 24, height / 2 - 24,
                          width / 2 + 24, height / 2 + 24),
                color=None, fill=_rgb(color), overlay=True,
            )
            if rotation:
                page.set_rotation(rotation)
        return document.tobytes()


def _included_source(profile, destination, label, colors, previous):
    filename = f"synthetic-{label}.pdf"
    original = _source_pdf(label, colors)
    content, messages = sources.ingest(profile, filename, original)
    assert content is not None, messages

    if destination in {"mbcx_report", "utility_analysis"}:
        revised, additions = prepare_whole_pdf(
            profile, content, previous, destination=destination)
    else:
        # Water uses its existing explicit per-page approval and automatic
        # complete selected-document assembly; no new chooser is introduced.
        numbered = (1, 2, 3)
        source = replace(
            content.source, selected_pages=numbered,
            captions=tuple((n, f"{filename} · page/item {n}") for n in numbered))
        source = replace(source, client_page_reviews=tuple(
            (n, page_fingerprint(source, n)) for n in numbered))
        revised = replace(content, source=source)
        additions = prepare_section_pages(
            profile, (revised,), destination, previous)
    source = correct_scope(
        revised.source, profile, (profile.facilities[0].key,))
    source = replace(source, service_date="2026-09-12",
                     facility=profile.facilities[0].key)
    block = approve_all_assets(refresh_asset_source_context(
        additions[destination], (source,)))
    assert len(block.asset_hashes) == 3
    assert block.references == tuple(sources.source_reference(source, n) for n in (1, 2, 3))
    assert sources.source_bytes(profile, source) == original
    return source, block, original


def _matching_pixels(frame, rgb):
    difference = np.abs(frame - np.asarray(rgb, dtype=np.int16))
    return np.nonzero(np.all(difference <= 30, axis=2))


def _frame(page):
    picture = page.get_pixmap(matrix=fitz.Matrix(0.85, 0.85), alpha=False)
    return np.frombuffer(picture.samples, dtype=np.uint8).reshape(
        picture.height, picture.width, picture.n)[:, :, :3].astype(np.int16)


@requires_libreoffice
def test_scorecards_mbcx_and_water_keep_nine_occurrences_once_after_reopen(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "isolated-library"))
    profile = synthetic_profiles()[0]
    period = ReportPeriod(2026, 9)
    original_files, accepted_sources, accepted_blocks = {}, [], {}
    routes = (
        ("utility_analysis", "scorecard", CENTERS[:3]),
        ("mbcx_report", "commissioning", CENTERS[3:6]),
        ("water_reports", "water-treatment", CENTERS[6:9]),
    )
    for destination, label, centers in routes:
        source, block, raw = _included_source(
            profile, destination, label, centers, accepted_blocks)
        accepted_sources.append(source)
        accepted_blocks[destination] = block
        original_files[destination] = raw
    accepted_blocks["water_monthly_update"] = ResolvedBlock(
        "water_monthly_update", "This month",
        text="Synthetic monthly Water update and action.")
    accepted_blocks["equipment_issues"] = ResolvedBlock(
        "equipment_issues", "This month",
        text="Synthetic separate issue card remains unchanged.")

    sections = tuple(
        section for section in default_sections()
        if section.key in {"scorecards", "mbcx", "water", "issues"})
    draft = ReportDraft(
        profile, period, "Synthetic Editor", sections,
        tuple(accepted_blocks.values()), sources=tuple(accepted_sources),
        synthetic=True)
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, period).draft
    assert reopened == draft
    for source, (destination, _, _) in zip(reopened.sources, routes):
        assert sources.source_bytes(profile, source) == original_files[destination]
    loader = lambda ref: library.read_asset(profile.contract, profile.key, ref)
    package = generate_report(
        reopened, acknowledged_fingerprint=reopened.fingerprint,
        asset_loader=loader)
    assert package.docx and package.pdf, package.pdf_error

    word = Document(BytesIO(package.docx))
    assert len(word.inline_shapes) == 9
    # DOCX physical picture geometry must match each differently oriented
    # source page; the rotated third page uses its displayed dimensions.
    for destination, label, _ in routes:
        with fitz.open(stream=original_files[destination], filetype="pdf") as original:
            offset = [item[0] for item in routes].index(destination) * 3
            for index, source_page in enumerate(original):
                shape = word.inline_shapes[offset + index]
                assert shape.width / shape.height == pytest.approx(
                    source_page.rect.width / source_page.rect.height, rel=0.015)

    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        outline = pdf.get_toc()
        assert [entry[1] for entry in outline] == [
            "1. Monthly Scorecards", "2. MBCx Reports",
            "3. Water Treatment Reports", "4. Equipment Performance Issues",
        ]
        texts = [page.get_text() for page in pdf]
        page_positions = []
        for destination, label, palette in routes:
            positions = []
            for index, center in enumerate(palette, 1):
                caption = f"synthetic-{label}.pdf · page/item {index}"
                found = [number for number, page_text in enumerate(texts)
                         if caption in page_text]
                assert len(found) == 1, (destination, caption, found)
                position = found[0]
                positions.append(position)
                frame = _frame(pdf[position])
                xs, ys = _matching_pixels(frame, center)
                assert len(xs) >= 30, (destination, index, "center lost")
                quadrants = []
                for corner in CORNERS:
                    cx, cy = _matching_pixels(frame, corner)
                    assert len(cx) >= 30, (destination, index, corner)
                    quadrants.append((float(cx.mean()), float(cy.mean())))
                middle_x = sum(x for x, _ in quadrants) / 4
                middle_y = sum(y for _, y in quadrants) / 4
                assert len({(x < middle_x, y < middle_y)
                            for x, y in quadrants}) == 4
            assert positions == list(range(positions[0], positions[0] + 3))
            page_positions.extend(positions)
        assert page_positions == sorted(set(page_positions))
        joined = "\n".join(texts)
        assert joined.count("Synthetic monthly Water update and action.") == 1
        assert joined.count("Synthetic separate issue card remains unchanged.") == 1
        assert joined.index("Synthetic monthly Water update and action.") < joined.index(
            "synthetic-water-treatment.pdf · page/item 1")
        assert page_positions[0] < page_positions[3] < page_positions[6]
    # Rendering is derivative-only; the three accepted source PDFs stay exact.
    for source, (destination, _, _) in zip(accepted_sources, routes):
        assert sources.source_bytes(profile, source) == original_files[destination]
