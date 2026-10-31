"""Invalid page numerals never become accepted Monthly source-scope citations.

Synthetic records only. Original source bytes and historical snapshots remain
independent of this lexical source/page predicate. Refs #298 and #270.
"""
from dataclasses import asdict, replace

import pytest

from app import monthly_report_library as library
from app.monthly_report_model import (
    BlockSpec, DraftParagraph, ReportDraft, ReportFollowUp, ReportPeriod,
    ReportSource, ReportTable, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_source_scope import (
    USE_PREFIX, _source_id, contribution_receipt, correct_scope,
    included_scope_valid, reviewed_scope, source_uses,
)


SOURCE_ID = "a" * 64
SHA = "b" * 64
TEXT = "Synthetic maintenance report: inspected air handling equipment."
PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 10)
SOURCE = ReportSource(SOURCE_ID, "synthetic-site.txt", SHA, ".txt",
                      service_date="2026-10-08", page_texts=(TEXT,))
SECTIONS = (SectionSpec("activity", "2", "Activity",
                        (BlockSpec("activity_summary", "rich_text"),)),)


def source_ref(number, *, source_id=SOURCE_ID, revision=None):
    return f"{source_id}:{number}:{revision or SOURCE.fingerprint}"


def draft_for(*blocks, sources=(SOURCE,), follow_ups=()):
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor", SECTIONS, tuple(blocks),
                       sources=tuple(sources), follow_ups=tuple(follow_ups))


@pytest.mark.parametrize("page", ["1", "2", "001", "000001", "500", "999999"])
def test_existing_ascii_source_refs_preserve_identity(page):
    assert _source_id(source_ref(page)) == SOURCE_ID


@pytest.mark.parametrize("page", [
    "0", "000", "000000", "-1", "+1", "", "1.0", "²", "①",
    "٥", "٣١", "９", "１", "1\u200b", " 1", "1 ", "1234567",
    "1" * 4301, "9" * 10000, "١" * 7,
])
def test_malformed_unicode_zero_and_unbounded_page_tokens_fail_closed(page):
    assert _source_id(source_ref(page)) is None


@pytest.mark.parametrize("reference", [
    None, 42, {}, (), "", "not-a-source",
    f"{SOURCE_ID}:1", f"{SOURCE_ID}:1:{SHA}:extra",
    ":1:revision", f"{SOURCE_ID}:1:",
    "source-scope-use:v1:encoded-record",
])
def test_unrelated_metadata_cannot_be_a_page_identity(reference):
    assert _source_id(reference) is None


@pytest.mark.parametrize("page", [
    "0", "000000", "²", "①", "٥", "９", "1234567", "1" * 4301,
])
def test_invalid_page_cannot_create_a_source_scope_contribution_receipt(page):
    reference = source_ref(page)
    before = asdict(SOURCE)
    assert contribution_receipt(reference, PROFILE, PERIOD, "activity_summary",
                                text=TEXT, source=SOURCE) == ""
    assert asdict(SOURCE) == before


@pytest.mark.parametrize("page", [
    "0", "000", "²", "①", "٥", "９", "1234567", "9" * 4301,
])
def test_invalid_page_does_not_mark_plain_text_as_a_source_contribution(page):
    reference = source_ref(page)
    block = ResolvedBlock("activity_summary", "This month", text=TEXT,
                          references=(reference,))
    draft = draft_for(block)
    original = asdict(draft)
    assert source_uses(draft, SOURCE_ID) == ()
    assert included_scope_valid(draft, SOURCE)
    assert asdict(draft) == original


@pytest.mark.parametrize("page", ["0", "²", "١", "9999999"])
def test_invalid_page_cannot_make_a_standalone_table_source_bound(page):
    table = ReportTable(("Finding",), (("Inspected filter",),), source_ref(page))
    block = ResolvedBlock("activity_summary", "This month", extra_tables=(table,))
    assert source_uses(draft_for(block), SOURCE_ID) == ()


@pytest.mark.parametrize("page", ["0", "²", "٩", "1234567"])
def test_invalid_page_cannot_make_an_ai_paragraph_source_bound(page):
    paragraph = DraftParagraph(TEXT, (), (source_ref(page),))
    block = ResolvedBlock("activity_summary", "This month", ai_paragraphs=(paragraph,))
    assert source_uses(draft_for(block), SOURCE_ID) == ()


@pytest.mark.parametrize("page", ["0", "²", "٥", "1234567"])
def test_invalid_page_cannot_make_an_included_followup_source_bound(page):
    followup = ReportFollowUp("followup-1", "issue", "Synthetic follow-up",
                              "2026-09", references=(source_ref(page),))
    sections = (*SECTIONS, SectionSpec("issues", "8", "Issues",
                                      (BlockSpec("equipment_issues", "rich_text"),)))
    draft = replace(draft_for(), sections=sections, follow_ups=(followup,))
    assert source_uses(draft, SOURCE_ID) == ()


@pytest.mark.parametrize("page", ["1", "001"])
def test_valid_receipt_and_contribution_still_bind_exact_current_source(page):
    reference = source_ref(page)
    receipt = contribution_receipt(reference, PROFILE, PERIOD, "activity_summary",
                                   text=TEXT, source=SOURCE)
    assert receipt.startswith(USE_PREFIX)
    block = ResolvedBlock("activity_summary", "This month", text=TEXT,
                          references=(reference, receipt))
    draft = draft_for(block)
    uses = source_uses(draft, SOURCE_ID)
    assert len(uses) == 1 and uses[0][:3] == ("text", block.key, TEXT)
    assert included_scope_valid(draft, SOURCE)
    # The existing receipt must not approve a later change to extracted facts.
    changed = replace(SOURCE, page_texts=("Replaced extraction",))
    assert not included_scope_valid(replace(draft, sources=(changed,)), changed)


def test_valid_saved_site_scope_stays_valid_without_reconfirming():
    scoped = correct_scope(SOURCE, PROFILE, ("north",))
    assert reviewed_scope(scoped, PROFILE) is not None
    block = ResolvedBlock("activity_summary", "This month", text=TEXT,
                          references=(source_ref("1"),))
    assert included_scope_valid(draft_for(block, sources=(scoped,)), scoped)


def test_omitted_block_cannot_gain_source_use_even_with_valid_reference():
    block = ResolvedBlock("activity_summary", "Omit", text=TEXT,
                          references=(source_ref("1"),))
    assert source_uses(draft_for(block), SOURCE_ID) == ()


def test_saved_snapshot_preserves_raw_invalid_reference_for_explicit_correction(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    reference = source_ref("²")
    block = ResolvedBlock("activity_summary", "This month", text=TEXT,
                          references=(reference,))
    draft = draft_for(block)
    initial = asdict(draft)
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD)
    assert reopened == saved
    assert reopened.draft.blocks[0].references == (reference,)
    assert source_uses(reopened.draft, SOURCE_ID) == ()
    assert asdict(draft) == initial
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, 1) == saved
