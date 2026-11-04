"""Temporary Starting Report omissions retain reviewed edits for deliberate reuse.

Word checks include Activity only; unfinished unrelated sections retain their
ordinary required-content preflight when generating the complete report.
"""

from dataclasses import replace
from io import BytesIO
import json

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_start_import import report_file, save_start, start_app


KEEP = "Keep and review"
EDIT = "Edit text or change pictures"
OMIT = "Leave this section out"


def action(app):
    return next(control for control in app.radio
                if control.label == "What would you like to do?")


def period_review(app):
    return next(control for control in app.checkbox
                if control.label == "This work belongs in September 2026")


def continue_button(app):
    return next(control for control in app.button
                if control.label == "Continue to this month’s updates")


def activity(app):
    return next(control for control in app.text_area
                if control.label == "Work completed this month")


def wire_table(app, delta):
    # Deliver the actual native data-editor protocol alongside sibling widgets.
    # An ordinary AppTest run omits that widget's browser value.
    frame = app.dataframe[-1]
    message = app._tree.get_widget_states()
    for previous in list(message.widgets):
        if previous.id == frame.proto.id:
            message.widgets.remove(previous)
    message.widgets.add(id=frame.proto.id, string_value=json.dumps(delta))
    app._run(message)
    assert not app.exception


def omit_then_restore(app, restore=KEEP):
    action(app).set_value(OMIT).run()
    assert not app.exception and not continue_button(app).disabled
    # Let native widget cleanup happen while those editors are not rendered.
    app.run()
    action(app).set_value(restore).run()
    assert not app.exception


def assert_originals(path, original, draft):
    args = (draft.profile.contract, draft.profile.key)
    assert path.read_bytes() == original
    assert library.imported_original(*args).read_bytes() == original
    assert library.load_imported_draft(*args) == draft


def activity_word(draft):
    # Model the existing section inclusion choice without altering source,
    # content, required flags or the final generation/preflight path.
    selected = replace(draft, sections=tuple(
        replace(section, included=section.key == "activity") for section in draft.sections))
    return Document(BytesIO(assemble_docx(
        selected, acknowledged_fingerprint=selected.fingerprint)))


@pytest.mark.parametrize("restore", (KEEP, EDIT), ids=("keep", "edit"))
@pytest.mark.parametrize("paragraphs,correction", (
    (("Inspected the synthetic pump.",),
     "Human correction: the synthetic pump inspection remains pending."),
    (("Inspected the synthetic pump.",), ""),
    (("Inspected the synthetic pump.", "Checked the synthetic fan.",
      "July 2026: Archived synthetic work."),
     "Reviewed pump finding.\n\nReviewed fan finding."),
), ids=("corrected-text", "deliberate-clear", "combined-paragraphs"))
def test_reviewed_text_survives_omission_and_saved_reinclusion(
        monkeypatch, tmp_path, restore, paragraphs, correction):
    path = report_file(tmp_path, month="July 2026", activity=paragraphs, contact=False)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    expected_ids = {item.id for item in inspection.items
                    if item.kind == "text" and item.text in paragraphs
                    and not item.text.startswith("July 2026:")}
    app = start_app(monkeypatch, tmp_path, path)
    action(app).set_value(EDIT).run()
    activity(app).set_value(correction).run()
    assert activity(app).value == correction

    omit_then_restore(app, restore)
    if restore == EDIT:
        assert activity(app).value == correction
    assert not period_review(app).value and continue_button(app).disabled
    period_review(app).check().run()
    draft = save_start(app)
    block = next(block for block in draft.blocks if block.key == "activity_summary")
    assert block.text == correction
    expected_refs = {f"docx:{inspection.sha256}:{identity}" for identity in expected_ids}
    assert set(block.references) == expected_refs
    assert len(block.references) == len(expected_refs)
    assert "Archived synthetic work" not in block.text
    if restore == KEEP and correction:
        output = activity_word(draft)
        visible = [paragraph.text for paragraph in output.paragraphs]
        for line in correction.split("\n\n"):
            if line:
                assert visible.count(line) == 1
        assert not any(paragraph in visible for paragraph in paragraphs)
    assert_originals(path, original, draft)


def test_repeated_omission_cycles_keep_latest_combined_edit_without_old_paragraphs(
        monkeypatch, tmp_path):
    path = report_file(tmp_path, month="July 2026", contact=False, activity=(
        "Inspected the synthetic pump.", "Checked the synthetic fan.",
        "July 2026: Archived synthetic work."))
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    for correction in ("First reviewed aggregate.", "Second reviewed aggregate.\n\nExplicit follow-up."):
        action(app).set_value(EDIT).run()
        activity(app).set_value(correction).run()
        omit_then_restore(app)
        # Reopening after Keep must not append source paragraphs to the aggregate.
        action(app).set_value(EDIT).run()
        assert activity(app).value == correction
    period_review(app).check().run()
    draft = save_start(app)
    block = next(block for block in draft.blocks if block.key == "activity_summary")
    assert block.text == correction
    assert len(block.references) == len(set(block.references)) == 2
    assert_originals(path, original, draft)


