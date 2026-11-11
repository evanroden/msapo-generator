"""Reachable directory Apply Undo: isolated synthetic contact preservation only."""

from dataclasses import replace

import pytest

from tests.conftest import requires_libreoffice

from app import monthly_report_contact_apply_undo as undo
from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app.monthly_report_model import (
    ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile,
    ReportTable, ResolvedBlock, default_sections,
)


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "undo-only"))
    first = directory.save_directory(
        "Synthetic Undo Contract",
        (directory.DirectorySite(
            "north", "Synthetic North", contacts=(
                directory.DirectoryContact("Manager", "Synthetic North Person", "202-555-0101"),
            )),),
        expected_revision=0, actor="Synthetic Writer", confirmed=True,
    )
    profile = ReportProfile(
        first.contract, "two-site-undo", "Two sites",
        (Facility("north", "Synthetic North"), Facility("south", "Synthetic South")),
        scope_type="multi_site",
    )
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Writer",
                        default_sections(), ())
    first_block, missing = directory.contact_block(
        first, profile.facilities, {"north": "north"})
    assert missing == ("Synthetic South",)
    prior = directory.apply_contacts(draft, replace(first_block, source="Library"))
    second = directory.save_directory(
        first.contract,
        (replace(first.sites[0], contacts=(
            directory.DirectoryContact("Manager", "Synthetic North Person", "202-555-0199"),
        )),),
        expected_revision=first.revision, actor="Synthetic Writer", confirmed=True,
    )
    new_block, missing = directory.contact_block(
        second, profile.facilities, {"north": "north"})
    assert missing == ("Synthetic South",)
    return first, second, prior, new_block


def contacts(draft):
    return next(b for b in draft.blocks if b.key == "contact_matrix")


def contact_spec(draft):
    return next(b for section in draft.sections for b in section.blocks
                if b.key == "contact_matrix")


def test_scoped_undo_keeps_report_rows_notes_art_and_later_unrelated_edit(scenario):
    first, second, before, incoming = scenario
    original = contacts(before)
    extra = ReportTable(("Contact detail", "Answer"), (("After hours", "Night line"),))
    columns = (*contact_spec(before).columns, ColumnSpec("local", " "),
               ColumnSpec("local", " "))  # intentional duplicate keys/blank titles
    sections = tuple(replace(s, blocks=tuple(
        replace(b, columns=columns) if b.key == "contact_matrix" else b
        for b in s.blocks)) for s in before.sections)
    local = ("Synthetic South", "Relief", "Report Person", "202-555-0188",
             "report@example.invalid", "Keep A", "Keep B")
    before = replace(before, sections=sections,
                     blocks=(replace(original,
                         rows=tuple((*row, "Old A", "Old B") for row in original.rows) + (local,),
                         text="Report-owned notes", extra_tables=(extra,),
                         asset_hashes=("a" * 64,),
                         references=(*original.references, "report-image:synthetic")),))
    applied = directory.apply_contacts(before, incoming, keep_report_rows=True)
    assert contact_spec(applied).columns == columns
    receipt = undo.capture_directory_apply(before, applied, len(incoming.rows))
    assert receipt.previous_owned_rows == before.blocks[0].rows[:1]

    # A report-only contact correction and an unrelated section edit are later.
    new_local = (*local[:3], "202-555-0170", *local[4:])
    edited = replace(contacts(applied), rows=(*contacts(applied).rows[:1], new_local),
                     text="Newer report note", asset_hashes=("a" * 64, "b" * 64))
    activity = ResolvedBlock("activity_narrative", "This month", text="Later activity edit")
    later = replace(applied, blocks=(edited, activity))
    restored = undo.undo_directory_apply(later, receipt)
    final = contacts(restored)
    assert final.rows == ((*original.rows[0], "Old A", "Old B"), new_local)
    assert final.text == "Newer report note"
    assert final.asset_hashes == ("a" * 64, "b" * 64)
    assert final.extra_tables == (extra,)
    assert "report-image:synthetic" in final.references
    assert final.references[0].endswith(":1")
    assert undo.UNDO_MARKER in final.references
    assert contact_spec(restored).columns == columns
    assert restored.blocks[1] == activity
    assert restored.sections == before.sections
    assert directory.load_directory(first.contract) == second
    assert directory.load_directory(first.contract, 1) == first
    # An explicit report-local Undo survives reload and is not immediately
    # replaced by the newer shared directory's automatic refresh.
    assert directory.refresh_directory_contacts(restored) == restored


