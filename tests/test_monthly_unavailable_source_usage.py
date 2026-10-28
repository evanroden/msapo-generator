"""Synthetic original-source availability follows actual output provenance.

A mentioned hash, old route or removed section is not proof of a dependency.
AI-only paragraphs and valid picture occurrences remain protected. Refs #302.
"""
from dataclasses import asdict, replace

import pytest

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_model import (
    AssetInstance, DraftParagraph, ReportDraft, ReportFollowUp, ReportPeriod,
    ReportSource, ReportTable, ResolvedBlock, default_sections, synthetic_profiles,
    used_source_ids,
)
from app.monthly_report_source_recovery import used_missing_sources


MISSING = ReportSource("a" * 64, "unavailable-source.pdf", "b" * 64, ".pdf")
SIBLING = ReportSource("c" * 64, "unrelated-source.pdf", "d" * 64, ".pdf")
PAGE_REF = f"{MISSING.id}:1:source-fingerprint"
ROUTE = f"section-source-route:v1:water_reports:{MISSING.id}:{MISSING.sha256}"
IMAGE = "f" * 64 + ".png"


def report(*blocks, sections=None, follow_ups=(), sources=()):
    return ReportDraft(
        synthetic_profiles()[0], ReportPeriod(2026, 10), "Synthetic Editor",
        sections if sections is not None else default_sections(), tuple(blocks),
        sources=tuple(sources), follow_ups=tuple(follow_ups),
    )


def needed(draft):
    return used_missing_sources(draft, (MISSING, SIBLING))


@pytest.mark.parametrize("block", [
    ResolvedBlock("activity_summary", "This month", text=f"Author note {MISSING.id}"),
    ResolvedBlock("activity_summary", "This month", text=f"Reader reminder {MISSING.id}."),
    ResolvedBlock("activity_summary", "This month", text="Approved work", references=(ROUTE,)),
    ResolvedBlock("water_reports", "This month", asset_hashes=(MISSING.id + ".png",)),
    ResolvedBlock("water_reports", "This month", asset_hashes=(IMAGE,), asset_captions=(MISSING.id,)),
    ResolvedBlock("activity_summary", "This month", text="Reviewed note",
                  references=(f"asset-source-context:v1:{MISSING.id}:1:marker",)),
    ResolvedBlock("activity_summary", "This month", text="", references=(PAGE_REF,)),
    ResolvedBlock("activity_summary", "This month", extra_tables=(
        ReportTable(("Status",), (("",),), PAGE_REF),)),
])
def test_inactive_or_human_text_id_does_not_block_recovery(block):
    draft = report(block, sources=(MISSING,))
    before = asdict(draft)
    assert needed(draft) == ()
    assert used_source_ids(draft) == set()
    assert asdict(draft) == before


@pytest.mark.parametrize("block", [
    ResolvedBlock("activity_summary", "This month", text="Completed reviewed maintenance",
                  references=(PAGE_REF,)),
    ResolvedBlock("activity_summary", "This month", rows=(("Work order 1",),),
                  references=(PAGE_REF,)),
    ResolvedBlock("activity_summary", "This month", extra_tables=(
        ReportTable(("Reference",), (("Output row",),), PAGE_REF),)),
    ResolvedBlock("activity_summary", "This month", ai_paragraphs=(
        DraftParagraph("Verified equipment finding", (), (PAGE_REF,)),)),
    ResolvedBlock("water_reports", "This month", asset_hashes=(IMAGE,),
                  asset_provenance=((IMAGE, (PAGE_REF,)),)),
    ResolvedBlock("water_reports", "This month", asset_hashes=(IMAGE,),
                  asset_instances=(AssetInstance("occurrence-1", IMAGE, (PAGE_REF,)),)),
])
def test_live_output_provenance_keeps_missing_original_required(block):
    draft = report(block, sources=(MISSING,))
    assert needed(draft) == (MISSING,)
    assert used_source_ids(draft) == {MISSING.id}
    # This should also block a direct generation path if its entire source
    # inventory was lost; merely dropping the record cannot approve output.
    unbound = replace(draft, sources=())
    assert any(check.code == "source_missing" and check.blocking
               for check in preflight(unbound))


def test_omitted_and_excluded_content_does_not_block_source_removal():
    block = ResolvedBlock("activity_summary", "Omit",
                          text="Previously sourced", references=(PAGE_REF,))
    assert needed(report(block, sources=(MISSING,))) == ()
    inactive = tuple(replace(section, included=False) if section.key == "activity"
                     else section for section in default_sections())
    linked = replace(block, source="This month")
    assert needed(report(linked, sections=inactive, sources=(MISSING,))) == ()


@pytest.mark.parametrize("included", [True, False])
def test_only_current_included_followup_citations_require_original(included):
    item = ReportFollowUp("synthetic-item", "issue", f"Note {MISSING.id}", "2026-09",
                          evidence_note=f"Unlinked ID {MISSING.id}",
                          references=(PAGE_REF,), included=included)
    draft = report(follow_ups=(item,), sources=(MISSING,))
    assert needed(draft) == ((MISSING,) if included else ())
    assert asdict(draft.follow_ups[0]) == asdict(item)


def test_stale_image_occurrence_and_provenance_for_other_bytes_are_not_evidence():
    mismatched = ResolvedBlock(
        "water_reports", "This month", asset_hashes=(IMAGE,),
        asset_provenance=(("e" * 64 + ".png", (PAGE_REF,)),),
        asset_instances=(AssetInstance("stale", "e" * 64 + ".png", (PAGE_REF,)),),
    )
    draft = report(mismatched, sources=(MISSING,))
    assert needed(draft) == ()
    assert used_source_ids(draft) == set()


def test_other_missing_siblings_remain_selectively_available_for_removal():
    block = ResolvedBlock("activity_summary", "This month",
                          text="Reviewed", references=(PAGE_REF,))
    assert needed(report(block, sources=(MISSING, SIBLING))) == (MISSING,)
    assert needed(report(block, sources=())) == (MISSING,)


def test_durable_snapshot_keeps_source_and_report_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    block = ResolvedBlock("activity_summary", "This month",
                          text=f"Authored reminder {MISSING.id}")
    draft = report(block, sources=(MISSING,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    assert needed(saved.draft) == ()
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened.draft == draft
    assert reopened.draft.sources == (MISSING,)
    assert needed(reopened.draft) == ()
    assert reopened.revision == saved.revision
