"""Directory Apply must retain report-owned contact content (synthetic fixtures only)."""

from dataclasses import replace

import pytest

from app import monthly_report_directory as directory, monthly_report_library as library
from app.monthly_report_model import (
    ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, default_sections,
)


@pytest.fixture
def partial_report(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "directory-apply"))
    site = directory.DirectorySite(
        "north", "Synthetic North",
        contacts=(directory.DirectoryContact("Director", "Directory Person", "202-555-0100"),),
    )
    first = directory.save_directory(
        "Synthetic Contact Contract", (site,), expected_revision=0,
        actor="Synthetic Editor", confirmed=True,
    )
    profile = ReportProfile(
        first.contract, "two-sites", "Synthetic two-site report",
        (Facility("north", "Synthetic North"), Facility("south", "Synthetic South")),
        scope_type="multi_site",
    )
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", default_sections(), ())
    copied, missing = directory.contact_block(first, profile.facilities, {"north": "north"})
    assert missing == ("Synthetic South",)
    draft = directory.apply_contacts(draft, replace(copied, source="Library"))
    return first, draft


def _contact(draft):
    return next(block for block in draft.blocks if block.key == "contact_matrix")


def _next_directory(first, *, add_south=False):
    north = replace(
        first.sites[0],
        contacts=(directory.DirectoryContact("Director", "Directory Person", "202-555-0199"),),
    )
    sites = (north,)
    if add_south:
        sites += (directory.DirectorySite(
            "south", "Synthetic South",
            contacts=(directory.DirectoryContact("Director", "New Shared Person"),),
        ),)
    return directory.save_directory(
        first.contract, sites, expected_revision=first.revision,
        actor="Synthetic Editor", confirmed=True,
    )


def _candidate(state, draft, *, add_south=False):
    bindings = {"north": "north", **({"south": "south"} if add_south else {})}
    candidate, missing = directory.contact_block(state, draft.profile.facilities, bindings)
    assert missing == (() if add_south else ("Synthetic South",))
    return candidate


def _local_row():
    return ("Synthetic South", "Local Operator", "Report-Only Person", "202-555-0110", "local@example.invalid")


def test_apply_keeps_report_only_row_custom_column_table_note_and_artwork(partial_report):
    """The live guided route calls apply_contacts with the saved directory block."""
    first, draft = partial_report
    old = _contact(draft)
    # The original image-capable contact page has a report-authored column,
    # row, note, second table, and artwork which belong to this report alone.
    sections = tuple(replace(section, blocks=tuple(
        replace(spec, columns=(*spec.columns, ColumnSpec("local", "Local details")))
        if spec.key == "contact_matrix" else spec for spec in section.blocks
    )) for section in default_sections())
    local_row = (*_local_row(), "keep this value")
    extra = ReportTable(("Local field", "Local value"), (("Desk", "Weekends"),))
    artwork = "a" * 64
    old = replace(
        old, source="This month",
        rows=tuple((*row, "report-specific cell") for row in old.rows) + (local_row,),
        text="Report-only note; do not replace.",
        extra_tables=(extra,),
        asset_hashes=(artwork,),
        references=(*old.references, "report-artwork:synthetic"),
    )
    draft = replace(draft, sections=sections, blocks=(old,))
    latest = _next_directory(first)
    incoming = _candidate(latest, draft)

    applied = directory.apply_contacts(draft, incoming)
    after = _contact(applied)
    assert after.rows == ((*incoming.rows[0], "report-specific cell"), local_row)
    assert after.text == old.text
    assert after.extra_tables == (extra,)
    assert after.asset_hashes == (artwork,)
    assert "report-artwork:synthetic" in after.references
    assert after.references[0].endswith(":2")
    assert after.source == incoming.source
    spec = next(spec for s in applied.sections for spec in s.blocks if spec.key == "contact_matrix")
    assert spec.columns[-1].key == "local"
    assert spec.type == "image_page"