@pytest.mark.parametrize("change", [
    "owned-row", "source", "provenance", "contact-columns", "report", "period",
])
def test_scoped_undo_refuses_conflicts_without_overwriting(change, scenario):
    _, _, before, incoming = scenario
    applied = directory.apply_contacts(before, incoming)
    receipt = undo.capture_directory_apply(before, applied, len(incoming.rows))
    current = contacts(applied)
    if change == "owned-row":
        bad = replace(current, rows=((current.rows[0][0], current.rows[0][1],
                                     "Edited by another person", *current.rows[0][3:]),))
        changed = replace(applied, blocks=(bad,))
    elif change == "source":
        changed = replace(applied, blocks=(replace(current, source="Replace once"),))
    elif change == "provenance":
        changed = replace(applied, blocks=(replace(current, references=("directory:foreign:9",)),))
    elif change == "contact-columns":
        sections = tuple(replace(s, blocks=tuple(
            replace(b, columns=(*b.columns, ColumnSpec("other", "Other")))
            if b.key == "contact_matrix" else b for b in s.blocks)) for s in applied.sections)
        changed = replace(applied, sections=sections)
    elif change == "report":
        changed = replace(applied, profile=replace(applied.profile, key="another-report"))
    else:
        changed = replace(applied, period=ReportPeriod(2026, 10))
    with pytest.raises(ValueError):
        undo.undo_directory_apply(changed, receipt)
    assert changed != before


def test_undo_empty_fresh_report_does_not_autofill_and_can_reapply(scenario):
    _, second, prior, incoming = scenario
    # A fresh report has no existing contact block but can have an imported
    # image-page schema with deliberately duplicate or empty custom headings.
    sections = tuple(replace(s, blocks=tuple(
        replace(spec, columns=(*spec.columns, ColumnSpec("blank", ""),
                                ColumnSpec("blank", "")))
        if spec.key == "contact_matrix" else spec for spec in s.blocks))
        for s in prior.sections)
    fresh = replace(prior, sections=sections, blocks=())
    applied = directory.apply_contacts(fresh, incoming, keep_report_rows=True)
    assert len(contacts(applied).rows[0]) == 7
    receipt = undo.capture_directory_apply(fresh, applied, len(incoming.rows))
    restored = undo.undo_directory_apply(applied, receipt)
    assert contacts(restored).rows == ()
    assert contacts(restored).source == "This month"
    assert undo.UNDO_MARKER in contacts(restored).references
    assert directory.apply_defaults(restored) == restored
    assert directory.refresh_directory_contacts(restored) == restored
    assert contact_spec(restored).columns[-2:] == (
        ColumnSpec("blank", ""), ColumnSpec("blank", ""))
    # A later explicit Apply removes the deliberate Undo marker and uses the
    # selected directory, rather than silently filling an omitted report.
    reapplied = directory.apply_contacts(restored, incoming, keep_report_rows=True)
    assert contacts(reapplied).rows == contacts(applied).rows
    assert undo.UNDO_MARKER not in contacts(reapplied).references
    assert directory.load_directory(second.contract) == second


def test_repeated_explicit_apply_undo_then_snapshot_reopen(scenario):
    first, second, original, incoming = scenario
    after = directory.apply_contacts(original, incoming, keep_report_rows=True)
    receipt = undo.capture_directory_apply(original, after, len(incoming.rows))
    restored = undo.undo_directory_apply(after, receipt)
    again = directory.apply_contacts(restored, incoming, keep_report_rows=True)
    saved = library.save_snapshot(again, expected_revision=0, entered_editor=again.prepared_by)
    reopened = library.load_snapshot(again.profile.contract, again.profile.key, again.period)
    assert reopened is not None
    assert contacts(reopened.draft) == contacts(saved.draft)
    assert contact_spec(reopened.draft) == contact_spec(again)
    assert directory.load_directory(first.contract, first.revision) == first
    assert directory.load_directory(second.contract) == second


def test_legacy_undo_receipt_and_unrelated_section_changes(scenario):
    _, _, before, incoming = scenario
    after = directory.apply_contacts(before, incoming)
    receipt = undo.capture_directory_apply(before, after, len(incoming.rows))
    with pytest.raises(ValueError, match="legacy"):
        undo.undo_directory_apply(after, (before, before.sections))
    extra_section = next(s for s in after.sections if s.key != "organization")
    modified = replace(extra_section, title="Later independent section title")
    later = replace(after, sections=tuple(
        modified if s.key == extra_section.key else s for s in after.sections))
    result = undo.undo_directory_apply(later, receipt)
    assert modified in result.sections
    assert contacts(result).rows == contacts(before).rows


