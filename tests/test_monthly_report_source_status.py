"""Disclosure is earned by current page decisions and actual report images."""
from dataclasses import replace
from os import stat_result
from pathlib import Path

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles,
)
from app.monthly_report_source_status import source_manager_status
from test_monthly_report_sources import pdf_bytes


@pytest.fixture
def included(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-utility-results.pdf", pdf_bytes(2))
    source = replace(content.source, classification="Utility results", service_date="2026-09-04",
                     facility=profile.facilities[0].key, selected_pages=(1, 2),
                     captions=((1, "First reviewed utility page"), (2, "Second reviewed utility page")))
    source = replace(source, client_page_reviews=tuple((n, page_fingerprint(source, n)) for n in (1, 2)))
    content = replace(content, source=source)
    block, = sources.prepare_pages(profile, (content,), ((source.id, "utility_analysis"),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor", default_sections(),
                        (block,), sources=(source,), synthetic=True)
    return draft, content, block


def entry(draft, content, **kwargs):
    values = source_manager_status(draft, (content,), **kwargs)
    assert len(values) == 1
    return values[0]


def source_change(draft, content, **changes):
    source = replace(content.source, **changes)
    return replace(draft, sources=(source,)), replace(content, source=source)


def test_real_ingested_reviewed_pdf_is_resolved_only_after_canonical_attachment(included):
    draft, content, block = included
    status = entry(draft, content)
    assert status.resolved and status.reason == ""
    assert (status.source_id, status.filename, status.pages, status.destinations) == (
        content.source.id, content.source.filename, 2, ("utility_analysis",))
    assert not entry(replace(draft, blocks=()), content).resolved


@pytest.mark.parametrize("changes,reason", [
    ({"service_date": ""}, "date"),
    ({"service_date": "2026-08-04"}, "date"),
    ({"service_date": "unresolved"}, "date"),
    ({"facility": ""}, "facility"),
    ({"facility": "Another hospital"}, "facility"),
    ({"classification": "Reference only"}, "use"),
    ({"classification": "CMMS export"}, "use"),
    ({"classification": "Proposal / quote"}, "use"),
    ({"notices": ("Original vector object still needs review.",)}, "notices"),
    ({"selected_pages": ()}, "pages"),
    ({"selected_pages": (1, 3)}, "pages"),
    ({"selected_pages": (1, 1)}, "pages"),
])
def test_unknown_scope_nonpage_uses_and_invalid_selection_stay_open(included, changes, reason):
    draft, content, _ = included
    draft, content = source_change(draft, content, **changes)
    value = entry(draft, content)
    assert not value.resolved and reason in value.reason


@pytest.mark.parametrize("change", ["page_review", "caption", "price", "page_text"])
def test_stale_page_decisions_never_resolve(included, change):
    draft, content, _ = included
    values = {"page_review": {"client_page_reviews": ()},
              "caption": {"captions": ((1, "Changed caption"),)},
              "price": {"captions": ((1, "Cost $125"),)},
              "page_text": {"page_texts": ("Changed technical page.", content.source.page_texts[1])}}
    draft, content = source_change(draft, content, **values[change])
    assert not entry(draft, content).resolved


@pytest.mark.parametrize("change", ["omitted", "disabled", "removed", "duplicate", "ambiguous", "unreviewed", "caption"])
def test_only_one_current_active_reviewed_image_per_selected_page_resolves(included, change):
    draft, content, block = included
    if change == "omitted":
        draft = replace(draft, blocks=(replace(block, source="Omit"),))
    elif change == "disabled":
        draft = replace(draft, sections=tuple(replace(s, included=False) if s.key == "scorecards" else s for s in draft.sections))
    elif change == "removed":
        # A narrative reference survives report-only picture removal.
        draft = replace(draft, blocks=(replace(block, asset_hashes=(), asset_captions=()),))
    elif change == "duplicate":
        draft = replace(draft, blocks=(block, replace(block, key="improvements")))
    elif change == "ambiguous":
        draft = replace(draft, blocks=(replace(block, asset_provenance=tuple(
            (asset, block.references) for asset in block.asset_hashes)),))
    elif change == "unreviewed":
        draft = replace(draft, blocks=(replace(block, client_asset_reviews=(), client_reviewed_fingerprint=""),))
    else:
        draft = replace(draft, blocks=(approve_all_assets(replace(block, asset_captions=("Wrong caption", block.asset_captions[1]))),))
    assert not entry(draft, content).resolved


def test_explicit_exclusion_requires_current_fingerprint_and_no_attached_image(included):
    draft, content, block = included
    source = replace(content.source, selected_pages=(1,), client_page_reviews=tuple(
        item for item in content.source.client_page_reviews if item[0] == 1),
        client_page_exclusions=((2, page_fingerprint(content.source, 2)),))
    content = replace(content, source=source)
    # Preparing once after the decision supplies exact current provenance.
    block, = sources.prepare_pages(draft.profile, (content,), ((source.id, "utility_analysis"),))
    draft = replace(draft, sources=(source,), blocks=(block,))
    value = entry(draft, content)
    assert value.resolved and value.pages == 1
    bad = replace(source, client_page_exclusions=((2, "stale"),))
    assert not entry(replace(draft, sources=(bad,)), replace(content, source=bad)).resolved


def test_excluded_page_still_attached_with_current_provenance_stays_open(included):
    draft, content, block = included
    source = replace(content.source, selected_pages=(1,), client_page_reviews=tuple(
        item for item in content.source.client_page_reviews if item[0] == 1),
        client_page_exclusions=((2, page_fingerprint(content.source, 2)),))
    references = tuple(sources.source_reference(source, n) for n in (1, 2))
    retained = approve_all_assets(replace(block, references=references,
        asset_provenance=tuple((asset, (references[index],))
                               for index, asset in enumerate(block.asset_hashes))))
    assert not entry(replace(draft, sources=(source,), blocks=(retained,)),
                     replace(content, source=source)).resolved


def test_missing_unavailable_and_changed_current_source_stay_actionable(included):
    draft, content, _ = included
    assert not entry(draft, content, unavailable=(content.source,)).resolved
    status, = source_manager_status(draft, ())
    assert not status.resolved and "original" in status.reason
    assert status.source_id == content.source.id
    assert not entry(replace(draft, sources=()), content).resolved
    changed = replace(content, source=replace(content.source, vendor="Changed source details"))
    assert not entry(draft, changed).resolved
    sources._path(draft.profile, content.source.sha256, content.source.suffix).unlink()
    assert not entry(draft, content).resolved


def test_selected_excluded_conflict_and_stale_source_reference_stay_open(included):
    draft, content, block = included
    draft, content = source_change(draft, content, client_page_exclusions=((1, page_fingerprint(content.source, 1)),))
    assert not entry(draft, content).resolved
    draft, content, _ = included
    reference = block.references[0].rsplit(":", 1)[0] + ":old-source-fingerprint"
    changed = replace(block, references=(reference, block.references[1]), asset_provenance=())
    changed = approve_all_assets(changed)
    assert not entry(replace(draft, blocks=(changed,)), content).resolved


def test_current_reference_cannot_hide_older_context_for_same_source_page(included):
    draft, content, block = included
    current = block.references[0]
    stale = current.rsplit(":", 1)[0] + ":old-source-fingerprint"
    provenance = tuple((asset, (current, stale) if index == 0 else (block.references[index],))
                       for index, asset in enumerate(block.asset_hashes))
    changed = approve_all_assets(replace(block, references=(*block.references, stale),
                                        asset_provenance=provenance))
    assert not entry(replace(draft, blocks=(changed,)), content).resolved


def test_absent_source_caption_cannot_waive_pricing_in_attached_caption(included):
    draft, content, _ = included
    source = replace(content.source, captions=())
    source = replace(source, client_page_reviews=tuple((n, page_fingerprint(source, n)) for n in (1, 2)))
    content = replace(content, source=source)
    block, = sources.prepare_pages(draft.profile, (content,), ((source.id, "utility_analysis"),))
    changed = approve_all_assets(replace(block, asset_captions=("Cost $125", block.asset_captions[1])))
    status = entry(replace(draft, sources=(source,), blocks=(changed,)), content)
    assert not status.resolved and "pricing" in status.reason


@pytest.mark.parametrize("size", [0, sources.MAX_FILE_BYTES + 1])
def test_invalid_original_stat_cannot_resolve(included, size, monkeypatch):
    draft, content, _ = included
    original = sources._path(draft.profile, content.source.sha256, content.source.suffix)
    actual_stat = Path.stat
    def wrong_size(path, *args, **kwargs):
        result = actual_stat(path, *args, **kwargs)
        if path == original:
            values = list(result)
            values[6] = size
            return stat_result(values)
        return result
    monkeypatch.setattr(Path, "stat", wrong_size)
    assert not entry(draft, content).resolved


def test_native_text_and_spreadsheets_do_not_gain_image_resolution(included):
    draft, _, _ = included
    for name, raw in (("synthetic-notes.txt", b"Completed a synthetic inspection."),
                      ("synthetic-cmms.csv", b"Work order,Description\nDEMO-01,Inspected pump\n")):
        content, _ = sources.ingest(draft.profile, name, raw)
        source = replace(content.source, classification="Utility results", service_date="2026-09-04",
                         facility=draft.profile.facilities[0].key)
        content = replace(content, source=source)
        assert not entry(replace(draft, sources=(source,)), content).resolved


def test_pending_batch_and_duplicate_source_inventory_stay_open(included):
    draft, content, _ = included
    pending = entry(draft, content, pending=True)
    assert not pending.resolved  # Existing preflight safety is unchanged.
    assert not pending.needs_correction, "A global batch must not invent a correction for this file."
    assert "current file selection" in pending.reason
    assert entry(draft, content).resolved
    values = source_manager_status(draft, (content, content))
    assert len(values) == 1 and not values[0].resolved


def test_display_does_not_read_bytes_render_write_cache_or_call_readers(included, monkeypatch):
    from app import monthly_report_library as library, monthly_report_ai as ai, receipt_jobs
    draft, content, _ = included
    original_draft, original_content = draft, content
    def forbidden(*args, **kwargs):
        pytest.fail("Source disclosure must only inspect facts and bounded original stat.")
    for module, name in ((sources, "source_bytes"), (sources, "page_image"),
                         (library, "_atomic_write"), (library, "read_asset"),
                         (ai, "cached"), (ai, "save_cache"), (ai, "reserve_call"),
                         (receipt_jobs, "start_receipt")):
        monkeypatch.setattr(module, name, forbidden)
    assert entry(draft, content).resolved
    assert (draft, content) == (original_draft, original_content)


def test_display_cannot_create_uninitialized_qa_namespace(included, tmp_path):
    from app import monthly_report_testing as testing
    draft, content, _ = included
    before = set(tmp_path.rglob("*"))
    with testing.isolated("e" * 32):
        assert testing.generation() is None
        assert not entry(draft, content).resolved
        assert testing.generation() is None
    assert set(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("name,raw", [
    ("synthetic-reference.txt", b"Optional synthetic reference note."),
    ("synthetic-workorders.csv", b"Work order,Description\nDEMO-01,Inspected pump\n"),
])
def test_optional_text_and_spreadsheets_are_quiet_without_approving_them(included, name, raw):
    draft, _, _ = included
    content, _ = sources.ingest(draft.profile, name, raw)
    draft = replace(draft, sources=(content.source,))
    status = entry(draft, content)
    assert not status.resolved and not status.needs_correction
    assert status.reason == "" and status.summary == "Not included"
    assert status.source_id == content.source.id
    # A pending batch is one global blocking task, not a file-specific
    # correction. A genuinely missing original still needs its own recovery.
    pending = entry(draft, content, pending=True)
    assert not pending.resolved and not pending.needs_correction
    assert "current file selection" in pending.reason
    missing = entry(draft, content, unavailable=(content.source,))
    assert not missing.resolved and missing.needs_correction
    assert "original source file" in missing.reason


def test_specific_page_and_scope_problems_stay_actionable(included):
    draft, content, _ = included
    assert not entry(draft, content).needs_correction
    for changes in ({"service_date": ""}, {"facility": ""}, {"selected_pages": ()},
                    {"notices": ("Unreadable original artwork.",)}):
        changed, current = source_change(draft, content, **changes)
        status = entry(changed, current)
        assert not status.resolved and status.needs_correction


@pytest.mark.parametrize("classification", ["Reference only", "Utility results"])
def test_reading_notice_is_actionable_even_for_optional_text(included, classification):
    draft, _, _ = included
    content, _ = sources.ingest(draft.profile, "synthetic-notes.txt", b"Synthetic reference note.")
    source = replace(content.source, classification=classification,
                     notices=("Some original artwork could not be read.",))
    content = replace(content, source=source)
    status = entry(replace(draft, sources=(source,)), content)
    assert not status.resolved and status.needs_correction
    assert "reading notices" in status.reason
