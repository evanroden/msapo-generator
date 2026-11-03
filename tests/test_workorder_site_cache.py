"""Work-order evidence must follow the current sites, even under one profile key."""
from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from dataclasses import replace
from app.monthly_report_model import Facility, ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_sources import ingest
from app.monthly_report_upload_ui import render_workorder_metrics
choice = st.radio('Scope', ['North', 'South', 'Both', 'North alias', 'Renamed North'])
north = Facility('north', 'Synthetic North', ('Legacy North',) if choice == 'North alias' else ())
south = Facility('south', 'Synthetic South')
if choice == 'Renamed North':
    north = Facility('north', 'Renamed North')
facilities = (south,) if choice == 'South' else (north, south) if choice == 'Both' else (north,)
profile = replace(synthetic_profiles()[0], facilities=facilities, scope_type='multi_site')
raw = (b'Work Order,Date,Status,Facility\\n'
       b'N-1,2026-09-01,Completed,Synthetic North\\n'
       b'S-1,2026-09-02,Open,Synthetic South\\n'
       b'S-2,2026-09-03,Completed,Synthetic South\\n'
       b'A-1,2026-09-04,Completed,Legacy North\\n'
       b'K-1,2026-09-05,Open,north\\n')
if 'content' not in st.session_state:
    st.session_state.content = ingest(profile, 'synthetic-sites.csv', raw)[0]
blocks = st.session_state.setdefault('blocks', {'activity_summary': ResolvedBlock('activity_summary', 'This month', text='Retain my authored summary.')})
render_workorder_metrics(profile, ReportPeriod(2026, 9), 'site_test', (st.session_state.content,), blocks)
'''


def app_for(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    return AppTest.from_string(APP, default_timeout=20).run()


def counted(app):
    assert not app.exception
    return tuple(app.dataframe[0].value['Work order'])


def test_site_switch_recomputes_totals_and_review_rows(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    original = app.session_state['content']
    blocks = dict(app.session_state['blocks'])
    assert counted(app) == ('N-1', 'K-1')
    app.radio[0].set_value('South').run()
    assert counted(app) == ('S-1', 'S-2')
    assert '2 work orders' in app.info[0].value
    app.radio[0].set_value('Both').run()
    assert counted(app) == ('N-1', 'S-1', 'S-2', 'K-1')
    assert '4 work orders' in app.info[0].value
    app.radio[0].set_value('North').run()
    assert counted(app) == ('N-1', 'K-1')
    assert app.session_state['content'] == original
    assert app.session_state['blocks'] == blocks


def test_site_alias_and_title_changes_invalidate_cached_counts(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    app.radio[0].set_value('North alias').run()
    assert counted(app) == ('N-1', 'A-1', 'K-1')
    app.radio[0].set_value('Renamed North').run()
    assert counted(app) == ('K-1',)
    assert '1 work orders' in app.info[0].value


def test_unchanged_scope_reuses_computation(monkeypatch, tmp_path):
    from app import monthly_report_work_order_csv as metrics
    actual, calls = metrics.work_order_evidence, []
    def measured(*args, **kwargs):
        calls.append(args[2].facilities)
        return actual(*args, **kwargs)
    monkeypatch.setattr(metrics, 'work_order_evidence', measured)
    app = app_for(monkeypatch, tmp_path)
    app.run()
    assert len(calls) == 1
    app.radio[0].set_value('South').run()
    assert len(calls) == 2
    app.run()
    assert len(calls) == 2
