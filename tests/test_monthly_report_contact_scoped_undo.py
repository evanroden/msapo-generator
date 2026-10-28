"""An explicit contact-table Undo cannot overwrite later independent report edits.

All contracts, contacts, rows, source references and images are synthetic.
No shared directory is changed by Undo, and an older report snapshot stays
immutable even when the working draft is restored.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app.monthly_report_contact_undo import (
    ContactUndoReceipt, capture_contact_undo, contact_undo_ready,
    undo_contact_update,
)
from app.monthly_report_model import (
    ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, default_sections,
)


PROFILE = ReportProfile("Synthetic Undo Contract", "north", "Synthetic North",
                        (Facility("north", "Synthetic North", ("SN",)),))
PERIOD = ReportPeriod(2026, 9)

ORIGINAL = ResolvedBlock(
    "contact_matrix", "This month",
    text="Report-only escalation order remains unchanged.",
    rows=(("Synthetic North", "Director", "Independent Person",
           "202-555-0100", "independent@example.invalid"),),
    extra_tables=(ReportTable(("Custom role", "Notes", ""),
                              (("Escalation", "Do not discard", "Blank retained"),),
                              "synthetic:older-contact-page"),),
    asset_hashes=("synthetic-contacts.png",),
    asset_captions=("Original approved contact page",),
    references=("synthetic:source-original",),
    client_reviewed_fingerprint="synthetic-original-review",
)
REPLACEMENT = ResolvedBlock("contact_matrix", "This month",
    rows=(("Synthetic North", "Manager", "Directory Person",
           "202-555-0101", "directory@example.invalid"),),
    references=("directory:synthetic-undo:1", "directory-site:north:north"),
)


def contact_section(sections):
    return next(s for s in sections if any(b.key == "contact_matrix" for b in s.blocks))


def contact_block(draft):
    return next((b for b in draft.blocks if b.key == "contact_matrix"), None)


def draft_with_original(*, omitted=False, contact=ORIGINAL):
    sections = default_sections()
    if omitted:
        # Deliberately preserve a nonstandard imported contact schema and
        # previously excluded contact section; Apply is an explicit Include.
        original_spec = next(b for b in contact_section(sections).blocks
                             if b.key == "contact_matrix")
        adjusted = replace(original_spec, columns=(
            ColumnSpec("imported_site", "Site"),
            ColumnSpec("custom_row", "Custom contact payload"),
        ))
        sections = tuple(replace(s, included=False, blocks=tuple(
            adjusted if b.key == "contact_matrix" else b for b in s.blocks))
            if any(b.key == "contact_matrix" for b in s.blocks) else s
            for s in sections)
    other = (
        ResolvedBlock("org_chart", "This month", text="Independent chart note."),
        ResolvedBlock("activity_summary", "This month", text="Independent work before Apply."),
    )
    return ReportDraft(PROFILE, PERIOD, "Synthetic Reviewer", sections,
                       (*((contact,) if contact else ()), *other))


def applied(original):
    result = directory.apply_contacts(original, REPLACEMENT)
    return result, capture_contact_undo(original, result)


def test_undo_restores_old_contact_artwork_notes_and_custom_columns_only():
    original = draft_with_original(omitted=True)
    after, receipt = applied(original)
    assert isinstance(receipt, ContactUndoReceipt)
    assert contact_block(after) == REPLACEMENT
    assert contact_section(after.sections).included
    assert contact_undo_ready(after, receipt)

    # An independently edited org chart + Activity and a distinct native
    # chart specification are deliberately changed AFTER contact Apply.
    later_blocks = tuple(
        replace(block, text="Later independent operator change")
        if block.key in ("org_chart", "activity_summary") else block
        for block in after.blocks)
    section = contact_section(after.sections)
    chart = next(b for b in section.blocks if b.key == "org_chart")
    altered_sections = tuple(replace(s, blocks=tuple(
        replace(chart, required=not chart.required) if b.key == "org_chart" else b
        for b in s.blocks)) if s.key == section.key else s
        for s in after.sections)
    latest = replace(after, blocks=later_blocks, sections=altered_sections)
    assert contact_undo_ready(latest, receipt)

    restored = undo_contact_update(latest, receipt)
    assert contact_block(restored) == ORIGINAL
    assert contact_block(restored).asset_hashes == ORIGINAL.asset_hashes
    assert contact_block(restored).extra_tables == ORIGINAL.extra_tables
    assert contact_block(restored).references == ORIGINAL.references
    assert contact_block(restored).client_reviewed_fingerprint == ORIGINAL.client_reviewed_fingerprint
    assert not contact_section(restored.sections).included
    original_contact_spec = next(b for b in contact_section(original.sections).blocks
                                 if b.key == "contact_matrix")
    assert next(b for b in contact_section(restored.sections).blocks
                if b.key == "contact_matrix") == original_contact_spec
    assert next(b for b in contact_section(restored.sections).blocks
                if b.key == "org_chart").required != chart.required
    assert all(b.text == "Later independent operator change"
               for b in restored.blocks if b.key in ("org_chart", "activity_summary"))
    assert all(section == old for section, old in
               zip(restored.sections, original.sections)
               if section.key != contact_section(original.sections).key)


@pytest.mark.parametrize("mutation", ("edited_rows", "new_notes", "new_photo",
                                      "extra_source", "contact_spec", "inclusion"))
def test_stale_contact_undo_refuses_newer_contact_or_section_changes(mutation):
    original = draft_with_original(omitted=True)
    after, receipt = applied(original)
    if mutation == "inclusion":
        changed = replace(after, sections=tuple(
            replace(s, included=False) if s.key == contact_section(after.sections).key else s
            for s in after.sections))
    elif mutation == "contact_spec":
        changed = replace(after, sections=tuple(replace(s, blocks=tuple(
            replace(b, required=not b.required) if b.key == "contact_matrix" else b
            for b in s.blocks)) if s.key == contact_section(after.sections).key
            else s for s in after.sections))
    else:
        def modify(b):
            if b.key != "contact_matrix":
                return b
            if mutation == "edited_rows":
                return replace(b, rows=(("Synthetic North", "Manager", "Newer User Edit", "", ""),))
            if mutation == "new_notes":
                return replace(b, text="Later report-only phone note")
            if mutation == "new_photo":
                return replace(b, asset_hashes=("synthetic-new-photo.png",))
            return replace(b, references=(*b.references, "synthetic:later-source"))
        changed = replace(after, blocks=tuple(modify(b) for b in after.blocks))
    assert changed != after and not contact_undo_ready(changed, receipt)
    with pytest.raises(ValueError, match="changed after the directory update"):
        undo_contact_update(changed, receipt)
    assert contact_block(changed) != ORIGINAL


def test_undo_refuses_other_contract_site_month_or_legacy_session_tuple():
    original = draft_with_original()
    after, receipt = applied(original)
    foreign = replace(after, profile=replace(after.profile, contract="Foreign Synthetic Contract"))
    changed_site = replace(after, profile=replace(after.profile,
        facilities=(Facility("other", "Other Site"),), title="Different site"))
    changed_month = replace(after, period=ReportPeriod(2026, 10))
    for candidate in (foreign, changed_site, changed_month):
        assert not contact_undo_ready(candidate, receipt)
        with pytest.raises(ValueError, match="changed after the directory update"):
            undo_contact_update(candidate, receipt)
    assert not contact_undo_ready(after, (contact_block(original), original.sections))


def test_repeated_directory_apply_retires_previous_undo_and_keeps_latest():
    original = draft_with_original()
    after, receipt = applied(original)
    revised = replace(REPLACEMENT, rows=(("Synthetic North", "Director",
        "More recent directory", "", ""),))
    later = directory.apply_contacts(after, revised)
    new_receipt = capture_contact_undo(after, later)
    assert not contact_undo_ready(later, receipt)
    assert contact_undo_ready(later, new_receipt)
    restored = undo_contact_update(later, new_receipt)
    assert contact_block(restored) == REPLACEMENT
    assert contact_block(restored) != ORIGINAL


def test_absent_prior_contact_is_removed_without_touching_other_fields():
    initial = draft_with_original(contact=None)
    after, receipt = applied(initial)
    assert contact_block(after) == REPLACEMENT
    changed = replace(after, blocks=tuple(
        replace(b, text="Later other-section work") if b.key == "activity_summary" else b
        for b in after.blocks))
    restored = undo_contact_update(changed, receipt)
    assert contact_block(restored) is None
    assert next(b for b in restored.blocks if b.key == "activity_summary").text == "Later other-section work"


def test_undo_is_report_only_and_preserves_earlier_saved_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    initial, receipt = None, None
    original = draft_with_original(contact=None)
    after, receipt = applied(original)
    saved = library.save_snapshot(after, expected_revision=0, entered_editor="Synthetic Reviewer")
    restored = undo_contact_update(after, receipt)
    assert contact_block(restored) is None
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == saved
    assert contact_block(saved.draft) == REPLACEMENT

    # Layout-only output still reflects the correct accepted live draft; no
    # shared source or directory is mutated by undo itself.
    from app.monthly_report_docx import _build_docx
    active_section = contact_section(after.sections)
    narrow = replace(after, sections=(active_section,))
    word = Document(BytesIO(_build_docx(narrow)))
    text = "\n".join(cell.text for table in word.tables
                    for row in table.rows for cell in row.cells)
    assert "Directory Person" in text
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == saved


APP = """
import streamlit as st
from app.monthly_report_directory_ui import review_contacts

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

