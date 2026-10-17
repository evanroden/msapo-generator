"""Organization notes remain editable and cannot echo an older report's text."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from test_monthly_report_organization_ui import SCRIPT, click


def notes(app):
    return next(widget for widget in app.text_area if widget.label == "Notes included with this part")


def open_editor(monkeypatch, tmp_path, part):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    script = SCRIPT.replace('st.session_state.setdefault("original", original)', '''
from app.monthly_report_model import OrgChartNode
original["org_chart"] = replace(original["org_chart"], asset_hashes=(), extra_tables=(),
    org_nodes=(OrgChartNode("manager", "Synthetic Manager", "Manager"),))
st.session_state.setdefault("original", original)''').replace(
        '"test", assets, _field, editor)', '"test", assets, _field, editor, show_preview=False)')
    app = AppTest.from_string(script, default_timeout=30).run()
    click(app, "Edit contacts" if part == "contact_matrix" else "Edit chart")
    assert not app.exception
    return app


@pytest.mark.parametrize("part", ["contact_matrix", "org_chart"])
@pytest.mark.parametrize("boundary", ["epoch", "source", "newer wording"])
def test_replacement_report_notes_do_not_replay_prior_editor_value(monkeypatch, tmp_path, part, boundary):
    app = open_editor(monkeypatch, tmp_path, part)
    old_key, old_id = notes(app).key, notes(app).proto.id
    blocks = dict(app.session_state["blocks"])
    replacement = replace(blocks[part], text="Newly accepted instructions must remain current.")
    if boundary == "source":
        replacement = replace(replacement, references=("new-source-revision",))
    if boundary == "epoch":
        app.session_state["test_rich_text_epoch"] = "replacement-report-incarnation"
    blocks[part] = replacement
    app.session_state["blocks"] = blocks
    app.run()
    assert not app.exception
    assert app.session_state["blocks"][part] == replacement
    assert notes(app).value == replacement.text
    if boundary == "newer wording":
        assert notes(app).key == old_key and notes(app).proto.id == old_id
    else:
        assert notes(app).key != old_key and notes(app).proto.id != old_id


@pytest.mark.parametrize("part", ["contact_matrix", "org_chart"])
def test_clear_reentry_and_sibling_change_keep_the_notes_native_identity(monkeypatch, tmp_path, part):
    app = open_editor(monkeypatch, tmp_path, part)
    original = app.session_state["blocks"][part]
    key, native_id = notes(app).key, notes(app).proto.id
    notes(app).set_value("").run()
    app.run()
    assert not app.exception
    assert app.session_state["blocks"][part].text == notes(app).value == ""
    assert notes(app).key == key and notes(app).proto.id == native_id
    notes(app).set_value("Reentered current notes.").run()
    app.run()
    assert not app.exception
    result = app.session_state["blocks"][part]
    assert result.text == notes(app).value == "Reentered current notes."
    assert notes(app).key == key and notes(app).proto.id == native_id
    assert result.references == original.references and result.org_nodes == original.org_nodes
    assert result.rows == original.rows and result.extra_tables == original.extra_tables
    assert result.asset_hashes == original.asset_hashes
    assert not list(library._root().glob("directory/**/manifest.json"))


def test_same_action_contact_and_notes_edits_keep_both_and_do_not_write_unlinked_standing_data(monkeypatch, tmp_path):
    app = open_editor(monkeypatch, tmp_path, "contact_matrix")
    before = dict(app.session_state["blocks"])
    key, native_id = notes(app).key, notes(app).proto.id
    next(widget for widget in app.text_input if widget.label == "Name").set_value("Corrected Synthetic Person")
    notes(app).set_value("Same-action corrected contact instructions.").run()
    app.run()
    assert not app.exception and not app.warning
    after = app.session_state["blocks"]
    assert after["contact_matrix"].extra_tables[0].rows == (("Operator", "Corrected Synthetic Person"),)
    assert after["contact_matrix"].text == "Same-action corrected contact instructions."
    assert notes(app).key == key and notes(app).proto.id == native_id
    assert all(value == before[part] for part, value in after.items() if part != "contact_matrix")
    assert not list(library._root().glob("directory/**/manifest.json"))


@pytest.mark.parametrize("decision", ["Apply interrupted edit", "Keep current wording"])
def test_delivered_old_note_requires_explicit_recovery_after_newer_wording(monkeypatch, tmp_path, decision):
    app = open_editor(monkeypatch, tmp_path, "contact_matrix")
    # A genuine native on_change callback retains the version it was rendered
    # against. New canonical wording arrives before that callback is delivered.
    notes(app).set_value("The interrupted operator note.")
    blocks = dict(app.session_state["blocks"])
    newer = replace(blocks["contact_matrix"], text="Keep this newer canonical note.")
    blocks["contact_matrix"] = newer
    app.session_state["blocks"] = blocks
    app.run()
    assert not app.exception
    assert app.session_state["blocks"]["contact_matrix"] == newer
    assert notes(app).value == newer.text
    assert any("earlier edit was interrupted" in warning.value for warning in app.warning)
    assert {code.value for code in app.code} >= {newer.text, "The interrupted operator note."}
    click(app, decision)
    app.run()
    assert not app.exception and not app.warning
    expected = "The interrupted operator note." if decision.startswith("Apply") else newer.text
    assert notes(app).value == app.session_state["blocks"]["contact_matrix"].text == expected
    assert app.session_state["blocks"]["contact_matrix"].extra_tables == newer.extra_tables


def test_delayed_native_note_from_prior_epoch_cannot_change_replacement(monkeypatch, tmp_path):
    app = open_editor(monkeypatch, tmp_path, "org_chart")
    old_key = notes(app).key
    notes(app).set_value("Delayed obsolete note.")
    blocks = dict(app.session_state["blocks"])
    current = replace(blocks["org_chart"], text="New report notes.")
    blocks["org_chart"] = current
    app.session_state["blocks"] = blocks
    app.session_state["test_rich_text_epoch"] = "new-report"
    app.run()
    assert not app.exception and not app.warning
    assert notes(app).key != old_key and notes(app).value == current.text
    assert app.session_state["blocks"]["org_chart"] == current


def test_source_linked_notes_have_no_competing_ordinary_editor(monkeypatch, tmp_path):
    from app.monthly_report_model import DraftParagraph
    app = open_editor(monkeypatch, tmp_path, "contact_matrix")
    blocks = dict(app.session_state["blocks"])
    current = replace(blocks["contact_matrix"],
                      ai_paragraphs=(DraftParagraph("Source-bound wording.", ("fact-1",), ("source:1",)),))
    blocks["contact_matrix"] = current
    app.session_state["blocks"] = blocks
    app.run()
    assert not app.exception
    assert not any(widget.label == "Notes included with this part" for widget in app.text_area)
    assert any("wording and sources editor" in caption.value for caption in app.caption)
    assert app.session_state["blocks"]["contact_matrix"] == current


@pytest.mark.parametrize("part", ["contact_matrix", "org_chart"])
def test_same_action_done_keeps_delivered_note_before_editor_closes(monkeypatch, tmp_path, part):
    app = open_editor(monkeypatch, tmp_path, part)
    original = dict(app.session_state["blocks"])
    notes(app).set_value("Note delivered with Done.")
    click(app, "Done")
    app.run()
    assert not app.exception and not app.text_area
    assert app.session_state["blocks"][part].text == "Note delivered with Done."
    assert all(value == original[key] for key, value in app.session_state["blocks"].items() if key != part)
    click(app, "Edit contacts" if part == "contact_matrix" else "Edit chart")
    assert notes(app).value == "Note delivered with Done."


def test_closed_absent_parts_do_not_create_report_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    script = SCRIPT.replace('st.session_state.setdefault("original", original)',
        'original.pop("contact_matrix"); original.pop("org_chart")\nst.session_state.setdefault("original", original)')
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert app.session_state["blocks"] == app.session_state["original"]
    app.run()
    assert app.session_state["blocks"] == app.session_state["original"]


def test_pending_note_cannot_undo_a_newer_report_omission(monkeypatch, tmp_path):
    app = open_editor(monkeypatch, tmp_path, "contact_matrix")
    notes(app).set_value("The obsolete included note.")
    blocks = dict(app.session_state["blocks"])
    omitted = replace(blocks["contact_matrix"], source="Omit")
    blocks["contact_matrix"] = omitted
    app.session_state["blocks"] = blocks
    app.run()
    assert not app.exception
    assert app.session_state["blocks"]["contact_matrix"] == omitted
    assert notes(app).value == omitted.text
    assert any("earlier edit was interrupted" in warning.value for warning in app.warning)


SCOPED_APP = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_organization_ui import render_organization
from app.monthly_report_directory import CONTACT_SPEC
from app.monthly_report_ui import _field
draft = st.session_state.get('scoped_notes_draft', st.session_state['draft'])
blocks = {block.key:block for block in draft.blocks}
st.session_state['blocks'] = render_organization(draft, blocks, {'contact_matrix':CONTACT_SPEC},
    'scoped_notes', {}, _field, lambda spec, block:block, show_preview=False)
st.session_state['scoped_notes_draft'] = replace(draft, blocks=tuple(st.session_state['blocks'].values()))
'''


@pytest.mark.parametrize("outcome", ["save", "write failure", "concurrent", "report only", "add_contact"])
def test_same_action_linked_contact_and_notes_keep_standing_scope_and_history(monkeypatch, tmp_path, outcome):
    from app import monthly_report_directory as directory
    from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, default_sections
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = ReportProfile("Synthetic Organization", "north", "Synthetic North", (Facility("north", "Synthetic North"),))
    state = directory.save_directory(profile.contract, (
        directory.DirectorySite("north", "Synthetic North", contacts=(directory.DirectoryContact("Manager", "Original Person"),)),
        directory.DirectorySite("south", "Synthetic South", contacts=(directory.DirectoryContact("Manager", "Other Site Person"),)),
    ), expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    other = directory.save_directory("Other Synthetic Contract", (
        directory.DirectorySite("other", "Other Synthetic Site", contacts=(directory.DirectoryContact("Manager", "Unrelated Person"),)),
    ), expected_revision=0,
                                     actor="Synthetic Seeder", confirmed=True)
    block, missing = directory.contact_block(state, profile.facilities)
    assert not missing
    # Automatic first-fill explicitly marks a verified standing copy Library.
    # An otherwise identical This month copy deliberately remains report-only.
    block = replace(block, source="This month" if outcome == "report only" else "Library",
                    text="Original contact instructions.")
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", default_sections(), (block,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    app = AppTest.from_string(SCOPED_APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.session_state["blocks"] = {block.key: block}
    app.run()
    click(app, "Edit contacts")
    assert directory.load_directory(profile.contract) == state
    if outcome == "write failure":
        def fail(*args, **kwargs):
            raise OSError("Synthetic shared write failure")
        monkeypatch.setattr(directory, "save_directory", fail)
    elif outcome == "concurrent":
        newer_site = replace(state.sites[0], contacts=(directory.DirectoryContact("Manager", "Concurrent Person"),))
        state = directory.save_directory(profile.contract, (newer_site, state.sites[1]),
            expected_revision=1, actor="Concurrent Editor", confirmed=True)
    if outcome == "add_contact":
        notes(app).set_value("Same-action current site instructions.")
        click(app, "Add contact")
    else:
        next(widget for widget in app.text_input if widget.label == "Name").set_value("Corrected Current Person")
        notes(app).set_value("Same-action current site instructions.").run()
    assert not app.exception
    result = app.session_state["blocks"][block.key]
    assert result.rows[0][2] == ("Original Person" if outcome == "add_contact" else "Corrected Current Person")
    assert result.text == "Same-action current site instructions."
    latest = directory.load_directory(profile.contract)
    if outcome == "save":
        assert not app.warning
        assert latest.revision == 2 and latest.sites[0].contacts[0].name == "Corrected Current Person"
        assert latest.sites[1] == state.sites[1]
    elif outcome in ("report only", "add_contact"):
        assert not app.warning and latest == state
    else:
        assert app.warning and latest == state
    assert directory.load_directory(other.contract) == other
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
    directory_before = {path: path.read_bytes() for path in (library._root() / "directory").rglob("*.json")}
    app.run()
    assert not app.exception
    assert app.session_state["blocks"][block.key].text == result.text
    assert {path: path.read_bytes() for path in directory_before} == directory_before
    checkpoint = library.save_snapshot(replace(draft, blocks=(app.session_state["blocks"][block.key],)),
        expected_revision=1, entered_editor=draft.prepared_by)
    reopened = AppTest.from_string(SCOPED_APP, default_timeout=30)
    reopened.session_state["draft"] = checkpoint.draft
    reopened.session_state["blocks"] = {item.key: item for item in checkpoint.draft.blocks}
    reopened.run()
    click(reopened, "Edit contacts")
    assert not reopened.exception
    assert notes(reopened).value == result.text
    assert library.load_snapshot_version(profile.contract, profile.key, draft.period, 1) == saved
