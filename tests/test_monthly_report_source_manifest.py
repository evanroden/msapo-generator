"""A54: synthetic no-silent-loss source-to-report manifest canaries.

No paid model, client original or live deployment is involved.
"""
from collections import Counter
from dataclasses import asdict, replace

import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, EvidenceFact, ReportDraft, ReportPeriod,
    ReportSource, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_source_manifest import (
    ACTIONABLE, report_manifest, report_manifest_counts, source_manifest,
)
from app.monthly_report_source_scope import contribution_receipt


PERIOD = ReportPeriod(2026, 9)
PROFILE = synthetic_profiles()[0]


def source(*, sha="a" * 64, suffix=".pdf", texts=(), **kwargs):
    return ReportSource("synthetic54", "synthetic-original" + suffix, sha, suffix,
        classification="Vendor service", facility=PROFILE.facilities[0].key,
        service_date="2026-09-07", page_texts=tuple(texts), **kwargs)


def draft_for(item, block=None, *, section=None, period=PERIOD):
    block = block or ResolvedBlock("activity_summary", "Human", text="")
    section = section or SectionSpec("activity", "2", "Monthly Activity",
        (BlockSpec(block.key, "rich_text"),))
    return ReportDraft(PROFILE, period, "Synthetic reviewer", (section,),
                       (block,), sources=(item,), synthetic=True)


def indexed(ledger):
    keys = [item.key for item in ledger.items]
    assert len(keys) == len(set(keys)), "Each source occurrence must be counted once"
    return {item.key: item for item in ledger.items}


def test_policy_exclusions_and_scan_are_visible_without_fabricating_approval():
    pages = (
        "Inspected a synthetic compressor and recorded vibration.",
        "Quotation: unit price $1,200",
        "Terms and conditions include limitation of liability and governing law.",
        "",
    )
    original = source(texts=pages, needs_vision=(4,),
        notices=("Item 4: Native Word drawing could not be read.",))
    draft = draft_for(original)
    manifest = source_manifest(draft, original, sources.SourceContent(original))
    items = indexed(manifest)
    assert items["page:1"].status == "included"
    assert items["page:2"].status == "excluded" and "policy" in items["page:2"].reason.lower()
    assert items["page:3"].status == "excluded" and "legal" in items["page:3"].reason.lower()
    assert items["page:4"].status == "unreadable"
    assert "photo:4" not in items, "PDF page image is not an extra physical source item"
    assert items["notice:1"].status == "blocked"
    assert items["notice:1"].kind == "drawing_or_notice"
    assert all(item.source_hash == original.sha256 for item in items.values())
    assert manifest.report_period == "2026-09"
    counts = report_manifest_counts((manifest,))
    assert counts["items"] == len(items)
    assert counts["sources_with_tasks"] == 1
    assert counts["excluded"] == 2 and counts["unreadable"] == 1
    assert sum(manifest.counts.values()) == len(items)


def test_one_deliberately_omitted_page_is_bound_to_current_source_revision():
    from app.monthly_report_content_policy import page_fingerprint
    original = source(texts=("Synthetic vendor inspection", "Quote price $900"))
    omitted = replace(original, client_page_exclusions=((1, page_fingerprint(original, 1)),))
    manifest = source_manifest(draft_for(omitted), omitted, sources.SourceContent(omitted))
    assert indexed(manifest)["page:1"].status == "excluded"
    assert "Deliberately" in indexed(manifest)["page:1"].reason
    changed = replace(omitted, page_texts=("Synthetic vendor inspection changed", "Quote price $900"))
    stale = source_manifest(draft_for(changed), changed, sources.SourceContent(changed))
    assert indexed(stale)["page:1"].status == "blocked", "A stale exclusion must not approve replacement"