def test_partial_directory_keeps_unmatched_site_row_and_survives_save_reopen(partial_report):
    first, draft = partial_report
    old = _contact(draft)
    local = _local_row()
    extra = ReportTable(("Additional",), (("Keep",),))
    draft = replace(draft, blocks=(replace(
        old, rows=(*old.rows, local), extra_tables=(extra,), text="Local instruction",
    ),))
    latest = _next_directory(first)
    applied = directory.apply_contacts(draft, _candidate(latest, draft))
    assert _contact(applied).rows == (*_candidate(latest, draft).rows, local)
    assert _contact(applied).extra_tables == (extra,)
    assert _contact(applied).text == "Local instruction"

    saved = library.save_snapshot(applied, expected_revision=0, entered_editor=applied.prepared_by)
    reopened = library.load_snapshot(applied.profile.contract, applied.profile.key, applied.period)
    assert reopened is not None
    assert _contact(reopened.draft) == _contact(saved.draft)


def test_scope_expansion_with_unmapped_report_row_requires_review(partial_report):
    first, draft = partial_report
    old = _contact(draft)
    draft = replace(draft, blocks=(replace(old, rows=(*old.rows, _local_row())),))
    expanded = _next_directory(first, add_south=True)
    incoming = _candidate(expanded, draft, add_south=True)
    with pytest.raises(ValueError, match="review|Review|scope"):
        directory.apply_contacts(draft, incoming)
    assert _contact(draft).rows[-1] == _local_row()


def test_unproved_and_omitted_content_cannot_be_replaced(partial_report):
    first, draft = partial_report
    incoming = _candidate(_next_directory(first), draft)
    old = _contact(draft)
    unproved = replace(old, rows=(*old.rows, _local_row()), references=())
    with pytest.raises(ValueError, match="review|Review|directory"):
        directory.apply_contacts(replace(draft, blocks=(unproved,)), incoming)
    omitted = replace(old, source="Omit", text="Intentionally omitted; retain note.")
    with pytest.raises(ValueError, match="omitted|Omit|review"):
        directory.apply_contacts(replace(draft, blocks=(omitted,)), incoming)
    sections = tuple(replace(s, included=False) if s.key == "organization" else s for s in draft.sections)
    with pytest.raises(ValueError, match="omitted|Omit|review"):
        directory.apply_contacts(replace(draft, sections=sections), incoming)


def test_foreign_contract_directory_is_never_applied(partial_report):
    _, draft = partial_report
    other = directory.save_directory(
        "Unrelated Synthetic Contract", (
            directory.DirectorySite("south", "Synthetic South", contacts=(
                directory.DirectoryContact("Director", "Foreign Person"),)),
        ), expected_revision=0, actor="Synthetic Editor", confirmed=True,
    )
    foreign, _ = directory.contact_block(other, draft.profile.facilities, {"south": "south"})
    with pytest.raises(ValueError, match="contract"):
        directory.apply_contacts(draft, foreign)


