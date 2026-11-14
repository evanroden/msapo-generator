"""Source review to Maintenance/Activity publication, with safe editing."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_work_order_review_flow as flow
from app.monthly_report_maintenance_workflow import (
    check_binding, classify_unknown, correct, preview, publish, remove,
)
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock,
    default_sections,
)


def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = ReportProfile('Synthetic contract', 'maintenance-workflow', 'Two sites', (
        Facility('north', 'Example North', ('North',)),
        Facility('south', 'Example South', ('South',))), scope_type='multi_site')
    raw = (b'Work Order,Site,Received Date,Closed Date,Status,Type,Area,Description,Asset Tag,Performed By\n'
           b'N-1,North,2026-08-25,2026-09-02,Closed,Repair,Plant,Inspect pump,P-1,ENFRA\n'
           b'S-1,South,2026-09-03,2026-09-04,Closed,Repair,Roof,Repair valve,V-1,Leased staff\n'
           b'N-2,North,2026-09-05,2026-09-06,Closed,Repair,Plant,Check gauge,G-1,\n'
           b'N-3,North,2026-09-05,2026-09-06,Closed,PM,Plant,Inspect AHU,A-1,ENFRA\n')
    content, _ = sources.ingest(profile, 'synthetic-workorders.csv', raw)
    manual = ReportTable(('Manual',), (('Keep existing',),), 'manual')
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic AM', default_sections(), (
        ResolvedBlock('work_orders', 'This month'),
        ResolvedBlock('service_calls', 'This month', extra_tables=(manual,))),
        synthetic=True, sources=(content.source,))
    bundle = flow.prepare_bundle(draft, content)
    return flow.store_bundle(draft, bundle), content, bundle, raw, manual


def expected_blocks(draft):
    blocks = {b.key: b for b in draft.blocks}
    return {key: blocks.get(key, ResolvedBlock(key, 'This month')).fingerprint
            for key in ('work_orders', 'service_calls')}


def include(draft, bundle, confirmed=True):
    return publish(draft, bundle, expected_revision=flow.revision(bundle),
        expected_blocks=expected_blocks(draft), index=0, confirmed=confirmed)


def test_one_export_routes_onsite_and_vendor_without_guessing(tmp_path, monkeypatch):
    draft, content, bundle, raw, manual = prepared(tmp_path, monkeypatch)
    first = preview(draft, bundle, 0)
    assert [row.work_order for row in first.needs_review] == ['N-2']
    with pytest.raises(ValueError, match='Confirm'):
        classify_unknown(draft, bundle, index=0, site='north', performer='ENFRA onsite', confirmed=False)
    with pytest.raises(ValueError, match='Resolve every candidate'):
        include(draft, bundle)
    classified = classify_unknown(draft, bundle, index=0, site='north', performer='ENFRA onsite', confirmed=True)
    draft = flow.store_bundle(draft, classified, expected_revision=flow.revision(bundle))
    result = include(draft, classified)
    blocks = {b.key: b for b in result.blocks}
    assert blocks['service_calls'].extra_tables[0] == manual
    assert [row[0] for row in blocks['service_calls'].extra_tables[-1].rows] == ['N-1', 'N-2']
    assert [row[0] for row in blocks['work_orders'].extra_tables[-1].rows] == ['S-1']
    assert all('N-3' not in row for block in blocks.values() for table in block.extra_tables for row in table.rows)
    assert sources.source_bytes(profile=result.profile, source=content.source) == raw
    assert check_binding(result) is None
    saved = flow.saved_bundle(result, content.source.id, 'workorders')
    assert include(result, saved) == result
    library.save_profile(result.profile, expected_revision=0, actor='Synthetic AM', confirmed=True)
    library.save_snapshot(result, expected_revision=0)
    reopened = library.load_snapshot(result.profile.contract, result.profile.key, result.period).draft
    assert reopened == result and check_binding(reopened) is None


def test_later_review_or_manual_edit_is_never_silently_overwritten(tmp_path, monkeypatch):
    draft, content, bundle, _, _ = prepared(tmp_path, monkeypatch)
    classified = classify_unknown(draft, bundle, index=0, site='north', performer='ENFRA onsite', confirmed=True)
    draft = flow.store_bundle(draft, classified, expected_revision=flow.revision(bundle))
    result = include(draft, classified)
    saved = flow.saved_bundle(result, content.source.id, 'workorders')
    row = preview(result, saved, 0).candidates[0]
    changed = correct(result, saved, index=0, row_key=row.key,
        changes={'area': 'Changed plant', 'task': row.task, 'tag': row.tag, 'performer': 'ENFRA onsite'})
    pending = flow.store_bundle(result, changed, expected_revision=flow.revision(saved))
    assert check_binding(pending)
    from app.monthly_report_checks import preflight
    assert any(item.code == 'maintenance_source' and item.blocking for item in preflight(pending))
    refreshed = include(pending, changed)
    assert check_binding(refreshed) is None
    service = next(b for b in refreshed.blocks if b.key == 'service_calls')
    assert service.extra_tables[-1].rows[0][2] == 'Example North — Changed plant'
    latest = flow.saved_bundle(refreshed, content.source.id, 'workorders')
    altered_table = replace(service.extra_tables[-1], rows=(('Manual edit', '2026-09-02', '', '', ''),))
    altered = replace(service, extra_tables=(*service.extra_tables[:-1], altered_table))
    edited = replace(refreshed, blocks=tuple(altered if b.key == 'service_calls' else b for b in refreshed.blocks))
    assert check_binding(edited)
    with pytest.raises(ValueError, match='edited or removed'):
        include(edited, latest)
    assert next(b for b in edited.blocks if b.key == 'service_calls').extra_tables[-1] == altered_table
    with pytest.raises(ValueError, match='rows were edited'):
        remove(edited, latest, expected_revision=flow.revision(latest),
               expected_blocks=expected_blocks(edited), index=0, confirmed=True)
    manual_result = remove(edited, latest, expected_revision=flow.revision(latest),
        expected_blocks=expected_blocks(edited), index=0, confirmed=True, keep_manual=True)
    assert next(b for b in manual_result.blocks if b.key == 'service_calls').extra_tables[-1] == altered_table
    assert check_binding(manual_result) is None


def test_visible_source_workspace_requires_performer_confirmation(tmp_path, monkeypatch):
    draft, content, _, _, _ = prepared(tmp_path, monkeypatch)
    script = """