def test_exact_reviewed_text_current_and_after_reload_stale_month_and_replacement():
    from app.monthly_report_ai import evidence_fingerprint, reviewed_block
    text = "Inspected synthetic chiller and documented normal operation."
    original = source(suffix=".txt", texts=(text,))
    ref = sources.source_reference(original, 1)
    block = ResolvedBlock("activity_summary", "Human", text=text, references=(ref,),
        ai_written=True, ai_evidence_fingerprint=evidence_fingerprint((original,), (ref,)))
    block = reviewed_block(block, (original,))
    draft = draft_for(original, block)
    content = sources.SourceContent(original)
    accepted = source_manifest(draft, original, content)
    assert indexed(accepted)["page:1"].status == "extracted"
    assert indexed(accepted)["page:1"].section == "Monthly Activity"
    restored = library.draft_from_dict(asdict(draft))
    assert source_manifest(restored, restored.sources[0],
        replace(content, source=restored.sources[0])) == accepted
    changed_month = replace(draft, period=ReportPeriod(2026, 10))
    assert indexed(source_manifest(changed_month, original, content))["page:1"].status == "included"
    changed_original = replace(original, sha256="b" * 64, page_texts=(text + " Updated.",))
    replaced = replace(draft, sources=(changed_original,))
    result = indexed(source_manifest(replaced, changed_original,
        sources.SourceContent(changed_original)))
    assert result["page:1"].status != "extracted"
    assert result["page:1"].source_hash == changed_original.sha256
    assert indexed(source_manifest(replaced, changed_original, content))["source:replaced"].status == "blocked"


def test_accepted_one_duplicate_row_does_not_claim_second_occurrence():
    original = source(suffix=".csv", texts=("Work order,Task\n001,Synthetic inspection",))
    table = sources.SourceTable("synthetic CSV", ("Work order", "Task"),
        (("001", "Synthetic inspection"), ("001", "Synthetic inspection")))
    ref = sources.source_reference(original, 1)
    first = (("001", "Synthetic inspection"),)
    receipt = contribution_receipt(ref, PROFILE, PERIOD, "activity_summary",
        columns=table.columns, rows=first, source=original)
    block = ResolvedBlock("activity_summary", "Human", rows=first,
        references=(ref, receipt))
    section = SectionSpec("activity", "2", "Monthly Activity",
        (BlockSpec("activity_summary", "table",
            columns=(ColumnSpec("wo", "Work order"), ColumnSpec("task", "Task"))),))
    draft = draft_for(original, block, section=section)
    manifest = source_manifest(draft, original, sources.SourceContent(original, (table,)))
    states = indexed(manifest)
    assert states["table:1:row:1"].status == "extracted"
    assert states["table:1:row:2"].status == "included"
    assert states["table:1"].status == "included"
    assert len([x for x in manifest.items if x.kind == "row"]) == 2
    assert report_manifest_counts((manifest,))["extracted"] == 1


def test_missing_unsupported_and_duplicate_cache_do_not_report_zero_work():
    original = source(suffix=".xlsx", texts=("Synthetic stored cells",))
    draft = draft_for(original)
    missing = indexed(source_manifest(draft, original, None))
    assert missing["source:unavailable"].status == "blocked"
    assert missing["tables:unknown"].status == "blocked"
    candidate = sources.SourceContent(original)
    assert indexed(report_manifest(draft, (candidate, candidate))[0])["source:unavailable"].status == "blocked"
    mismatched = replace(original, id="other-original")
    assert indexed(source_manifest(draft, original, sources.SourceContent(mismatched)))["source:replaced"].status == "blocked"
    unsupported = replace(original, suffix=".bin")
    assert indexed(source_manifest(draft_for(unsupported), unsupported,
        sources.SourceContent(unsupported)))["source:unsupported"].status == "blocked"