working = st.session_state.get("demo_draft", st.session_state["seed_draft"])
working = review_contacts(working, "demo", field, {})
st.session_state["demo_draft"] = working
"""


def seed_ui(monkeypatch, tmp_path, before):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    directory.save_directory(PROFILE.contract, (
        directory.DirectorySite("north", "Synthetic North", contacts=(
            directory.DirectoryContact("Manager", "Directory Person",
                                       "202-555-0101", "directory@example.invalid"),
        )),
    ), expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["seed_draft"] = before
    app.run()
    assert not app.exception
    return app


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_native_directory_apply_and_scoped_undo_preserve_later_activity(monkeypatch, tmp_path):
    prior = draft_with_original(contact=None)
    app = seed_ui(monkeypatch, tmp_path, prior)
    next(c for c in app.checkbox if c.label.startswith("Replace this report")).check().run()
    button(app, "Use reviewed contact table").click().run()
    assert not app.exception
    updated = app.session_state["demo_draft"]
    assert contact_block(updated) is not None
    assert contact_undo_ready(updated, app.session_state["demo_contacts_undo"])
    working = replace(updated, blocks=tuple(
        replace(b, text="Later activity changed by hand")
        if b.key == "activity_summary" else b for b in updated.blocks))
    app.session_state["demo_draft"] = working
    app.run()
    assert not app.exception
    button(app, "Undo contact table update").click().run()
    assert not app.exception
    after_undo = app.session_state["demo_draft"]
    assert contact_block(after_undo) is None
    assert next(b for b in after_undo.blocks if b.key == "activity_summary").text == "Later activity changed by hand"
    assert directory.load_directory(PROFILE.contract).revision == 1
    assert "demo_contacts_undo" not in app.session_state


def test_native_stale_undo_disappears_without_erasing_delivered_contact_edit(monkeypatch, tmp_path):
    app = seed_ui(monkeypatch, tmp_path, draft_with_original(contact=None))
    next(c for c in app.checkbox if c.label.startswith("Replace this report")).check().run()
    button(app, "Use reviewed contact table").click().run()
    assert not app.exception
    after = app.session_state["demo_draft"]
    edited = replace(after, blocks=tuple(
        replace(b, rows=(("Synthetic North", "Manager", "New correction", "", ""),))
        if b.key == "contact_matrix" else b for b in after.blocks))
    app.session_state["demo_draft"] = edited
    app.run()
    assert not app.exception
    assert not any(b.label == "Undo contact table update" for b in app.button)
    assert any("Undo is no longer available" in w.value for w in app.warning)
    assert app.session_state["demo_draft"] == edited
    assert directory.load_directory(PROFILE.contract).revision == 1
