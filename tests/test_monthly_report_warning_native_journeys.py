"""Representative mounted Streamlit warning journeys for #440.

All data are synthetic; tests do not approve source/client content or bypass
preflight. DOM focus and Return-to-Review remain hosted Playwright acceptance.
"""
from streamlit.testing.v1 import AppTest


BASE = """
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, Facility, OrgChartNode, ReportDraft, ReportPeriod,
    ReportProfile, ReportTable, ResolvedBlock, SectionSpec,
)
from app.monthly_report_checks import ReportCheck, preflight
PREFIX = 'warning-native'
def draft(blocks=(), sections=None):
    profile = ReportProfile('Synthetic contract', 'synthetic-site',
                            'Synthetic Site', (Facility('synthetic-site','Synthetic Site'),))
    if sections is None:
        sections = (SectionSpec('activity','2','Activity',(
            BlockSpec('work_orders','table',
                      columns=(ColumnSpec('item','Item'), ColumnSpec('value','Value'))),
        )),)
    return ReportDraft(profile, ReportPeriod(2026,10), 'Synthetic Editor',
                       sections, tuple(blocks))
"""


def action(app, label):
    candidates = [b for b in app.button if b.label == label]
    assert len(candidates) == 1, (label, [b.label for b in app.button])
    return candidates[0]


def test_native_section_recovery_requires_click_and_preserves_excluded_content():
    script = BASE + """
from app.monthly_report_correction_ui import render_structure_and_followup_recovery
if 'warning-native_draft' not in st.session_state:
    excluded = SectionSpec('activity','2','Activity',(
        BlockSpec('work_orders','table',
                  columns=(ColumnSpec('item','Item'),ColumnSpec('value','Value'))),
    ),included=False)
    st.session_state['warning-native_draft'] = draft(
        (ResolvedBlock('work_orders','This month',rows=(('Pump','Maintained'),)),),
        (excluded,))
current = st.session_state['warning-native_draft']
for check in preflight(current):
    render_structure_and_followup_recovery(check,current,PREFIX)
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert not app.session_state["warning-native_draft"].sections[0].included
    action(app, "Include this selected section").click().run()
    assert not app.exception
    updated = app.session_state["warning-native_draft"]
    assert updated.sections[0].included
    assert updated.blocks[0].rows == (("Pump", "Maintained"),)


def test_native_unsafe_table_cell_edit_removes_only_selected_amount():
    script = BASE + """
from app.monthly_report_non_narrative_recovery import edit_active_cell, render_links
if 'warning-native_draft' not in st.session_state:
    table = ReportTable(('Item','Value'),(
        ('Grand total','500'), ('Pump 204','204')), 'original:table:one')
    st.session_state['warning-native_draft'] = draft((
        ResolvedBlock('work_orders','This month',extra_tables=(table,)),))
current = st.session_state['warning-native_draft']
block = current.blocks[0]
updated, editing = edit_active_cell(current,block,PREFIX,lambda key,default:key)
if updated != block:
    current = replace(current,blocks=(updated,))
    st.session_state['warning-native_draft'] = current
st.session_state[PREFIX+'_draft'] = current
for check in preflight(current):
    render_links(check,current,PREFIX)
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    item = action(app, "Correct imported table 1 · row 1 · column 2")
    item.click().run()
    assert not app.exception
    editors = [e for e in app.text_area if e.label == "Exact report table cell"]
    assert len(editors) == 1
    editors[0].set_value("Amount not supplied").run()
    action(app, "Apply correction to this exact cell").click().run()
    assert not app.exception
    saved = app.session_state["warning-native_draft"].blocks[0].extra_tables[0]
    assert saved.columns == ("Item", "Value")
    assert saved.reference == "original:table:one"
    assert saved.rows == (("Grand total", "Amount not supplied"), ("Pump 204", "204"))
    assert not any(c.code == 'pricing' for c in preflight(
        app.session_state["warning-native_draft"]))


def test_native_chart_warning_routes_into_existing_person_field():
    script = BASE + """
from app.monthly_report_org_warning import render_chart_links
from app.monthly_report_visual_ui import edit_org_chart
chart_spec = BlockSpec('org_chart','image_page',True)
chart_section = SectionSpec('organization','1','Organization',(chart_spec,))
if 'warning-native_draft' not in st.session_state:
    st.session_state['warning-native_draft'] = draft((
        ResolvedBlock('org_chart','This month',
            org_nodes=(OrgChartNode('person-1'),)),), (chart_section,))
current = st.session_state['warning-native_draft']
block = current.blocks[0]
changed = edit_org_chart(current,block,PREFIX,{},lambda key,default:key,
                         show_preview=False)
if changed != block:
    current = replace(current,blocks=(changed,))
    st.session_state['warning-native_draft'] = current
st.session_state[PREFIX+'_draft'] = current
for check in preflight(current):
    render_chart_links(check,current,PREFIX)
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    action(app, "Correct chart position 1 · name").click().run()
    assert not app.exception
    fields = [field for field in app.text_input if field.label == "Name"]
    assert len(fields) == 1
    fields[0].set_value("Synthetic engineer").run()
    assert not app.exception
    updated = app.session_state["warning-native_draft"].blocks[0]
    assert updated.org_nodes[0].name == "Synthetic engineer"
    assert not any(check.code == 'org_chart' for check in preflight(
        app.session_state["warning-native_draft"]))


def test_missing_source_route_opens_one_manager_without_accepting_original():
    script = BASE + """
from app.monthly_report_correction_ui import render_source_recovery_links
from app.monthly_report_correction_targets import CorrectionTarget, report_identity
if 'warning-native_draft' not in st.session_state:
    st.session_state['warning-native_draft'] = draft()
current = st.session_state['warning-native_draft']
check = ReportCheck('source_missing','Original missing',True,'work_orders',
    (CorrectionTarget(report_identity(current), source_id='lost-source-a'),))
render_source_recovery_links(check,current,PREFIX)
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    action(app, "Open Manage source files · source lost-source-a").click().run()
    assert not app.exception
    assert app.session_state["warning-native_batch_files_open"] is True
    assert app.session_state["warning-native_evidence_selected"] == ""
    assert app.session_state["warning-native_draft"].sources == ()
