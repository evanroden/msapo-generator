"""Retire actual imported occurrences after a deliberate report-picture reorder."""
from dataclasses import replace

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_asset_instances import asset_instances, with_asset_instances
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections
from app.monthly_report_setup import merge_report_block
from app.monthly_report_source_retirement import retire_contributions
from test_source_page_occurrences import source_page


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0), (1, 0, 2)])
def test_multi_page_retirement_respects_current_order_and_keeps_equal_human_photo(
        monkeypatch, tmp_path, order):
    profile, first_content, first = source_page(monkeypatch, tmp_path, variant="reorder-A", caption="First imported page")
    _, second_content, second = source_page(monkeypatch, tmp_path, variant="reorder-B", caption="Second imported page")
    assert first_content.source.id != second_content.source.id
    assert first.asset_hashes == second.asset_hashes
    originals = tuple(sources.source_bytes(profile, content.source) for content in (first_content, second_content))
    accepted = merge_report_block(first, second, None, None)
    human = approve_all_assets(ResolvedBlock(first.key, "This month", text="Independent operator finding.",
        asset_hashes=first.asset_hashes, asset_captions=("Independent human photograph",),
        asset_provenance=((first.asset_hashes[0], ()),)))
    combined = merge_report_block(accepted, human, None, None)
    instances = asset_instances(combined)
    ordered = with_asset_instances(replace(combined,
        asset_hashes=tuple(combined.asset_hashes[index] for index in order),
        asset_captions=tuple(combined.asset_captions[index] for index in order)),
        tuple(instances[index] for index in order))
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Reorder Reviewer", default_sections(),
                        (ordered,), sources=(first_content.source, second_content.source))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    reloaded = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reloaded == saved and reloaded.draft.blocks[0].asset_captions == ordered.asset_captions
    remaining = retire_contributions(reloaded.draft.blocks[0], (accepted,))
    assert remaining.asset_captions == human.asset_captions, (
        "Removal indexes must follow the current report order, without shifting a later owned occurrence "
        "or deleting the independent equal-byte photo.")
    assert remaining.asset_hashes == human.asset_hashes and remaining.text == human.text
    assert not asset_instances(remaining)[0].references
    after = library.save_snapshot(replace(draft, blocks=(remaining,)), expected_revision=saved.revision,
                                  entered_editor=draft.prepared_by)
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == after
    assert retire_contributions(remaining, (accepted,)) == remaining
    assert tuple(sources.source_bytes(profile, content.source)
                 for content in (first_content, second_content)) == originals
