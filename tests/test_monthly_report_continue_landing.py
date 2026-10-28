"""Continue into the editor asks the browser to start at its Activity once.

The browser side is covered by tests/workspace_navigation_test.cjs and the
Starting report journey in scripts/qa_shared_fixture_testing.py (#299).
"""

import json

from test_cover_import_task_ui import stage_source


def _landing(app):
    return next(json.loads(component.proto.json)["landing"] for component in app.get("bidi_component")
                if component.proto.component_name == "enfra_workspace_layout")


def test_continue_lands_once_at_activity_and_later_reruns_stay_in_place(monkeypatch, tmp_path):
    app, _, _ = stage_source(monkeypatch, tmp_path)
    assert _landing(app) is None, "reviewing a source does not move the reader"
    next(b for b in app.button if b.label == "Continue to this month’s updates").click().run()
    assert not app.exception
    nonce, section = _landing(app)
    assert nonce and section == "monthly_activity"
    app.run()
    assert not app.exception
    assert _landing(app) is None, "an ordinary rerun after the entry keeps the reader in place"


def test_landing_falls_back_to_cover_without_reordering_custom_sections(monkeypatch, tmp_path):
    from dataclasses import replace
    from test_cover_import_task_ui import current
    from test_monthly_report_ui import monthly

    from app import monthly_report_guided
    complete = monthly_report_guided.complete_guided_sections
    monkeypatch.setattr(monthly_report_guided, "complete_guided_sections",
        lambda draft: replace(complete(draft), sections=tuple(
            section for section in complete(draft).sections if section.key != "activity")))
    app = monthly(monkeypatch, tmp_path)
    draft = current(app)
    sections = tuple(section for section in draft.sections if section.key != "activity")
    draft_key = next(key for key, value in app.session_state.filtered_state.items()
                     if key.endswith("_draft") and value is draft)
    app.session_state[draft_key] = replace(draft, sections=sections)
    app.session_state[draft_key[:-len("_draft")] + "_land_on_editor"] = True
    app.run()
    assert not app.exception
    assert _landing(app)[1] == "monthly_cover"
    assert current(app).sections == sections
    app.run()
    assert _landing(app) is None
