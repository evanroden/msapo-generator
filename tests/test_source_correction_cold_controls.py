"""Cold server-rendered correction affordances, with real synthetic replay.

AppTest cannot mount browser JavaScript. These cases assert the truthful server
state before the handler exists; the separate native journey covers activation.
"""
import pytest

from app import monthly_report_active_work as active
from app import monthly_report_testing as isolation
from app import monthly_report_qa_fixture as fixture
from app.monthly_report_editor import _signature
from app.monthly_report_sources import source_bytes
from test_monthly_report_qa_ui import ACTOR_COOKIE, visit


def replay(monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    next(item for item in app.button if item.label == "Replay synthetic source files").click().run()
    assert not app.exception
    key = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key)) + "_draft"
    return app, key


@pytest.mark.parametrize("kind", ["site", "date"])
def test_cold_source_warning_is_visible_without_an_inactive_link(monkeypatch, tmp_path, kind):
    app, key = replay(monkeypatch, tmp_path)
    draft = app.session_state[key]
    source = next(item for item in draft.sources if item.filename == "synthetic-activity.txt")
    if kind == "site":
        start = "Establish the site scope of synthetic-activity.txt before including its content."
        notices = app.error
    else:
        start = "Confirm the reporting date for synthetic-activity.txt; no date has been established."
        notices = app.warning
    warning, = [item.value for item in notices if item.value.startswith(start)]
    assert "(#source-details-" not in warning, "The cold warning cannot offer a link before its handler exists."
    assert "Loading correction controls" in warning
    assert start in warning
    assert next(item for item in app.button if item.label == "Create Word and PDF").disabled
    # The native correction fields are still the canonical form, not clones.
    assert len([item for item in app.multiselect if item.label == "Source sites"]) >= 1
    assert any('id="source-details-' + source.id + '"' in item.value for item in app.markdown)


def test_loading_display_preserves_scope_block_originals_and_durable_draft(monkeypatch, tmp_path):
    app, key = replay(monkeypatch, tmp_path)
    before = app.session_state[key]
    with isolation.isolated(ACTOR_COOKIE):
        originals = {source.id: source_bytes(before.profile, source) for source in before.sources}
        saved = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    assert saved.draft == before
    app.run()
    assert not app.exception and app.session_state[key] == before
    assert next(item for item in app.button if item.label == "Create Word and PDF").disabled
    with isolation.isolated(ACTOR_COOKIE):
        current = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        assert current == saved
        assert {source.id: source_bytes(before.profile, source) for source in before.sources} == originals
