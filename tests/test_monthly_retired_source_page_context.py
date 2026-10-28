"""Retiring a legacy source page preserves distinct page review context.

Synthetic source IDs and image refs only; never use or modify client documents.
Refs #282 and #270.
"""
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from app import monthly_report_library as library
from app.monthly_report_asset_instances import valid_instances
from app.monthly_report_asset_review import asset_context, pending_asset_indexes
from app.monthly_report_model import (
    AssetInstance, ReportDraft, ReportPeriod, ResolvedBlock, default_sections,
    synthetic_profiles,
)
from app.monthly_report_source_retirement import (
    _detached, retire_contributions, resolve_legacy_retirement, retirement_pending,
)


SOURCE = "a" * 64
OTHER = "b" * 64


def reference(source, page):
    return f"{source}:{page}:source-revision"


def marker(source, page):
    return f"asset-source-context:v1:{source}:{page}:facts-revision"


def item(*refs):
    return AssetInstance("legacy:invented", "synthetic.png", tuple(refs))


def remaining(item, retired):
    return set(_detached(item, retired, token=("synthetic", "revision", "image")).references)


@pytest.mark.parametrize("retired_page", ["1", "01", "000001"])
def test_retiring_page_one_preserves_other_page_context_of_same_source(retired_page):
    original = item(reference(SOURCE, retired_page), marker(SOURCE, 1),
                    reference(SOURCE, 2), marker(SOURCE, 2))
    result = remaining(original, (reference(SOURCE, retired_page),))
    assert result == {reference(SOURCE, 2), marker(SOURCE, 2)}
    assert marker(SOURCE, 1) not in result
    assert original.references[1] == marker(SOURCE, 1)


@pytest.mark.parametrize("unrelated", [
    reference(SOURCE, "²"),
    reference(SOURCE, "not-page"),
    reference(SOURCE, "000000"),
    f"section-source-route:v1:water_reports:{SOURCE}:{OTHER}",
])
def test_non_page_receipt_cannot_detach_a_valid_context(unrelated):
    original = item(reference(SOURCE, 2), marker(SOURCE, 2))
    assert remaining(original, (unrelated,)) == set(original.references)


def test_two_deliberately_retired_pages_lose_their_respective_markers():
    original = item(reference(SOURCE, 1), marker(SOURCE, 1),
                    reference(SOURCE, 2), marker(SOURCE, 2))
    assert remaining(original, (reference(SOURCE, 1), reference(SOURCE, 2))) == set()


def test_retirement_of_source_one_preserves_second_sources_matching_page():
    original = item(reference(SOURCE, 1), marker(SOURCE, 1),
                    reference(OTHER, 1), marker(OTHER, 1))
    assert remaining(original, (reference(SOURCE, 1),)) == {
        reference(OTHER, 1), marker(OTHER, 1),
    }


def test_directly_owned_marker_is_removed_without_unlinking_another_page():
    original = item(reference(SOURCE, 1), marker(SOURCE, 1),
                    reference(SOURCE, 2), marker(SOURCE, 2))
    assert remaining(original, (marker(SOURCE, 1),)) == {
        reference(SOURCE, 1), reference(SOURCE, 2), marker(SOURCE, 2),
    }


def test_detached_incarnation_is_stable_without_editing_the_original():
    original = item(reference(SOURCE, 1), marker(SOURCE, 1),
                    reference(SOURCE, 2), marker(SOURCE, 2))
    token = ("water_reports", "accepted-fingerprint", "legacy:invented")
    first = _detached(original, (reference(SOURCE, 1),), token)
    assert first == _detached(original, (reference(SOURCE, 1),), token)
    assert first.key.startswith("detached:")
    assert original.references == (reference(SOURCE, 1), marker(SOURCE, 1),
                                   reference(SOURCE, 2), marker(SOURCE, 2))


def legacy_pair(asset="synthetic.png", *, ambiguous=False):
    first, second = reference(SOURCE, 1), reference(SOURCE, 2)
    first_marker, second_marker = marker(SOURCE, 1), marker(SOURCE, 2)
    accepted = ResolvedBlock(
        "water_reports", "This month", asset_hashes=(asset,),
        asset_captions=("Imported page one",), references=(first,),
        asset_provenance=((asset, (first, first_marker)),),
    )
    captions = ("Imported page one", "Imported page one" if ambiguous else "Retained page two")
    combined = ResolvedBlock(
        "water_reports", "This month", asset_hashes=(asset, asset),
        asset_captions=captions, references=(first, second),
        asset_provenance=((asset, (first, first_marker, second, second_marker)),),
    )
    return accepted, combined


def assert_page_two_only(block, asset):
    assert block.asset_hashes == (asset,)
    assert set(asset_context(block, 0)) == {reference(SOURCE, 2), marker(SOURCE, 2)}
    assert reference(SOURCE, 1) not in block.references
    assert valid_instances(block)
    # Retiring one page cannot silently approve another historical occurrence.
    assert pending_asset_indexes(block) == (0,)


def test_unique_legacy_caption_retirement_preserves_other_page_context():
    accepted, combined = legacy_pair()
    original_refs = combined.references
    result = retire_contributions(combined, (accepted,))
    assert_page_two_only(result, "synthetic.png")
    assert result.asset_captions == ("Retained page two",)
    assert combined.references == original_refs
    assert retire_contributions(result, (accepted,)) == result
    assert not retirement_pending(result, accepted)


def test_explicit_ambiguous_page_selection_retains_other_page_context():
    accepted, combined = legacy_pair(ambiguous=True)
    assert retire_contributions(combined, (accepted,)) == combined
    result = resolve_legacy_retirement(combined, accepted, 1)
    assert_page_two_only(result, "synthetic.png")
    assert result.asset_captions == ("Imported page one",)
    assert not retirement_pending(result, accepted)


def test_saved_retirement_reopens_with_remaining_context_and_unmodified_original(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    stream = BytesIO()
    Image.new("RGB", (40, 32), "navy").save(stream, format="PNG")
    raw = stream.getvalue()
    asset = library.asset_reference(raw, "png")
    accepted, combined = legacy_pair(asset)
    profile = synthetic_profiles()[0]
    period = ReportPeriod(2026, 10)
    original = ReportDraft(profile, period, "Synthetic Editor",
                           default_sections(), (combined,))
    saved = library.save_snapshot(original, expected_revision=0,
                                  assets=((asset, raw),), entered_editor="Synthetic Editor")
    retired = retire_contributions(saved.draft.blocks[0], (accepted,))
    next_draft = replace(saved.draft, blocks=(retired,))
    second = library.save_snapshot(next_draft, expected_revision=saved.revision,
                                   entered_editor="Synthetic Editor")
    assert library.load_snapshot(profile.contract, profile.key, period) == second
    assert_page_two_only(second.draft.blocks[0], asset)
    assert library.read_asset(profile.contract, profile.key, asset) == raw
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1) == saved
    assert saved.draft.blocks == (combined,)
