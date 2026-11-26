"""Two synthetic preview panes exercise the actual registration/scheduler UI."""
from streamlit.testing.v1 import AppTest
from test_monthly_report_section_preview import fake_converter
from report_preview_test_support import immediate_worker, enable_view


def test_two_mounted_sections_prepare_next_pdf_after_current_ready(monkeypatch, tmp_path):
    immediate_worker(monkeypatch)
    calls = fake_converter(monkeypatch, tmp_path)
    app = AppTest.from_string('''
import streamlit as st
from dataclasses import replace
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles, default_sections
from app.monthly_report_section_preview_ui import render_section_preview
base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
text = st.text_area('Activity edit', 'Synthetic current activity')
sections = tuple(s for s in default_sections() if s.key in ('activity', 'water'))
draft = replace(base, sections=sections, blocks=(ResolvedBlock('activity_summary','This month',text=text), ResolvedBlock('water_reports','This month',text='Synthetic water reference')))
for section in sections:
    render_section_preview(draft, section.key, {}, 'synthetic_pair')
''', default_timeout=20).run()
    assert not app.exception and not calls
    enable_view(app, 'synthetic_pair', 'activity')
    app.run()  # Harvest current and admit the immediate successor.
    app.run()  # Harvest successor, never show it as visible by assumption.
    assert not app.exception
    state = app.session_state['synthetic_pair_ordered_previews']
    assert set(state['cache']) == {'activity', 'water'}
    assert len(calls) == 2
    assert not state['visible'].get('water')
    app.text_area[0].set_value('Synthetic newest activity').run()
    app.run(); app.run()
    assert not app.exception
    assert len(calls) == 3, 'Unchanged prepared water PDF remains reusable'
    enable_view(app, 'synthetic_pair', 'water')
    assert len(calls) == 3, 'Navigation reuses the already prepared PDF'


def test_visible_current_pane_keeps_heartbeat_to_harvest_next_pdf(monkeypatch, tmp_path):
    from concurrent.futures import Future
    from app import monthly_report_section_preview_ui as ui
    from report_preview_test_support import payload
    immediate_worker(monkeypatch)
    fake_converter(monkeypatch, tmp_path)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_section_preview_ui import _ordered_preview_state, _render_ordered_preview
state = _ordered_preview_state('heartbeat')
_render_ordered_preview('activity', 'heartbeat', 'Activity')
''', default_timeout=20).run()
    state = app.session_state['heartbeat_ordered_previews']
    state['wanted'] = {'activity':'a', 'water':'w'}
    state['visible'] = {'activity':True}
    state['preparation_order'] = ('activity','water')
    state['requests'] = {'water':('w',None,{},'Water')}
    from report_preview_test_support import completed_entry
    state['cache']['activity'] = {'fingerprint':'a', **completed_entry(state)}
    state['running'] = ('water','w',Future())
    app.run()
    assert not app.exception
    assert payload(app)['pending'] is False
    assert payload(app)['backgroundPending'] is True
    state['running'] = None
    state['queue'] = {'water': ('w', None, {}, 'Water')}
    state['retry_after'] = float('inf')
    app.run()
    assert payload(app)['pending'] is False
    assert payload(app)['backgroundPending'] is True
    state['visible']['activity'] = False
    app.run()
    assert payload(app)['pending'] is False
    assert payload(app)['backgroundPending'] is False


def test_background_heartbeat_does_not_relabel_ready_current_work():
    from app.monthly_report_preview_view import JS
    assert 'data.pending || data.backgroundPending' in JS
    assert 'if (!active || frameworkBusy()' in JS
    assert '2000' in JS


def test_queued_successor_keeps_ready_pane_heartbeat_through_busy_retry():
    from app import monthly_report_section_preview_ui as ui
    state = {'visible': {'activity': True}, 'preparing': ('water',),
             'queue': {'water': object()}, 'retry_after': float('inf')}
    assert ui._background_preparation_pending(state, 'activity')
    assert not ui._background_preparation_pending(state, 'water')
    state['preparing'] = ()
    assert not ui._background_preparation_pending(state, 'activity')


def test_raster_retry_keeps_last_pane_heartbeat_until_ready_or_limited(monkeypatch):
    from app import monthly_report_section_preview_ui as ui
    from app.monthly_report_preview_store import PreviewStore
    from test_monthly_report_preview_store import sample
    cache = PreviewStore()
    monkeypatch.setattr(ui, 'STORE', cache)
    ticket = cache.put('owner', sample(2))
    state = {'owner': 'owner', 'visible': {'activity': True},
             'wanted': {'activity': 'a'}, 'cache': {'activity': {'fingerprint': 'a', 'ticket': ticket}},
             'preparation_order': ('activity',), 'raster_retry_after': float('inf')}
    try:
        assert ui._background_preparation_pending(state, 'activity')
        state['raster_limited'] = {ticket.key}
        assert not ui._background_preparation_pending(state, 'activity')
        state['raster_limited'].clear()
        for _ in range(ticket.pages):
            cache.prepare_next_page('owner', ticket)
        assert not ui._background_preparation_pending(state, 'activity')
    finally:
        cache.close()