import streamlit as st
from app.monthly_report_work_order_review_ui import render_reviewed_rows
draft = st.session_state['draft']
draft, blocks = render_reviewed_rows(draft, {b.key:b for b in draft.blocks}, 'maintenance-ui', st.session_state['content'])
st.session_state['draft'] = draft
"""
    app = AppTest.from_string(script, default_timeout=20)
    app.session_state['draft'] = draft
    app.session_state['content'] = content
    app.run()
    assert not app.exception
    next(w for w in app.checkbox if w.label == 'Review this file for Maintenance').check().run()
    button = next(b for b in app.button if b.label == 'Include reviewed Maintenance and vendor work')
    assert button.disabled
    next(w for w in app.selectbox if w.label == 'Verified performer for unclassified rows at this site').select('ENFRA onsite')
    next(w for w in app.checkbox if w.label.startswith('I verified this performer')).check()
    next(b for b in app.button if b.label == 'Classify unclassified performers').click().run()
    assert not app.exception
    next(w for w in app.checkbox if w.label.startswith('I reviewed the completed non-PM rows')).check()
    next(b for b in app.button if b.label == 'Include reviewed Maintenance and vendor work').click().run()
    assert not app.exception
    result = app.session_state['draft']
    assert check_binding(result) is None
    assert len(next(b for b in result.blocks if b.key == 'service_calls').extra_tables[-1].rows) == 2
