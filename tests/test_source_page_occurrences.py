"""Real synthetic PDF intake and per-occurrence image ownership contracts."""
from dataclasses import replace
from datetime import date

import fitz
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_asset_review import approve_all_assets, asset_context, pending_asset_indexes
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_setup import merge_report_block
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_retirement import retire_contributions


def source_page(monkeypatch, tmp_path, *, variant="A", caption="Reviewed sample diagram", destination="improvements"):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = synthetic_profiles()[0]
    with fitz.open() as doc:
        page = doc.new_page(width=360, height=480)
        page.insert_text((36, 48), "Demonstration North Facility")
        page.insert_text((36, 74), "Utility results for October 2026")
        page.insert_text((36, 100), "Meter reading: 3240 gallons. Synthetic data.")
        doc.set_metadata({"title": "Synthetic source variant " + variant})
        raw = doc.tobytes()
    content, _ = sources.ingest(profile, "synthetic-utility-" + variant + ".pdf", raw)
    source = correct_source_details(content.source, profile, date(2026, 10, 11), "north")
    source = replace(source, captions=((1, caption),), selected_pages=(1,))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    content = replace(content, source=source)
    block, = sources.prepare_pages(profile, (content,), ((source.id, destination),))
    return profile, content, block


def corrected_page(profile, content, *, caption):
    source = replace(content.source, captions=((1, caption),))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    changed = replace(content, source=source)
    block, = sources.prepare_pages(profile, (changed,), ((source.id, "improvements"),))
    return changed, block


@pytest.mark.parametrize("human_first", (True, False))
def test_equal_bytes_human_and_imported_occurrences_survive_merge_then_retire(monkeypatch, tmp_path, human_first):
    profile, content, imported = source_page(monkeypatch, tmp_path)
    human = approve_all_assets(ResolvedBlock(imported.key, "This month", text="Independent maintenance note.",
        asset_hashes=imported.asset_hashes, asset_captions=("Independent operator photograph",),
        asset_provenance=((imported.asset_hashes[0], ()),)))
    first, second = (human, imported) if human_first else (imported, human)
    combined = merge_report_block(first, second, None, None)
    assert len(combined.asset_hashes) == 2, "Equal bytes do not make two independently owned occurrences one image."
    assert set(combined.asset_captions) == {human.asset_captions[0], imported.asset_captions[0]}
    assert not asset_context(combined, combined.asset_captions.index(human.asset_captions[0]))
    removed = retire_contributions(combined, (imported,))
    assert removed.asset_hashes == human.asset_hashes
    assert removed.asset_captions == human.asset_captions
    assert removed.text == human.text
    assert not pending_asset_indexes(removed), "An unrelated source retirement must keep the human image review."
    assert retire_contributions(removed, (imported,)) == removed


def test_equal_rasters_from_different_real_sources_remain_distinct_and_retire_by_source(monkeypatch, tmp_path):
    profile, first_content, first = source_page(monkeypatch, tmp_path, variant="A", caption="First original")
    _, second_content, second = source_page(monkeypatch, tmp_path, variant="B", caption="Second original")
    assert first_content.source.id != second_content.source.id
    assert first.asset_hashes == second.asset_hashes, "Metadata variants must rasterize to the same test image."
    combined = merge_report_block(first, second, None, None)
    assert combined.asset_captions == ("First original", "Second original")
    remaining = retire_contributions(combined, (first,))
    assert remaining.asset_captions == ("Second original",)
    assert second_content.source.id in {ref.split(":")[0] for ref in asset_context(remaining, 0)}
    assert first_content.source.id not in {ref.split(":")[0] for ref in asset_context(remaining, 0)}


@pytest.mark.parametrize("caption", ("Corrected source meter caption", ""))
def test_same_source_caption_correction_updates_one_existing_occurrence(monkeypatch, tmp_path, caption):
    profile, content, original = source_page(monkeypatch, tmp_path)
    changed, incoming = corrected_page(profile, content, caption=caption)
    merged = merge_report_block(original, incoming, None, None)
    assert merged.asset_hashes == original.asset_hashes
    assert merged.asset_captions == (caption,)
    assert not pending_asset_indexes(merged, (changed.source,))
    repeated = merge_report_block(merged, incoming, None, None)
    assert repeated == merged


def test_independent_human_caption_requires_visible_conflict_instead_of_overwrite(monkeypatch, tmp_path):
    profile, content, original = source_page(monkeypatch, tmp_path)
    human = replace(original, asset_captions=("Deliberately corrected report-only wording",))
    changed, incoming = corrected_page(profile, content, caption="Different source caption")
    with pytest.raises(ValueError, match="caption"):
        merge_report_block(human, incoming, None, None)
    assert human.asset_captions == ("Deliberately corrected report-only wording",)
    assert dict(changed.source.captions)[1] == "Different source caption"


def test_readded_instance_survives_old_retirement_after_save_reload(monkeypatch, tmp_path):
    profile, content, original = source_page(monkeypatch, tmp_path)
    # The later explicit Include is a new occurrence even though its original
    # source, bytes and caption have not changed. Existing merges remain idempotent.
    readded, = sources.prepare_pages(profile, (content,), ((content.source.id, "improvements"),))
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Reviewer", default_sections(), (readded,), sources=(content.source,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    loaded = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert loaded == saved
    assert retire_contributions(loaded.draft.blocks[0], (original,)) == loaded.draft.blocks[0], "A stale retirement cannot own a newer explicit inclusion."


def test_omission_preserves_source_and_human_occurrences(monkeypatch, tmp_path):
    _, _, original = source_page(monkeypatch, tmp_path)
    omitted = replace(original, source="Omit")
    assert retire_contributions(omitted, (original,)) == omitted
