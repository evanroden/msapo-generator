"""The compact workspace keeps truthful, scoped, usable history and recovery actions."""

from dataclasses import replace

import pytest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import ReportDraft, ReportPeriod
from test_monthly_report_ui import monthly

PERIOD = ReportPeriod(2026, 9)


@pytest.fixture(autouse=True)
def tracked_history_expander(monkeypatch):
    # AppTest 1.61 does not serialize tracked expander state. Preserve the
    # actual tracked boolean alongside the native widget events it supports.
    from streamlit.testing.v1.element_tree import ElementTree
    original = ElementTree.get_widget_states

    def states(tree):
        values = original(tree)
        existing = {item.id for item in values.widgets}
        for key, identity in tree.session_state._state._key_id_mapper._key_id_mapping.items():
            if key.endswith("_history_open") and identity not in existing:
                values.widgets.add(id=identity, bool_value=bool(tree.session_state[key]))
        return values

    monkeypatch.setattr(ElementTree, "get_widget_states", states)


def open_history(app):
    key = next(key for key in app.session_state.filtered_state if key.endswith("_history_open"))
    app.session_state[key] = True
    app.run()
    assert not app.exception


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def save(app):
    widget(app, "button", "Save shared version").click().run()
    assert not app.exception


def history_tables(app):
    from lxml import html
    tables = []
    for item in app.get('html'):
        body = getattr(item.proto, 'body', '')
        if 'aria-label="Saved report versions"' in body:
            tables.extend(html.fromstring(body).xpath('.//table[@aria-label="Saved report versions"]'))
    return tables


def test_one_help_and_scoped_report_actions_keep_native_fields(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    labels = [item.label for item in app.expander]
    assert labels.count("Help") == 1
    assert "How to use this page" not in labels and "Saving and recovery" not in labels
    assert "Report actions" in labels
    assert sum(item.label == "Prepared by" for item in app.text_input) == 1
    assert widget(app, "button", "Start this report over").disabled
    scope = next(item.value for item in app.caption if "Discard this browser's unfinished changes" in item.value)
    profile = library.load_profile(RRH_CONTRACT, "synthetic-guided").profile
    assert "September 2026" in scope and profile.title in scope
    assert all(site.title in scope for site in profile.facilities)
    assert "original files" in scope and "standing site information" in scope


@pytest.mark.parametrize('first_editor', ['First editor', 'Synthetic <North> [name](https://example.invalid) *Reviewer*'])
def test_history_rows_and_old_version_inspection_keep_current_unsaved_draft(monkeypatch, tmp_path, first_editor):
    app = monthly(monkeypatch, tmp_path)
    widget(app, "text_input", "Prepared by").set_value(first_editor).run()
    widget(app, "text_area", "Activity summary").set_value("First saved wording.").run()
    save(app)
    widget(app, "text_input", "Prepared by").set_value("Second editor").run()
    widget(app, "text_area", "Activity summary").set_value("Second saved wording.").run()
    save(app)
    widget(app, "text_area", "Activity summary").set_value("Unpublished manual wording.").run()
    open_history(app)
    before = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD)
    tables = history_tables(app)
    assert len(tables) == 1
    table = tables[0]
    headings = table.xpath('./thead/tr/th[@scope="col"]/text()')
    assert headings == ['Version', 'Saved', 'Saved by']
    values = [[cell.text_content() for cell in row] for row in table.xpath('./tbody/tr')]
    rows = {heading: [row[index] for row in values] for index, heading in enumerate(headings)}
    assert rows["Version"] == ['2', '1']
    assert rows["Saved by"] == ["Second editor", first_editor]
    assert not table.xpath('.//a|.//img|.//script')
    assert all("UTC" in value for value in rows["Saved"])
    widget(app, "selectbox", "Inspect a saved version").set_value(1).run()
    assert not app.exception
    assert widget(app, "text_area", "Activity summary").value == "Unpublished manual wording."
    assert any("First saved wording." in item.value for item in app.text)
    comparison = next(item for item in app.expander if item.label == "Work completed this month")
    assert any("First saved wording." in item.value for item in comparison.text)
    assert any("Unpublished manual wording." in item.value for item in comparison.text)
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) == before