def test_manifest_does_not_mutate_report_or_read_original_or_trigger_paid_work(monkeypatch):
    from app import monthly_report_ai as ai
    original = source(suffix=".txt", texts=("Synthetic technical details",))
    draft = draft_for(original)
    original_draft = asdict(draft)
    def forbidden(*args, **kwargs):
        pytest.fail("Audit must not read originals, use paid AI or save shared records.")
    for module, name in ((sources, "source_bytes"), (sources, "page_image"),
                         (library, "_atomic_write"), (ai, "reserve_call")):
        monkeypatch.setattr(module, name, forbidden)
    manifest = source_manifest(draft, original, sources.SourceContent(original))
    assert indexed(manifest)["page:1"].status == "included"
    assert asdict(draft) == original_draft
    assert report_manifest_counts(report_manifest(draft, (sources.SourceContent(original),)))["sources"] == 1


def test_actionable_entries_have_current_source_and_native_review_targets():
    original = source(suffix=".txt", texts=("Synthetic inspected pump.",))
    manifest = source_manifest(draft_for(original), original, sources.SourceContent(original))
    assert manifest.pending
    assert all(item.status in ACTIONABLE and item.source_id == original.id for item in manifest.pending)
    assert manifest.pending[0].page == 1


def test_real_synthetic_csv_inspection_roundtrip_keeps_original_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original_bytes = (
        b"Work Order,Task\n"
        b"001,Synthetic inspected pump\n"
        b"001,Synthetic inspected pump\n"
    )
    content, children = sources.ingest(PROFILE, "a54-public-synthetic.csv", original_bytes)
    assert not children
    draft = draft_for(content.source)
    before = source_manifest(draft, content.source, content)
    assert len([item for item in before.items if item.kind == "row"]) == 2
    assert sources.source_bytes(PROFILE, content.source) == original_bytes
    restored = library.draft_from_dict(asdict(draft))
    warm, _ = sources.ingest(PROFILE, "a54-public-synthetic.csv", original_bytes)
    after = source_manifest(restored, restored.sources[0],
        replace(warm, source=restored.sources[0]))
    assert before == after
    assert sources.source_bytes(PROFILE, content.source) == original_bytes


def test_native_app_source_coverage_routes_only_an_actionable_item(monkeypatch, tmp_path):
    from test_monthly_report_source_manager_compact import resolved_app
    from test_monthly_report_upload_ui import button, current_draft
    app = resolved_app(monkeypatch, tmp_path)
    key = next(key for key, value in app.session_state.filtered_state.items()
               if key.startswith("report_guided_") and key.endswith("_draft")
               and hasattr(value, "blocks"))
    draft = current_draft(app)
    removed = tuple(replace(block, asset_hashes=(), asset_captions=(),
                            asset_provenance=()) if block.key == "utility_analysis"
                    else block for block in draft.blocks)
    app.session_state[key] = replace(draft, blocks=removed)
    app.run()
    button(app, "Review source-content coverage").click().run()
    assert not app.exception
    assert any("Source coverage" in caption.value for caption in app.caption)
    assert any(widget.label == "Source-content item" for widget in app.selectbox)
    button(app, "Open original item for correction").click().run()
    assert not app.exception
    assert button(app, "Done with source files")
    assert not next(block for block in current_draft(app).blocks
                    if block.key == "utility_analysis").asset_hashes


def test_duplicate_draft_identity_is_reported_once_but_blocked():
    original = source(suffix=".txt", texts=("Synthetic technical note",))
    draft = replace(draft_for(original), sources=(original, original))
    manifests = report_manifest(draft, (sources.SourceContent(original),))
    assert len(manifests) == 1
    items = indexed(manifests[0])
    assert items["source:duplicate"].status == "blocked"
    assert report_manifest_counts(manifests)["sources"] == 1


def test_malformed_cached_table_is_blocked_without_fake_accepted_rows():
    original = source(suffix=".csv", texts=("Synthetic CSV",))
    malformed = sources.SourceTable("synthetic malformed", ("ID", "Status"),
        (("one-cell",),))
    manifest = source_manifest(draft_for(original), original,
        sources.SourceContent(original, (malformed,)))
    items = indexed(manifest)
    assert items["table:1:malformed"].status == "blocked"
    assert not any(item.status == "extracted" for item in manifest.items)