def test_explicit_save_keeps_typed_rows_after_directory_rows_across_two_sites(monkeypatch, tmp_path):
    """Owner decision (b), 10 Nov 2026, for "Save contacts to directory and report"."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "explicit-save"))
    state = directory.save_directory(
        "Synthetic Explicit Contract", (
            directory.DirectorySite("north", "Synthetic North", contacts=(
                directory.DirectoryContact("Director", "North Director", "202-555-0101"),
                directory.DirectoryContact("Engineer", "North Engineer", "202-555-0102"),
            )),
            directory.DirectorySite("south", "Synthetic South", contacts=(
                directory.DirectoryContact("Director", "South Director", "202-555-0103"),
            )),
        ), expected_revision=0, actor="Synthetic Editor", confirmed=True,
    )
    profile = ReportProfile(
        state.contract, "two-sites", "Synthetic two-site report",
        (Facility("north", "Synthetic North"), Facility("south", "Synthetic South")),
        scope_type="multi_site",
    )
    typed = (
        ("Synthetic North", "Night Lead", "Typed Person One", "202-555-0111", "one@example.invalid"),
        ("Synthetic South", "Day Lead", "Typed Person Two", "202-555-0112", "two@example.invalid"),
    )
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", default_sections(), ())
    draft = directory.apply_contacts(draft, ResolvedBlock("contact_matrix", "This month", rows=typed))
    incoming, missing = directory.contact_block(state, profile.facilities, {"north": "north", "south": "south"})
    assert missing == () and len(incoming.rows) == 3

    # The automatic paths still leave rows typed into the report alone.
    with pytest.raises(ValueError, match="verified directory identity"):
        directory.apply_contacts(draft, incoming)
    assert directory.apply_defaults(draft) == draft

    saved = directory.apply_contacts(draft, incoming, keep_report_rows=True)
    contacts = _contact(saved)
    assert contacts.rows == (*incoming.rows, *typed)
    assert set(incoming.references) <= set(contacts.references)


def test_explicit_save_keeps_row_for_newly_covered_site_and_other_refusals(partial_report):
    first, draft = partial_report
    old = _contact(draft)
    draft = replace(draft, blocks=(replace(old, rows=(*old.rows, _local_row())),))
    incoming = _candidate(_next_directory(first, add_south=True), draft, add_south=True)
    saved = directory.apply_contacts(draft, incoming, keep_report_rows=True)
    assert _contact(saved).rows == (*incoming.rows, _local_row())

    omitted = replace(old, source="Omit", text="Intentionally omitted; retain note.")
    with pytest.raises(ValueError, match="omit"):
        directory.apply_contacts(replace(draft, blocks=(omitted,)), incoming, keep_report_rows=True)
    other = directory.save_directory(
        "Unrelated Synthetic Contract", (
            directory.DirectorySite("south", "Synthetic South", contacts=(
                directory.DirectoryContact("Director", "Foreign Person"),)),
        ), expected_revision=0, actor="Synthetic Editor", confirmed=True,
    )
    foreign, _ = directory.contact_block(other, draft.profile.facilities, {"south": "south"})
    with pytest.raises(ValueError, match="contract"):
        directory.apply_contacts(draft, foreign, keep_report_rows=True)


@pytest.mark.parametrize("existing", [False, True])
def test_fresh_extended_schema_keeps_heading_and_row_width(partial_report, existing):
    first, draft = partial_report
    sections = tuple(replace(s, blocks=tuple(
        replace(spec, columns=(*directory.CONTACT_SPEC.columns, ColumnSpec("local", "Local details")))
        if spec.key == "contact_matrix" else spec for spec in s.blocks)) for s in draft.sections)
    draft = replace(draft, sections=sections,
                    blocks=(ResolvedBlock("contact_matrix", "Omit"),) if existing else ())
    applied = directory.apply_contacts(draft, _candidate(first, draft))
    spec = next(b for s in applied.sections for b in s.blocks if b.key == "contact_matrix")
    assert spec.columns[-1].title == "Local details"
    assert len(spec.columns) == len(_contact(applied).rows[0]) == 6
    saved = library.save_snapshot(applied, expected_revision=0, entered_editor=applied.prepared_by)
    reopened = library.load_snapshot(applied.profile.contract, applied.profile.key, applied.period)
    assert reopened.draft.sections == saved.draft.sections
    assert _contact(reopened.draft).rows == _contact(applied).rows


@pytest.mark.parametrize("alias", ["synthetic contact contract", "SYNTHETIC CONTACT CONTRACT", "Synthetic  Contact Contract"])
def test_apply_resolves_saved_contract_alias_and_historical_rows(partial_report, alias):
    first, draft = partial_report
    draft = replace(draft, profile=replace(draft.profile, contract=alias))
    assert directory.load_directory(alias).contract == first.contract
    latest = _next_directory(first)
    applied = directory.apply_contacts(draft, _candidate(latest, draft))
    assert _contact(applied).rows[0][3] == "202-555-0199"
    assert _contact(applied).references[0].endswith(":2")