@pytest.mark.parametrize("restore", (KEEP, EDIT), ids=("keep", "edit"))
@pytest.mark.parametrize("delta,expected", (
    ({"edited_rows": {"0": {"PM count": "17"}}, "added_rows": [], "deleted_rows": []},
     (("July 2026", "17"), ("August 2026", "8"))),
    ({"edited_rows": {"0": {"PM count": ""}}, "added_rows": [], "deleted_rows": []},
     (("July 2026", ""), ("August 2026", "8"))),
    ({"edited_rows": {}, "added_rows": [{"Month": "Earlier period", "PM count": "0"}],
      "deleted_rows": [0]},
     (("August 2026", "8"), ("Earlier period", "0"))),
), ids=("corrected-cell", "cleared-cell", "added-deleted-zero"))
def test_reviewed_table_survives_omission_saved_reinclusion_and_word_output(
        monkeypatch, tmp_path, restore, delta, expected):
    path = report_file(tmp_path, month="July 2026", contact=False, table=True,
                       activity=("Inspected the synthetic pump.",))
    original = path.read_bytes()
    inspection = inspect_docx(path)
    table_item = next(item for item in inspection.items if item.kind == "table")
    app = start_app(monkeypatch, tmp_path, path)
    action(app).set_value(EDIT).run()
    wire_table(app, delta)
    omit_then_restore(app, restore)
    period_review(app).check().run()
    draft = save_start(app)
    block = next(block for block in draft.blocks if block.key == "work_orders")
    assert len(block.extra_tables) == 1
    table = block.extra_tables[0]
    assert table.columns == ("Month", "PM count") and table.rows == expected
    assert table.reference == f"docx:{inspection.sha256}:{table_item.id}"
    assert table.reference in block.references
    output = activity_word(draft)
    exported = [[tuple(cell.text for cell in row.cells) for row in table.rows]
                for table in output.tables]
    assert [table.columns, *expected] in exported
    assert_originals(path, original, draft)


def test_omitted_edits_never_contribute_until_deliberately_reincluded(monkeypatch, tmp_path):
    path = report_file(tmp_path, month="July 2026", contact=False, table=True,
                       activity=("Inspected the synthetic pump.",))
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    action(app).set_value(EDIT).run()
    activity(app).set_value("Retained correction for a later decision.").run()
    wire_table(app, {"edited_rows": {"0": {"PM count": "17"}},
                     "added_rows": [], "deleted_rows": []})
    action(app).set_value(OMIT).run()
    app.run()
    assert not app.exception and not continue_button(app).disabled
    draft = save_start(app)
    assert not any(block.text or block.rows or block.extra_tables or block.asset_hashes
                   for block in draft.blocks)
    with pytest.raises(ValueError, match="Resolve required block: activity_summary"):
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    assert_originals(path, original, draft)


def test_reinclusion_does_not_reuse_previous_month_confirmation(monkeypatch, tmp_path):
    path = report_file(tmp_path, month="July 2026", contact=False,
                       activity=("Inspected the synthetic pump.",))
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    period_review(app).check().run()
    assert not continue_button(app).disabled
    omit_then_restore(app)
    assert not period_review(app).value and continue_button(app).disabled
    assert path.read_bytes() == original
    assert not library.list_profiles(synthetic_profiles()[0].contract)


@pytest.mark.parametrize("kind", ("text", "table"))
def test_reincluded_edited_prices_still_require_explicit_correction(monkeypatch, tmp_path, kind):
    path = report_file(tmp_path, month="July 2026", contact=False, table=kind == "table",
                       activity=("Inspected the synthetic pump.",))
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    action(app).set_value(EDIT).run()
    if kind == "text":
        activity(app).set_value("Synthetic pump service cost $500.").run()
    else:
        wire_table(app, {"edited_rows": {"0": {"PM count": "$500"}},
                         "added_rows": [], "deleted_rows": []})
    assert any("pricing" in error.value for error in app.error)
    omit_then_restore(app)
    assert any("pricing" in error.value for error in app.error)
    period_review(app).check().run()
    assert continue_button(app).disabled
    action(app).set_value(EDIT).run()
    if kind == "text":
        activity(app).set_value("Synthetic pump service remains pending.").run()
    else:
        wire_table(app, {"edited_rows": {"0": {"PM count": "17"}},
                         "added_rows": [], "deleted_rows": []})
    assert not app.error
    period_review(app).check().run()
    draft = save_start(app)
    assert "$500" not in str(draft.blocks)
    assert_originals(path, original, draft)
