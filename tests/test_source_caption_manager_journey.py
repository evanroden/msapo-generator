"""Synthetic AppTest controls + actual persisted snapshots; no browser claim."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources, web_ui
from app.monthly_report_asset_review import pending_asset_indexes
from test_monthly_report_source_manager_compact import resolved_app
from test_monthly_report_upload_ui import button, current_draft
from test_monthly_report_ui import ROOT, choose_report


def page(draft):
    return next(block for block in draft.blocks if block.key == "utility_analysis")


def prepared_app(monkeypatch, tmp_path):
    app = resolved_app(monkeypatch, tmp_path)
    next(widget for widget in app.text_input if widget.label == "Prepared by").set_value("Synthetic Reviewer").run()
    assert not app.exception
    return app


def reload_report(monkeypatch, draft, token):
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: token)
    fresh = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    fresh.segmented_control[0].set_value("Monthly report").run()
    choose_report(fresh, draft.profile.facilities[0].title)
    # The new synthetic browser establishes its own preparer before the tested
    # edit journey; a prior shared author's name is not this browser's identity.
    next(widget for widget in fresh.text_input if widget.label == "Prepared by").set_value("Synthetic Reviewer").run()
    assert not fresh.exception
    return fresh


def save_and_reload(monkeypatch, app, expected_revision):
    assert not button(app, "Save shared version").disabled, {
        "prepared_by": current_draft(app).prepared_by,
        "errors": [item.value for item in app.error],
        "warnings": [item.value for item in app.warning],
    }
    button(app, "Save shared version").click().run()
    assert not app.exception
    draft = current_draft(app)
    saved = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert saved is not None and saved.revision == expected_revision, {
        "saved_revision": saved.revision if saved else None,
        "errors": [item.value for item in app.error],
        "warnings": [item.value for item in app.warning],
        "info": [item.value for item in app.info],
    }
    assert page(saved.draft) == page(draft)
    assert saved.draft.sources == draft.sources
    fresh = reload_report(monkeypatch, draft, str(expected_revision + 2) * 32)
    assert page(current_draft(fresh)) == page(saved.draft)
    return fresh, saved


@pytest.mark.parametrize("caption", ("Corrected meter chart caption", ""))
def test_one_include_updates_attached_caption_and_review_then_persists(monkeypatch, tmp_path, caption):
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: "a" * 32)
    app = prepared_app(monkeypatch, tmp_path)
    before = current_draft(app)
    raw = sources.source_bytes(before.profile, before.sources[0])
    button(app, "Manage source files").click().run()
    next(widget for widget in app.text_input if widget.label == "Page caption").set_value(caption)
    button(app, "Include page").click().run()
    assert not app.exception
    current = current_draft(app)
    assert page(current).asset_captions == (caption,), "The attached report page must agree after this one Include action."
    assert page(current).asset_hashes == page(before).asset_hashes
    assert not pending_asset_indexes(page(current), current.sources)
    button(app, "Done with source files").click().run()
    fresh, saved = save_and_reload(monkeypatch, app, 1)
    assert dict(saved.draft.sources[0].captions)[1] == caption
    assert sources.source_bytes(saved.draft.profile, saved.draft.sources[0]) == raw
    button(fresh, "Manage source files").click().run()
    assert next(widget for widget in fresh.text_input if widget.label == "Page caption").value == caption
    assert not any("different captions" in warning.value for warning in fresh.warning)


@pytest.mark.parametrize("keep_report", (True, False))
def test_independent_report_caption_has_explicit_choice_review_and_reload(monkeypatch, tmp_path, keep_report):
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: "b" * 32)
    app = prepared_app(monkeypatch, tmp_path)
    draft = current_draft(app)
    independent = "Deliberate report-only operator caption"
    corrected = "Corrected source caption"
    manual = replace(page(draft), asset_captions=(independent,))
    fixture = replace(draft, blocks=tuple(manual if item.key == manual.key else item for item in draft.blocks))
    # A real shared snapshot is fixture setup for previously edited report work.
    # It is not injected into the active report or presented as a native edit.
    library.save_snapshot(fixture, expected_revision=0, entered_editor="Synthetic previous author")
    app = reload_report(monkeypatch, fixture, "c" * 32)
    button(app, "Manage source files").click().run()
    next(widget for widget in app.text_input if widget.label == "Page caption").set_value(corrected)
    button(app, "Include page").click().run()
    assert not app.exception
    assert page(current_draft(app)).asset_captions == (independent,)
    assert any("different captions" in warning.value for warning in app.warning)
    label = "Keep report caption" if keep_report else "Use source caption in report"
    expected = independent if keep_report else corrected
    button(app, label).click().run()
    assert not app.exception
    current = current_draft(app)
    assert page(current).asset_captions == (expected,)
    assert dict(current.sources[0].captions)[1] == expected
    assert pending_asset_indexes(page(current), current.sources) == (0,), "A conflict choice is not page review."
    assert next(widget for widget in app.text_input if widget.label == "Page caption").value == expected
    button(app, "Include page").click().run()
    assert not app.exception
    assert not pending_asset_indexes(page(current_draft(app)), current_draft(app).sources)
    button(app, "Done with source files").click().run()
    fresh, saved = save_and_reload(monkeypatch, app, 2)
    assert page(saved.draft).asset_captions == (expected,)
    button(fresh, "Manage source files").click().run()
    assert not any("different captions" in warning.value for warning in fresh.warning)


def test_exclude_attached_page_commits_delivered_caption_and_readd_after_reload(monkeypatch, tmp_path):
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: "d" * 32)
    app = prepared_app(monkeypatch, tmp_path)
    before = current_draft(app)
    raw = sources.source_bytes(before.profile, before.sources[0])
    button(app, "Manage source files").click().run()
    next(widget for widget in app.text_input if widget.label == "Page caption").set_value("Caption retained while excluded")
    button(app, "Exclude page").click().run()
    assert not app.exception
    current = current_draft(app)
    assert not page(current).asset_hashes, "Exclude page must remove exactly its attached occurrence."
    assert dict(current.sources[0].captions)[1] == "Caption retained while excluded"
    assert not current.sources[0].selected_pages
    button(app, "Done with source files").click().run()
    fresh, saved = save_and_reload(monkeypatch, app, 1)
    assert sources.source_bytes(saved.draft.profile, saved.draft.sources[0]) == raw
    button(fresh, "Manage source files").click().run()
    button(fresh, "Include page").click().run()
    button(fresh, "Add selected pages and tables to report").click().run()
    assert not fresh.exception
    readded = current_draft(fresh)
    assert page(readded).asset_hashes == page(before).asset_hashes
    assert page(readded).asset_captions == ("Caption retained while excluded",)
    assert not pending_asset_indexes(page(readded), readded.sources)
