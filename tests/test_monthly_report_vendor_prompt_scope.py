"""Omitted subcontractors are recoverable source data, not model/Copilot context.

All names are invented. No model request or outbound API is made by these
tests; only the exact generated prompt payloads are inspected.
"""
from dataclasses import replace
import json

import pytest

from app import monthly_report_ai as ai
from app import monthly_report_library as library
from app.monthly_report_model import (
    EvidenceFact, ReportPeriod, ReportSource, ReportTable, ResolvedBlock,
    default_sections, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_prompts import copilot_prompt

PROFILE = replace(synthetic_profiles()[0], asset_tags=("PMP-99",))
PERIOD = ReportPeriod(2026, 9)
VENDOR_A = "Synthetic Alpha Services"
VENDOR_B = "Synthetic Beta Services"
OMITTED = "Synthetic Omitted Vendor Never Send"

def contact_block(*, source="Library"):
    return ResolvedBlock(
        "subcontractor_matrix", source,
        rows=(
            ("Synthetic facility", "Mechanical", VENDOR_A, "Contact omitted from glossary", "555-0110", "Agreement"),
            ("Synthetic facility", "Water", VENDOR_B, "Another contact", "555-0111", ""),
            ("Synthetic facility", "Mechanical", VENDOR_A, "", "", ""),
        ),
        extra_tables=(
            ReportTable(
                ("Facility", "Supplier name", "Phone", "Status"),
                (("Synthetic facility", VENDOR_B, "555-0112", "Available"),
                 ("Synthetic facility", "Synthetic Gamma Services", "555-0113", "Available")),
                "synthetic-source-1",
            ),
        ),
        text="Keep this report-only note.",
    )

def report(*, source="Library", include_section=True, with_section=True):
    sections = tuple(replace(section, included=include_section)
                     if section.key == "subcontractors" else section
                     for section in default_sections()) if with_section else tuple(
                     section for section in default_sections()
                     if section.key != "subcontractors")
    return replace(
        synthetic_draft(PROFILE, PERIOD),
        sections=sections,
        blocks=(contact_block(source=source),),
    )

def prompts(draft):
    names = ai.vendor_names(draft)
    copied = copilot_prompt(draft.profile, draft.period, names, draft.profile.asset_tags)
    fact = EvidenceFact(
        "synthetic-fact-1", "synthetic-source", 1, "action",
        "Inspected synthetic pressure sensors.",
        "Inspected synthetic pressure sensors.")
    source = ReportSource(
        "synthetic-source", "synthetic-report.pdf", "a" * 64, ".pdf",
        page_texts=("Inspected synthetic pressure sensors.",),
        selected_pages=(1,), facts=(fact,))
    _, request, linked = ai.drafting_request(
        "activity_summary", (source,), draft.period, names,
        draft.profile.asset_tags,
    )
    assert linked == (fact,)
    text = request[0]["text"]
    # Verify the real outbound JSON body rather than mocking the reader.
    assert text.startswith(ai.DRAFT_PROMPT + "\n")
    payload = json.loads(text[len(ai.DRAFT_PROMPT) + 1:])
    assert payload["block"] == "activity_summary"
    assert payload["period"] == draft.period.key
    assert payload["vendors"] == list(names)
    assert payload["known_tags"] == list(draft.profile.asset_tags)
    assert payload["facts"][0]["id"] == fact.id
    assert payload["facts"][0]["quote"] == fact.quote
    return copied, text


def test_included_vendor_table_still_supplies_exact_deduplicated_order():
    draft = report()
    assert ai.vendor_names(draft) == (
        VENDOR_A, VENDOR_B, "Synthetic Gamma Services")
    assert draft.blocks[0].text == "Keep this report-only note."
    assert draft.blocks[0].rows[0][4] == "555-0110"


def test_omitted_subcontractor_block_never_sends_retained_names_to_prompts():
    draft = report(source="Omit")
    assert draft.blocks[0].rows[0][2] == VENDOR_A
    assert draft.blocks[0].extra_tables[0].rows[0][1] == VENDOR_B
    assert ai.vendor_names(draft) == ()
    copy, model = prompts(draft)
    for forbidden in (VENDOR_A, VENDOR_B, "Synthetic Gamma Services", "555-0110"):
        assert forbidden not in copy
        assert forbidden not in model
    assert "none specified" in copy
    assert "PMP-99" in copy and "PMP-99" in model
    assert draft.blocks[0].source == "Omit"


def test_excluded_section_does_not_send_names_from_any_saved_source_table():
    draft = report(include_section=False)
    assert ai.vendor_names(draft) == ()
    copy, model = prompts(draft)
    assert VENDOR_A not in copy and VENDOR_A not in model
    assert VENDOR_B not in copy and VENDOR_B not in model
    assert draft.blocks[0].source == "Library"
    assert draft.blocks[0].extra_tables[0].rows[1][1] == "Synthetic Gamma Services"


def test_missing_active_subcontractor_section_never_uses_orphaned_vendor_rows():
    draft = report(with_section=False)
    assert ai.vendor_names(draft) == ()
    assert draft.blocks[0].rows[0][2] == VENDOR_A
    copy, model = prompts(draft)
    assert VENDOR_A not in copy and VENDOR_A not in model


@pytest.mark.parametrize("source,visible", (
    ("Library", True), ("This month", True), ("Omit", False),
))
def test_prompt_exposure_tracks_explicit_inclusion_not_saved_contact_bytes(source, visible):
    draft = report(source=source)
    copy, model = prompts(draft)
    assert (VENDOR_A in copy) == visible
    assert (VENDOR_B in model) == visible
    assert draft.blocks[0].rows[0][2] == VENDOR_A
    assert draft.blocks[0].extra_tables[0].rows[0][1] == VENDOR_B


def test_reinclude_section_restores_only_vendor_spelling_context_not_source_edits():
    omitted = report(include_section=False)
    section = next(s for s in omitted.sections if s.key == "subcontractors")
    included = replace(omitted, sections=tuple(
        replace(s, included=True) if s.key == section.key else s
        for s in omitted.sections))
    assert ai.vendor_names(omitted) == ()
    assert ai.vendor_names(included) == (
        VENDOR_A, VENDOR_B, "Synthetic Gamma Services")
    assert included.blocks == omitted.blocks
    assert included.profile == omitted.profile
    copy, model = prompts(included)
    assert VENDOR_A in copy and VENDOR_A in model


def test_contact_and_phone_columns_cannot_be_used_as_vendor_glossary_names():
    block = ResolvedBlock(
        "subcontractor_matrix", "Library",
        rows=(("Synthetic facility", "Mechanical", VENDOR_A,
               "555-9999", "alpha@example.invalid", ""),),
        extra_tables=(ReportTable(
            ("Vendor contact", "Contact", "Phone", "Email", "Notes"),
            ((OMITTED, "Someone", "555-0100", "another@example.invalid",
              "Vendor line in a contact column only"),), "synthetic:2"),),
    )
    draft = replace(report(), blocks=(block,))
    assert ai.vendor_names(draft) == (VENDOR_A,)
    copy, model = prompts(draft)
    assert VENDOR_A in copy and VENDOR_A in model
    for forbidden in (OMITTED, "555-9999", "alpha@example.invalid",
                      "another@example.invalid"):
        assert forbidden not in copy
        assert forbidden not in model


def test_omitted_vendor_names_survive_snapshot_and_reopen_without_prompt_leak(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = report(source="Omit")
    library.save_snapshot(draft, expected_revision=0)
    stored = library.load_snapshot(
        draft.profile.contract, draft.profile.key, draft.period)
    assert stored.revision == 1
    assert stored.draft.blocks == draft.blocks
    assert stored.draft.blocks[0].extra_tables == draft.blocks[0].extra_tables
    assert ai.vendor_names(stored.draft) == ()
    copy, model = prompts(stored.draft)
    assert VENDOR_A not in copy and VENDOR_A not in model
    assert VENDOR_B not in copy and VENDOR_B not in model
    assert stored.draft.blocks[0].rows[0][2] == VENDOR_A


def test_restricted_prompt_minimization_does_not_require_new_reader_calls(monkeypatch):
    import app.monthly_report_ai as model

    def fail(*args, **kwargs):
        raise AssertionError("Vendor name filtering must not use an external reader.")

    monkeypatch.setattr(model, "request_json", fail)
    omitted = report(source="Omit")
    included = report(source="Library")
    assert ai.vendor_names(omitted) == ()
    assert ai.vendor_names(included)[0] == VENDOR_A
    prompts(omitted)
    prompts(included)
