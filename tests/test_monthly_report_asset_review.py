"""Per-picture review follows immutable content, not unrelated editor controls."""

from dataclasses import asdict, replace
import hashlib
import json

import pytest

from app.monthly_report_asset_review import (
    approve_all_assets, approve_asset, asset_fingerprint, asset_reviewed,
    normalize_asset_reviews, pending_asset_indexes, preserve_asset_reviews, refresh_asset_source_context,
)
from app.monthly_report_checks import preflight
from app.monthly_report_library import block_from_dict
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ReportTable, ResolvedBlock, SectionSpec,
    synthetic_profiles,
)
from app.monthly_report_setup import merge_blocks, new_month_draft


def pictures(**changes):
    return replace(ResolvedBlock(
        "equipment_issues", "This month", asset_hashes=("first.png", "second.png"),
        asset_captions=("Pump inspection", "Valve inspection"),
        references=("source-first:1:hash-first", "source-second:1:hash-second"),
    ), **changes)


def legacy(block):
    return replace(block, client_reviewed_fingerprint=block.fingerprint)


def report(block):
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Editor",
                       (SectionSpec("issues", "8", "Equipment issues", (BlockSpec(block.key, "rich_text"),)),),
                       (block,))


def test_historical_fingerprint_and_snapshot_are_preserved_during_migration():
    original = pictures()
    value = asdict(original)
    value.pop("client_asset_reviews")
    value.pop("asset_provenance")
    historical = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    value["client_reviewed_fingerprint"] = historical
    stored = json.dumps(value, sort_keys=True)
    loaded = block_from_dict(value)
    assert loaded.fingerprint == historical
    assert not pending_asset_indexes(loaded)
    assert loaded.asset_provenance == (
        ("first.png", ("source-first:1:hash-first",)),
        ("second.png", ("source-second:1:hash-second",)),
    )
    assert json.dumps(value, sort_keys=True) == stored


def test_stale_legacy_approval_cannot_migrate_after_content_has_changed():
    original = legacy(pictures())
    changed = replace(original, text="Changed before migration")
    assert pending_asset_indexes(normalize_asset_reviews(changed)) == (0, 1)
    assert original.client_asset_reviews == ()


@pytest.mark.parametrize("changes", [
    {"text": "New maintenance note"},
    {"rows": (("New table value",),)},
    {"extra_tables": (ReportTable(("Asset",), (("Pump",),), "new-table-source"),)},
    {"source": "Last month"},
    {"photos_per_page": 4},
])
def test_unrelated_edits_keep_both_picture_approvals(changes):
    original = legacy(pictures())
    edited = preserve_asset_reviews(original, replace(original, client_reviewed_fingerprint="", **changes))
    assert not pending_asset_indexes(edited)
    assert not original.client_asset_reviews  # immutable old snapshot


def test_caption_change_needs_only_that_picture_reviewed():
    original = approve_all_assets(pictures())
    changed = preserve_asset_reviews(original, replace(original, asset_captions=("Changed caption", "Valve inspection")))
    assert pending_asset_indexes(changed) == (0,)
    assert asset_reviewed(changed, 1)
    assert not pending_asset_indexes(approve_asset(changed, 0))


def test_new_and_replaced_images_do_not_borrow_approval():
    original = approve_all_assets(pictures())
    appended = preserve_asset_reviews(original, replace(original, asset_hashes=(*original.asset_hashes, "third.png")))
    assert pending_asset_indexes(appended) == (2,)
    replaced = preserve_asset_reviews(original, replace(original, asset_hashes=("new-first.png", "second.png")))
    assert pending_asset_indexes(replaced) == (0,)


def test_removal_and_reordering_preserve_exact_remaining_picture():
    original = legacy(pictures())
    removed = preserve_asset_reviews(original, replace(original, asset_hashes=("first.png",),
        asset_captions=("Pump inspection",), references=(original.references[0],), client_reviewed_fingerprint=""))
    assert not pending_asset_indexes(removed)
    original = normalize_asset_reviews(original)
    reordered = replace(original, asset_hashes=original.asset_hashes[::-1],
                        asset_captions=original.asset_captions[::-1], references=original.references[::-1])
    assert not pending_asset_indexes(reordered)


def test_only_changed_source_provenance_invalidates_review():
    original = approve_all_assets(pictures())
    added_text_source = replace(original, references=(*original.references, "new-table-source"))
    assert not pending_asset_indexes(added_text_source)
    changed = preserve_asset_reviews(original, replace(original,
        references=("replacement-source:1:other-hash", original.references[1]),
        asset_provenance=(("first.png", ("replacement-source:1:other-hash",)), original.asset_provenance[1])))
    assert pending_asset_indexes(changed) == (0,)


def test_compatibility_stamp_cannot_approve_changed_metadata_after_migration():
    original = approve_all_assets(pictures(references=("source-a", "source-b", "context-c")))
    changed = replace(original, asset_provenance=(("first.png", ("context-c",)), original.asset_provenance[1]))
    assert changed.client_reviewed_fingerprint == changed.fingerprint
    assert not asset_reviewed(changed, 0)
    assert asset_reviewed(changed, 1)
    assert not asset_reviewed(normalize_asset_reviews(changed), 0)


def test_approval_is_bound_to_destination_and_does_not_change_content_review():
    original = pictures(ai_written=True)
    original = replace(original, reviewed_fingerprint=original.fingerprint)
    reviewed = approve_all_assets(original)
    assert reviewed.fingerprint == original.fingerprint and reviewed.reviewed
    assert pending_asset_indexes(replace(reviewed, key="water_reports")) == (0, 1)


