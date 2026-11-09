"""Removing a position must retain all delivered remaining-position fields."""

from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_org_chart_defaults as charts
from app.monthly_report_model import (
    BlockSpec, OrgChartNode, ReportDraft, ReportPeriod, ResolvedBlock,
    SectionSpec, synthetic_profiles,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_setup import new_month_draft
from app.monthly_report_visuals import org_page


APP = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_organization_ui import render_organization
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
preserve_report_draft_state()
restore_report_draft_state()
current = st.session_state['test_draft']
blocks = {b.key: b for b in current.blocks}
specs = {b.key: b for section in current.sections for b in section.blocks}
updated = render_organization(current, blocks, specs, 'test', {}, _field,
                              lambda spec, block: block, show_preview=False)
st.session_state['test_draft'] = replace(current, blocks=tuple(updated.values()))
preserve_report_draft_state(finalize=True)
'''


def report():
    chart = ResolvedBlock('org_chart', 'Library', text='Keep chart-specific notes.',
        references=('manual-chart-context',), org_nodes=(
            OrgChartNode('manager', 'Synthetic Manager', 'Lead', team='Site A1'),
            OrgChartNode('first', 'Synthetic First', 'Technician', 'manager', 'Site A1'),
            OrgChartNode('last', 'Synthetic Last', 'Engineer', 'manager', 'Site A1'),
        ))
    sibling = ResolvedBlock('activity_summary', 'This month', text='Independent manual activity.')
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor',
        (SectionSpec('organization', '1', 'Organizational Chart',
                     (BlockSpec('org_chart', 'image_page'),)),), (chart, sibling))


def chart(draft):
    return next(b for b in draft.blocks if b.key == 'org_chart')


def click(app, key):
    next(b for b in app.button if b.key == key).click().run()
    assert not app.exception


def start(draft=None, epoch=0):
    app = AppTest.from_string(APP)
    app.session_state['test_draft'] = draft or report()
    app.session_state['test_chart_default_epoch'] = epoch
    app.run()
    assert not app.exception
    click(app, 'test_organization_open_org_chart')
    return app


def widget_key(node, field, epoch=0):
    return f'test_org_person_{node}_{field}' + (f'_chart_default_{epoch}' if epoch else '')


def deliver(app, node, field, value, epoch=0):
    widgets = app.selectbox if field == 'manager' else app.text_input
    next(w for w in widgets if w.key == widget_key(node, field, epoch)).set_value(value)


@pytest.fixture
def empty_default_catalog(monkeypatch):
    # The only seam: optional shared-chart reads. Actual fields, buttons,
    # callbacks, draft updates and registered-field mirror all run unchanged.
    monkeypatch.setattr(charts, 'load_defaults', lambda contract: charts.ChartDefaults())


@pytest.mark.parametrize('removed', ['manager', 'first', 'last'])
@pytest.mark.parametrize('epoch', [0, 4])
@pytest.mark.parametrize('clear', [False, True])
def test_remove_preserves_all_delivered_remaining_fields(empty_default_catalog, removed, epoch, clear):
    original = report()
    app = start(original, epoch)
    expected = []
    for node in chart(original).org_nodes:
        if node.key == removed:
            continue
        values = {'name': '' if clear else 'Updated ' + node.key,
                  'role': 'Retained role ' + node.key if clear else 'Updated role ' + node.key,
                  'team': '' if clear else 'Updated site ' + node.key}
        for field, value in values.items():
            deliver(app, node.key, field, value, epoch)
        expected.append(replace(node, **values,
                                reports_to='' if node.reports_to == removed else node.reports_to))
    next(w for w in app.text_area if w.label == 'Notes included with this part').set_value('Delivered chart notes.')
    click(app, f'test_org_person_{removed}_remove_button')
    current = app.session_state['test_draft']
    assert chart(current).org_nodes == tuple(expected)
    assert chart(current).text == 'Delivered chart notes.'
    assert chart(current).references == chart(original).references
    # A deliberate note edit already marks its content as this month's work.
    assert chart(current).source == 'This month'
    assert current.blocks[1:] == original.blocks[1:]
    assert current.sections == original.sections and current.profile == original.profile
    for node in expected:
        assert app.session_state['report_draft_mirror'][widget_key(node.key, 'name', epoch)] == node.name
    app.run()
    click(app, 'test_organization_close_org_chart')
    click(app, 'test_organization_open_org_chart')
    assert chart(app.session_state['test_draft']).org_nodes == tuple(expected)
    assert chart(original).org_nodes[1].name == 'Synthetic First'


@pytest.mark.parametrize('field,value', [('name', ''), ('role', ''), ('team', ''), ('manager', 'first')])
def test_remove_keeps_deliberate_clear_and_new_reporting_line(empty_default_catalog, field, value):
    original = report()
    app = start(original)
    deliver(app, 'last', field, value)
    click(app, 'test_org_person_manager_remove_button')
    remaining = chart(app.session_state['test_draft']).org_nodes
    changed = 'reports_to' if field == 'manager' else field
    expected = replace(chart(original).org_nodes[-1], reports_to='', **({changed: value} if changed != 'reports_to' else {}))
    if field == 'manager':
        expected = replace(expected, reports_to=value)
    assert remaining[-1] == expected
    assert remaining[0].reports_to == ''


@pytest.mark.parametrize('epoch', [0, 4])
def test_add_preserves_delivered_values_and_existing_identity(empty_default_catalog, epoch):
    original = report()
    app = start(original, epoch)
    deliver(app, 'last', 'name', 'Delivered new name', epoch)
    deliver(app, 'last', 'manager', 'first', epoch)
    click(app, 'test_org_add')
    block = chart(app.session_state['test_draft'])
    assert block.org_nodes[:-2] == chart(original).org_nodes[:-1]
    assert block.org_nodes[-2] == replace(chart(original).org_nodes[-1], name='Delivered new name', reports_to='first')
    assert block.org_nodes[-1] == OrgChartNode('position-1')
    assert block.references == chart(original).references and block.text == chart(original).text


@pytest.mark.parametrize('removed', ['manager', 'first', 'last'])
def test_unchanged_remove_only_deletes_selected_position_and_unlinks_direct_reports(empty_default_catalog, removed):
    original = report()
    app = start(original)
    click(app, f'test_org_person_{removed}_remove_button')
    block = chart(app.session_state['test_draft'])
    assert block == replace(chart(original), org_nodes=tuple(
        replace(node, reports_to='') if node.reports_to == removed else node
        for node in chart(original).org_nodes if node.key != removed))


def test_remove_only_position_keeps_notes_and_rebuild_action(empty_default_catalog):
    original = report()
    original = replace(original, blocks=(replace(chart(original), org_nodes=chart(original).org_nodes[:1]), *original.blocks[1:]))
    app = start(original)
    click(app, 'test_org_person_manager_remove_button')
    assert chart(app.session_state['test_draft']) == replace(chart(original), org_nodes=())
    assert any(b.label == 'Start an editable org chart' for b in app.button)


def template(tmp_path):
    path = tmp_path / 'synthetic-team-chart.docx'
    document = Document()
    document.add_heading('1 Organizational Chart', 1)
    document.add_paragraph('Synthetic chart layout.')
    document.save(path)
    return path


def assert_word_chart(raw, nodes):
    with ZipFile(BytesIO(raw)) as package:
        pictures = [package.read(name) for name in package.namelist() if name.startswith('word/media/')]
    assert org_page(nodes) in pictures


def test_internal_native_word_uses_preserved_delivered_chart(empty_default_catalog, tmp_path):
    original = report()
    app = start(original)
    deliver(app, 'last', 'name', 'Delivered name for Word')
    deliver(app, 'last', 'manager', 'first')
    click(app, 'test_org_person_manager_remove_button')
    current = app.session_state['test_draft']
    expected = (replace(chart(original).org_nodes[1], reports_to=''),
                replace(chart(original).org_nodes[2], name='Delivered name for Word', reports_to='first'))
    path = template(tmp_path)
    original_bytes = path.read_bytes()
    assert_word_chart(_build_native_docx(current, path, section_key='organization'), expected)
    assert path.read_bytes() == original_bytes


def test_public_storage_history_rollover_and_word_keep_chart_edits(tmp_path, monkeypatch):
    """Required real Linux storage/default reads/public Word; no seam or skip."""
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    original = report()
    before = library.save_snapshot(original, expected_revision=0, entered_editor='Synthetic Editor')
    other = replace(original, profile=replace(original.profile, contract='Other Synthetic Contract'))
    library.save_snapshot(other, expected_revision=0, entered_editor='Synthetic Editor')
    app = start(library.load_snapshot(original.profile.contract, original.profile.key, original.period).draft)
    deliver(app, 'last', 'name', 'Delivered name for history')
    click(app, 'test_org_person_manager_remove_button')
    current = app.session_state['test_draft']
    expected = tuple(replace(node, reports_to='', name='Delivered name for history' if node.key == 'last' else node.name)
                     for node in chart(original).org_nodes if node.key != 'manager')
    library.save_snapshot(current, expected_revision=before.revision, entered_editor='Synthetic Editor')
    reopened = library.load_snapshot(original.profile.contract, original.profile.key, original.period).draft
    assert chart(reopened).org_nodes == expected
    assert library.load_snapshot_version(original.profile.contract, original.profile.key, original.period, before.revision).draft == before.draft
    assert library.load_snapshot(other.profile.contract, other.profile.key, other.period).draft == other
    following = new_month_draft(reopened, ReportPeriod(2026, 10))
    assert chart(following).org_nodes == expected
    assert_word_chart(build_native_docx(reopened, template(tmp_path), section_key='organization'), expected)
