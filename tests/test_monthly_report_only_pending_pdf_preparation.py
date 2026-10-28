"""Regression for append-only PDF preparation: no already-owned page reprocessing.

Every PDF and report scope is synthetic. These tests execute the real bounded
importer, client-page approval, image preparation and section appendix layer;
they observe physical page raster requests as well as returned references.
"""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from app.monthly_report_section_uploads import (
    included_pages, pending_pages, preflight_whole_pdf,
    prepare_section_pages,
)


def synthetic_pdf(count, *, marker="A"):
    with fitz.open() as pdf:
        for index in range(count):
            page = pdf.new_page(width=144, height=180)
            page.insert_text(
                (12, 30),
                f"Synthetic {marker} service report page {index + 1}. "
                "Inspection completed.",
                fontsize=8,
            )
        return pdf.tobytes()


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def read_approved(profile, *, count=3, marker="A"):
    original = synthetic_pdf(count, marker=marker)
    content, attachments = sources.ingest(
        profile, f"synthetic-{marker}.pdf", original)
    assert attachments == ()
    approved = replace(content.source, client_page_reviews=tuple(
        (page, page_fingerprint(content.source, page))
        for page in range(1, count + 1)
    ))
    return replace(content, source=approved), original


def prepared_first(profile, content, destination="water_reports"):
    source = content.source
    result = sources.prepare_pages(
        profile, (content,), ((source.id, destination),),
        only_pages=frozenset({(source.id, 1)}),
    )
    assert len(result) == 1
    assert len(result[0].asset_hashes) == 1
    return replace(result[0], text="Keep this independent monthly note.")


def trace_pages(monkeypatch):
    original = sources.page_image
    calls = []

    def traced(profile, content, page, *args, **kwargs):
        calls.append((content.source.id, page))
        return original(profile, content, page, *args, **kwargs)

    monkeypatch.setattr(sources, "page_image", traced)
    return calls


def test_default_add_prepares_only_new_pages_not_selected_existing_ones(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=3)
    first = prepared_first(workspace, content)
    blocks = {"water_reports": first}
    assert pending_pages((content,), "water_reports", blocks) == (
        (content.source.id, 2), (content.source.id, 3))
    estimate = preflight_whole_pdf(
        workspace, content, "water_reports", blocks)
    assert (estimate.new_pages, estimate.already_included) == (2, 1)
    assert estimate.pages_fit
    calls = trace_pages(monkeypatch)

    additions = prepare_section_pages(
        workspace, (content,), "water_reports", blocks)
    expected = (
        sources.source_reference(content.source, 2),
        sources.source_reference(content.source, 3))
    assert set(additions) == {"water_reports"}
    assert additions["water_reports"].references == expected
    assert calls == [(content.source.id, 2), (content.source.id, 3)]
    assert first.text == "Keep this independent monthly note."
    assert first.references == (sources.source_reference(content.source, 1),)
    assert first.asset_hashes != additions["water_reports"].asset_hashes
    assert sources.source_bytes(workspace, content.source) == original


def test_prior_page_with_retired_approval_is_not_rechecked_when_appending(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=2)
    first = prepared_first(workspace, content)
    # An earlier selected/included page retains its own report occurrence.
    # The source's current page-review record can change independently.
    source = replace(
        content.source, client_page_reviews=((
            2, page_fingerprint(content.source, 2)),))
    revised = replace(content, source=source)
    assert revised.source.selected_pages == (1, 2)
    blocks = {"water_reports": first}
    assert included_pages(blocks)[(content.source.id, 1)] == {"water_reports"}
    assert pending_pages((revised,), "water_reports", blocks) == (
        (content.source.id, 2),)
    calls = trace_pages(monkeypatch)

    added = prepare_section_pages(
        workspace, (revised,), "water_reports", blocks)
    assert added["water_reports"].references == (
        sources.source_reference(revised.source, 2),)
    assert calls == [(content.source.id, 2)]
    assert first.references == (sources.source_reference(content.source, 1),)
    assert first.text == "Keep this independent monthly note."
    assert sources.source_bytes(workspace, revised.source) == original