def test_mixed_legacy_block_does_not_guess_reference_alignment():
    original = normalize_asset_reviews(legacy(pictures(text="Source-linked monthly narrative")))
    assert dict(original.asset_provenance)["first.png"] == tuple(sorted(original.references))
    changed = replace(original, references=(original.references[0],))
    assert pending_asset_indexes(changed) == (0, 1)


def test_merge_preserves_reviewed_images_and_only_flags_new_or_new_context():
    original = approve_all_assets(pictures())
    new = ResolvedBlock(original.key, "This month", text="New note", asset_hashes=("third.png",),
                        asset_captions=("Third picture",), references=("third-source",))
    merged = merge_blocks(original, new)
    assert pending_asset_indexes(merged) == (2,)
    changed_context = ResolvedBlock(original.key, "This month", asset_hashes=("first.png",),
                                   asset_captions=("Pump inspection",), references=("new-origin",))
    merged = merge_blocks(original, changed_context)
    assert pending_asset_indexes(merged) == (0,)


def test_approved_incoming_pages_and_existing_pages_remain_independently_ready():
    original = legacy(pictures())
    incoming = approve_all_assets(ResolvedBlock(original.key, "This month", asset_hashes=("third.png",),
                                              asset_captions=("Third picture",), references=("third-source",)))
    merged = merge_blocks(original, incoming)
    assert not pending_asset_indexes(merged)
    assert asset_fingerprint(merged, 2) == asset_fingerprint(incoming, 0)


def test_next_month_keeps_reviews_of_carried_issue_pictures():
    prior = report(legacy(pictures()))
    following = new_month_draft(prior, ReportPeriod(2026, 10))
    assert following.blocks[0].asset_hashes == prior.blocks[0].asset_hashes
    assert not pending_asset_indexes(following.blocks[0])
    assert not prior.blocks[0].client_asset_reviews


def test_preflight_counts_only_pending_pictures_and_keeps_pricing_gate():
    original = approve_all_assets(pictures(references=("first-origin", "second-origin")))
    changed = replace(original, asset_captions=("Pump cost $123", "Valve inspection"))
    checks = preflight(report(changed))
    assert len([check for check in checks if check.code == "client_pages"]) == 1
    assert "1 new or changed picture" in next(check.message for check in checks if check.code == "client_pages")
    approved = approve_asset(changed, 0)
    assert not any(check.code == "client_pages" for check in preflight(report(approved)))
    assert any(check.code == "pricing" for check in preflight(report(approved)))


def source_page():
    from app.monthly_report_sources import source_reference
    source = ReportSource("synthetic-source", "synthetic.pdf", "a" * 64, ".pdf",
                          vendor="Synthetic vendor", facility="Synthetic site", service_date="2026-09-12",
                          work_order="WO-101", page_texts=("First technical page", "Second technical page"),
                          captions=((1, "Pump inspection"), (2, "Valve inspection")))
    block = ResolvedBlock("equipment_issues", "This month", asset_hashes=("first.png",),
                          asset_captions=("Pump inspection",), references=(source_reference(source, 1),))
    return source, block


def test_noop_merge_imports_independently_reviewed_page_approval():
    original = pictures()
    incoming = approve_all_assets(original)
    merged = merge_blocks(original, incoming)
    assert not pending_asset_indexes(merged)


def test_current_legacy_source_context_migrates_without_reviewing_again():
    source, block = source_page()
    original = legacy(block)
    refreshed = refresh_asset_source_context(original, (source,))
    assert not pending_asset_indexes(refreshed, (source,))
    assert any(r.startswith("asset-source-context:v1:") for r in dict(refreshed.asset_provenance)["first.png"])
    assert not original.client_asset_reviews


@pytest.mark.parametrize("changes", [
    {"vendor": "Different vendor"}, {"facility": "Different facility"},
    {"service_date": "2026-08-12"}, {"work_order": "WO-102"}, {"sha256": "b" * 64},
    {"page_texts": ("Changed first page", "Second technical page")},
    {"captions": ((1, "Changed caption"), (2, "Valve inspection"))},
])
def test_source_context_edits_invalidate_only_relevant_approvals(changes):
    source, block = source_page()
    reviewed = approve_all_assets(refresh_asset_source_context(block, (source,)))
    changed = replace(source, **changes)
    assert pending_asset_indexes(reviewed, (changed,)) == (0,)
    # Preflight independently recomputes context even if no UI has rerun.
    current_report = replace(report(reviewed), sources=(changed,))
    assert any(check.code == "client_pages" for check in preflight(current_report))


def test_other_page_changes_and_review_toggles_do_not_reset_unchanged_page():
    source, block = source_page()
    reviewed = approve_all_assets(refresh_asset_source_context(block, (source,)))
    changed = replace(source, page_texts=(source.page_texts[0], "Changed second page"),
                      captions=((1, "Pump inspection"), (2, "New second caption")),
                      selected_pages=(1, 2), client_page_reviews=((2, "new-review"),))
    assert not pending_asset_indexes(reviewed, (changed,))
    # Re-preparing the same page can emit a new full-source reference because
    # another page was changed. Its targeted source context is still identical.
    from app.monthly_report_sources import source_reference
    incoming = replace(block, references=(source_reference(changed, 1),))
    incoming = refresh_asset_source_context(incoming, (changed,))
    merged = merge_blocks(reviewed, incoming)
    assert not pending_asset_indexes(merged, (changed,))


def test_stale_legacy_source_and_missing_source_require_new_review():
    source, block = source_page()
    original = legacy(block)
    changed = replace(source, vendor="Different vendor")
    assert pending_asset_indexes(original, (changed,)) == (0,)
    assert pending_asset_indexes(original, ()) == (0,)
    missing = approve_all_assets(refresh_asset_source_context(original, ()))
    assert pending_asset_indexes(missing, ()) == (0,)