@pytest.mark.parametrize("native", [False, True])
def test_actual_docx_after_apply_and_undo_keeps_correct_contacts(scenario, tmp_path, native):
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import _build_docx
    from app.monthly_report_native_layout import build_native_docx
    from tests.test_monthly_report_contact_headers import native_contact_source
    from tests.test_monthly_report_generic_contact_page import _draft

    _, _, before, incoming = scenario
    applied = directory.apply_contacts(before, incoming)
    receipt = undo.capture_directory_apply(before, applied, len(incoming.rows))
    restored = undo.undo_directory_apply(applied, receipt)
    for expected, state in (
        ("202-555-0199", applied), ("202-555-0101", restored),
    ):
        baseline = _draft(chart=False)
        layout = replace(baseline.sections[0], blocks=tuple(
            spec for spec in baseline.sections[0].blocks
            if spec.key == "contact_matrix"))
        output = replace(baseline, sections=(layout,), blocks=(contacts(state),))
        raw = (build_native_docx(output, native_contact_source(
            tmp_path / ("native-" + expected + ".docx")), master=True)
               if native else _build_docx(output))
        document = Document(BytesIO(raw))
        cells = tuple(cell.text for table in document.tables
                      for row in table.rows for cell in row.cells)
        assert expected in cells
        assert ("202-555-0101" if expected == "202-555-0199"
                else "202-555-0199") not in cells
        assert "Synthetic North Person" in cells


@requires_libreoffice
@pytest.mark.parametrize("native", [False, True])
def test_actual_pdf_after_apply_and_undo_keeps_correct_contacts(
    scenario, tmp_path, monkeypatch, native,
):
    from app import pdf_converter
    from app.monthly_report_docx import _build_docx
    from app.monthly_report_native_layout import build_native_docx
    from tests.test_monthly_report_contact_headers import native_contact_source
    from tests.test_monthly_report_generic_contact_page import _draft
    import pymupdf as fitz

    # Uses real LibreOffice conversion, not a mocked PDF service.
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    _, _, before, incoming = scenario
    applied = directory.apply_contacts(before, incoming)
    restored = undo.undo_directory_apply(
        applied, undo.capture_directory_apply(before, applied, len(incoming.rows)))
    for expected, state in (
        ("202-555-0199", applied), ("202-555-0101", restored),
    ):
        baseline = _draft(chart=False)
        layout = replace(baseline.sections[0], blocks=tuple(
            spec for spec in baseline.sections[0].blocks
            if spec.key == "contact_matrix"))
        output = replace(baseline, sections=(layout,), blocks=(contacts(state),))
        raw = (build_native_docx(output, native_contact_source(
            tmp_path / ("native-pdf-" + expected + ".docx")), master=True)
               if native else _build_docx(output))
        source = tmp_path / (expected + ".docx")
        source.write_bytes(raw)
        converted = pdf_converter.convert_to_pdf(source)
        try:
            with fitz.open(converted) as pdf:
                text = "\n".join(page.get_text() for page in pdf)
            assert expected in text
            assert ("202-555-0101" if expected == "202-555-0199"
                    else "202-555-0199") not in text
        finally:
            converted.unlink(missing_ok=True)


def test_real_generic_docx_retains_blank_duplicate_contact_headings_and_cells(scenario):
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import _build_docx
    from tests.test_monthly_report_generic_contact_page import _draft

    _, _, before, incoming = scenario
    headings = (*contact_spec(before).columns, ColumnSpec("local", ""),
                ColumnSpec("local", ""))
    sections = tuple(replace(section, blocks=tuple(
        replace(spec, columns=headings) if spec.key == "contact_matrix" else spec
        for spec in section.blocks)) for section in before.sections)
    old = contacts(before)
    before = replace(before, sections=sections, blocks=(replace(
        old, rows=tuple((*row, "Synthetic private A", "Synthetic private B")
                        for row in old.rows)),))
    applied = directory.apply_contacts(before, incoming)
    receipt = undo.capture_directory_apply(before, applied, len(incoming.rows))
    restored = undo.undo_directory_apply(applied, receipt)
    for state, phone in ((applied, "202-555-0199"), (restored, "202-555-0101")):
        baseline = _draft(chart=False)
        organization = replace(baseline.sections[0], blocks=(
            contact_spec(state),))
        value = replace(baseline, sections=(organization,), blocks=(contacts(state),))
        document = Document(BytesIO(_build_docx(value)))
        table = next(table for table in document.tables
                     if any(phone in cell.text for row in table.rows for cell in row.cells))
        assert len(table.columns) == 7
        assert tuple(cell.text for cell in table.rows[0].cells) == (
            "Facility", "Role", "Name", "Phone", "Email", "", "")
        assert tuple(cell.text for cell in table.rows[1].cells[-2:]) == (
            "Synthetic private A", "Synthetic private B")
