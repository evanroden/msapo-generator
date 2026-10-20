"""Legacy reimport keeps human captions without merging independent instances.

These are synthetic merge, serialization and shared-snapshot contracts. They do
not establish native input delivery, a served workflow or rendered output.
"""
from dataclasses import asdict, replace
from io import BytesIO

from PIL import Image
import pytest

from app import monthly_report_library as library
from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_model import (
    AssetInstance, ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles,
)
from app.monthly_report_setup import merge_blocks
from app.monthly_report_testing_ui import _hash_generation_part


@pytest.mark.parametrize("caption", ("Deliberate report-only caption", ""))
def test_legacy_reimport_keeps_deliberate_caption_once_after_save_reload(monkeypatch, tmp_path, caption):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    image = BytesIO()
    Image.new("RGB", (12, 18), (20, 80, 120)).save(image, format="PNG")
    raw = image.getvalue()
    asset = library.asset_reference(raw, "png")
    approved = ResolvedBlock("vendor_reports", "This month", asset_hashes=(asset,),
                             asset_captions=("Original source caption",))
    approved = replace(approved, client_reviewed_fingerprint=approved.fingerprint)
    edited = replace(approved, asset_captions=(caption,))
    incoming = replace(approved, source="Last month")

    merged = merge_blocks(edited, incoming)
    assert merged.asset_hashes == (asset,)
    assert merged.asset_captions == (caption,)
    assert merged.client_reviewed_fingerprint == ""
    assert pending_asset_indexes(merged) == (0,)
    assert merge_blocks(merged, incoming) == merged
    assert approved.asset_captions == ("Original source caption",)

    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10),
                        "Synthetic Reviewer", (), (merged,), synthetic=True)
    saved = library.save_snapshot(draft, expected_revision=0, assets=((asset, raw),),
                                  entered_editor=draft.prepared_by)
    loaded = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert loaded == saved and loaded.draft.fingerprint == draft.fingerprint
    assert merge_blocks(loaded.draft.blocks[0], incoming) == loaded.draft.blocks[0]


@pytest.mark.parametrize("explicit_first", (False, True))
def test_explicit_independent_occurrence_does_not_merge_with_legacy_equal_bytes(explicit_first):
    legacy = ResolvedBlock("improvements", "This month", asset_hashes=("same.png",),
                           asset_captions=("Existing legacy report picture",))
    explicit = with_asset_instances(
        replace(legacy, asset_captions=("New independent photograph",)),
        (new_asset_instance("same.png"),))
    first, incoming = (explicit, legacy) if explicit_first else (legacy, explicit)
    merged = merge_blocks(first, incoming)
    assert merged.asset_hashes == ("same.png", "same.png")
    assert set(merged.asset_captions) == {legacy.asset_captions[0], explicit.asset_captions[0]}
    assert len({item.key for item in merged.asset_instances}) == 2
    assert merge_blocks(merged, incoming) == merged


def test_ambiguous_legacy_equal_images_keep_saved_state_until_identified():
    saved = ResolvedBlock("improvements", "This month", asset_hashes=("same.png", "same.png"),
                          asset_captions=("First retained picture", "Second retained picture"))
    incoming = replace(saved, source="Last month", asset_hashes=("same.png",),
                       asset_captions=("Different caption without an occurrence identity",))
    before = asdict(saved)
    with pytest.raises(ValueError, match="occurrence|identify"):
        merge_blocks(saved, incoming)
    assert asdict(saved) == before


@pytest.mark.parametrize("captions", (("First picture", "Second picture"), ("Same caption", "Same caption")))
def test_legacy_incoming_pictures_are_not_deduplicated_against_each_other(captions):
    incoming = ResolvedBlock("improvements", "Last month", asset_hashes=("same.png", "same.png"),
                             asset_captions=captions)
    merged = merge_blocks(ResolvedBlock(incoming.key, "This month"), incoming)
    assert merged.asset_hashes == incoming.asset_hashes
    assert merged.asset_captions == captions
    assert len({item.key for item in merged.asset_instances}) == 2
    assert merge_blocks(merged, incoming) == merged
    assert merge_blocks(merged, replace(incoming, asset_captions=captions[::-1])) == merged


def test_occurrence_identity_changes_report_and_qa_digests():
    legacy = ResolvedBlock("improvements", "This month", asset_hashes=("same.png",),
                           asset_captions=("Same caption",))
    first = with_asset_instances(legacy, (AssetInstance("first-inclusion", "same.png"),))
    readded = with_asset_instances(legacy, (AssetInstance("later-inclusion", "same.png"),))
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10),
                        "Synthetic Reviewer", (), (first,), synthetic=True)
    assert first.fingerprint != readded.fingerprint
    assert draft.fingerprint != replace(draft, blocks=(readded,)).fingerprint
    assert _hash_generation_part(first) != _hash_generation_part(readded)
    assert library.draft_from_dict(asdict(draft)).fingerprint == draft.fingerprint
