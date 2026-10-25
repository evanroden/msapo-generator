"""Continue into the editor asks the browser to start at its first section once.

The browser side is covered by tests/workspace_navigation_test.cjs and the
Starting report journey in scripts/qa_shared_fixture_testing.py (#299).
"""

import json

from test_cover_import_task_ui import stage_source


def _landing(app):
    return next(json.loads(component.proto.json)["landing"] for component in app.get("bidi_component")
                if component.proto.component_name == "enfra_workspace_layout")


def test_continue_lands_once_at_the_first_section_and_later_reruns_stay_in_place(monkeypatch, tmp_path):
    app, _, _ = stage_source(monkeypatch, tmp_path)
    assert _landing(app) is None, "reviewing a source does not move the reader"
    next(b for b in app.button if b.label == "Continue to this month’s updates").click().run()
    assert not app.exception
    nonce, section = _landing(app)
    assert nonce and section == "monthly_cover"
    app.run()
    assert not app.exception
    assert _landing(app) is None, "an ordinary rerun after the entry keeps the reader in place"
