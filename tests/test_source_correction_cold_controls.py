"""Cold server-rendered correction affordances, with real synthetic replay.

AppTest cannot mount browser JavaScript. These cases assert the truthful server
state before the handler exists; the separate native journey covers activation.
"""
import pytest
from hashlib import sha256
import json

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


def test_fixed_sibling_source_forms_identify_the_current_report_owner(monkeypatch, tmp_path):
    app, key = replay(monkeypatch, tmp_path)
    expected = sha256(key.removesuffix("_draft").encode()).hexdigest()[:24]
    owners = [item.value for item in app.markdown if 'class="enfra-source-correction-owner"' in item.value]
    assert len(owners) == 1
    assert 'data-report-identity="' + expected + '"' in owners[0]
    workspace, = [item for item in app.get('bidi_component')
                  if item.proto.component_name == 'enfra_workspace_layout']
    assert json.loads(workspace.proto.json)['identity'] == expected
    before = app.session_state[key]
    app.run()
    assert not app.exception and app.session_state[key] == before
    assert owners == [item.value for item in app.markdown if 'class="enfra-source-correction-owner"' in item.value]


def test_real_warning_and_source_form_are_both_owned_siblings_outside_workspace(monkeypatch, tmp_path):
    app, key = replay(monkeypatch, tmp_path)
    identity = sha256(key.removesuffix("_draft").encode()).hexdigest()[:24]
    def walk(node, parents=()):
        yield node, parents
        for child in getattr(node, 'children', {}).values():
            yield from walk(child, parents + (node,))
    nodes = list(walk(app._tree))
    workspaces = [node for node, _ in nodes if getattr(getattr(node, 'proto', None), 'id', '').endswith('-epc_workspace_monthly')]
    assert len(workspaces) == 1
    source_markers, warnings = [], []
    for node, parents in nodes:
        if getattr(node, 'type', '') != 'markdown':
            continue
        if 'id="source-details-' in node.value:
            source_markers.append(node)
            assert all(parent is not workspaces[0] for parent in parents)
        if 'class="enfra-source-correction"' in node.value:
            warnings.append(node)
            assert all(parent is not workspaces[0] for parent in parents)
            assert 'data-report-identity="' + identity + '"' in node.value
    assert len(source_markers) == 2 and len(warnings) == 3
    # Binding this display-only trip does not accept a date/site or unblock export.
    assert next(item for item in app.button if item.label == "Create Word and PDF").disabled