def test_history_content_keeps_the_preparer_privacy_gate(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    widget(app, "text_input", "Prepared by").set_value("History editor").run()
    widget(app, "text_area", "Activity summary").set_value("Saved attribution-gated content.").run()
    save(app)
    open_history(app)
    widget(app, "text_input", "Prepared by").set_value("").run()
    assert not app.exception
    assert not any(item.label == "Inspect a saved version" for item in app.selectbox)
    assert not history_tables(app)
    assert any("Enter Prepared by" in item.value and "shared report history" in item.value
               for item in app.caption)


def test_closed_history_does_no_reads_and_open_index_is_cached_until_refresh_or_new_head(monkeypatch, tmp_path):
    original = library.snapshot_history
    calls = []

    def observed(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(library, "snapshot_history", observed)
    app = monthly(monkeypatch, tmp_path)
    widget(app, "text_input", "Prepared by").set_value("Index reader").run()
    widget(app, "text_area", "Activity summary").set_value("No history reads for ordinary edits.").run()
    assert calls == []
    open_history(app)
    assert len(calls) == 1
    widget(app, "text_area", "Activity summary").set_value("Open history keeps only a small index.").run()
    assert len(calls) == 1
    widget(app, "button", "Refresh shared history").click().run()
    assert not app.exception and len(calls) == 2
    save(app)
    assert len(calls) == 3


def test_shared_save_failure_keeps_draft_reports_error_and_can_retry(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    widget(app, "text_input", "Prepared by").set_value("Synthetic editor").run()
    widget(app, "text_area", "Activity summary").set_value("Work retained after failed save.").run()
    original = library.save_snapshot

    def fail(*args, **kwargs):
        raise OSError("Synthetic shared disk unavailable")

    monkeypatch.setattr(library, "save_snapshot", fail)
    save(app)
    assert any("Shared version could not be saved" in item.value for item in app.error)
    assert widget(app, "text_area", "Activity summary").value == "Work retained after failed save."
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) is None
    assert not any("Report version saved" in item.value for item in app.success)
    monkeypatch.setattr(library, "save_snapshot", original)
    save(app)
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD).revision == 1


def test_continue_with_draft_acknowledges_revision_without_shared_save(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    widget(app, "text_input", "Prepared by").set_value("My editor").run()
    widget(app, "text_area", "Activity summary").set_value("My current draft.").run()
    draft = next(value for key, value in app.session_state.filtered_state.items()
                 if key.startswith("report_guided_") and key.endswith("_draft")
                 and isinstance(value, ReportDraft))
    newer = library.save_snapshot(replace(draft, prepared_by="Other editor"), expected_revision=0,
                                  entered_editor="Other editor")
    app.run()
    assert widget(app, "button", "Continue with my draft").disabled
    widget(app, "checkbox", "I compared the saved version and want to save my draft as the next version").check().run()
    widget(app, "button", "Continue with my draft").click().run()
    assert not app.exception
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) == newer
    assert widget(app, "text_area", "Activity summary").value == "My current draft."
    save(app)
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD).revision == 2


def test_confirmed_start_over_keeps_shared_history_and_standing_data(monkeypatch, tmp_path):
    from app import web_ui
    token = "d" * 32
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: token)
    app = monthly(monkeypatch, tmp_path)
    widget(app, "text_input", "Prepared by").set_value("Synthetic editor").run()
    widget(app, "text_area", "Activity summary").set_value("Completed version wording.").run()
    save(app)
    saved = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD)
    standing = library.load_profile(RRH_CONTRACT, "synthetic-guided")
    widget(app, "text_area", "Activity summary").set_value("Discard only this unfinished work.").run()
    assert active.load(token, RRH_CONTRACT, "synthetic-guided", PERIOD) is not None
    widget(app, "checkbox", "Discard my unfinished changes for this report").check().run()
    widget(app, "button", "Start this report over").click().run()
    assert not app.exception
    assert widget(app, "text_area", "Activity summary").value == "Completed version wording."
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) == saved
    assert library.load_profile(RRH_CONTRACT, "synthetic-guided") == standing
    assert [v.revision for v in library.snapshot_history(RRH_CONTRACT, "synthetic-guided", PERIOD)[0]] == [1]