def test_no_pending_pages_does_not_touch_any_pdfs(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=2)
    block, = sources.prepare_pages(
        workspace, (content,), ((content.source.id, "water_reports"),))
    calls = trace_pages(monkeypatch)
    assert prepare_section_pages(
        workspace, (content,), "water_reports",
        {"water_reports": block}) == {}
    assert calls == []
    assert sources.source_bytes(workspace, content.source) == original


def test_explicit_single_page_review_still_limits_additions(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=3)
    first = prepared_first(workspace, content)
    calls = trace_pages(monkeypatch)
    only = frozenset({(content.source.id, 3)})
    result = prepare_section_pages(
        workspace, (content,), "water_reports",
        {"water_reports": first}, only_pages=only)
    assert result["water_reports"].references == (
        sources.source_reference(content.source, 3),)
    assert calls == [(content.source.id, 3)]
    assert sources.source_bytes(workspace, content.source) == original


def test_mixed_files_prepare_only_new_source_page_occurrences(
        workspace, monkeypatch):
    a, raw_a = read_approved(workspace, count=2, marker="Alpha")
    b, raw_b = read_approved(workspace, count=2, marker="Beta")
    already = prepared_first(workspace, a)
    blocks = {"water_reports": already}
    calls = trace_pages(monkeypatch)
    addition = prepare_section_pages(
        workspace, (a, b), "water_reports", blocks)["water_reports"]
    assert addition.references == (
        sources.source_reference(a.source, 2),
        sources.source_reference(b.source, 1),
        sources.source_reference(b.source, 2))
    assert calls == [
        (a.source.id, 2), (b.source.id, 1), (b.source.id, 2)]
    assert sources.source_bytes(workspace, a.source) == raw_a
    assert sources.source_bytes(workspace, b.source) == raw_b
    assert already.text == "Keep this independent monthly note."


def test_near_report_limit_still_counts_only_one_new_page(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=2)
    first = prepared_first(workspace, content)
    padded = replace(
        first,
        asset_hashes=(*first.asset_hashes, *("synthetic-placeholder.png",) * 148),
        asset_captions=(*first.asset_captions, *("",) * 148),
    )
    blocks = {"water_reports": padded}
    estimate = preflight_whole_pdf(
        workspace, content, "water_reports", blocks)
    assert estimate.new_pages == estimate.available_pages == 1
    calls = trace_pages(monkeypatch)
    result = prepare_section_pages(
        workspace, (content,), "water_reports", blocks,
        {"synthetic-placeholder.png": b"x"})
    assert result["water_reports"].references == (
        sources.source_reference(content.source, 2),)
    assert calls == [(content.source.id, 2)]
    assert len(padded.asset_hashes) == 149
    assert sources.source_bytes(workspace, content.source) == original


def test_cross_section_source_ownership_still_refuses_append(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=2)
    other = prepared_first(workspace, content, "vendor_reports")
    calls = trace_pages(monkeypatch)
    with pytest.raises(ValueError, match="another section"):
        prepare_section_pages(
            workspace, (content,), "water_reports",
            {"vendor_reports": other})
    assert calls == []
    assert sources.source_bytes(workspace, content.source) == original


def test_default_append_does_not_silently_approve_an_unreviewed_new_page(
        workspace, monkeypatch):
    content, original = read_approved(workspace, count=2)
    first = prepared_first(workspace, content)
    source = replace(content.source, client_page_reviews=(
        (1, page_fingerprint(content.source, 1)),))
    changed = replace(content, source=source)
    calls = trace_pages(monkeypatch)
    with pytest.raises(ValueError, match="Check page 2"):
        prepare_section_pages(
            workspace, (changed,), "water_reports",
            {"water_reports": first})
    assert calls == []
    assert first.text == "Keep this independent monthly note."
    assert first.asset_hashes
    assert sources.source_bytes(workspace, content.source) == original
