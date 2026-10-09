"""Preview work stays proportional to what a visitor is actually viewing."""
from concurrent.futures import Future
from dataclasses import replace
from threading import BoundedSemaphore

import fitz
from streamlit.testing.v1 import AppTest

from app import monthly_report_section_preview_ui as ui
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_preview import ReportPreview


def report():
    base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    return replace(base, blocks=(
        ResolvedBlock('activity_summary', 'This month', text='Synthetic inspection.'),
        ResolvedBlock('water_reports', 'This month', asset_hashes=('unrelated.png',)),
    ))


def pdf_preview(pages=12):
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f'Synthetic preview page {index + 1}')
        return ReportPreview(doc.tobytes(), pages, 'synthetic-fingerprint', 'September 2026')


def worker(monkeypatch):
    jobs = []
    class Worker:
        def submit(self, fn, *args):
            future = Future()
            jobs.append((future, args))
            return future
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', BoundedSemaphore(1))
    return jobs


def test_build_does_not_rasterize_offscreen_pages_or_keep_base64_html(monkeypatch):
    monkeypatch.setattr(ui, 'preview_section', lambda *args: pdf_preview())
    rasterized = []
    original = ui.preview_page
    monkeypatch.setattr(ui, 'preview_page', lambda preview, index, **kwargs:
                        rasterized.append(index) or original(preview, index, **kwargs))
    slot = BoundedSemaphore(1)
    assert slot.acquire(False)
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    result = ui._build_preview_entry(report(), 'activity', {}, 'Activity')
    assert rasterized == [], 'Offscreen pages must not be rasterized by a conversion job'
    assert 'html' not in result, 'Large base64 pages must not live in session state'
    assert result['pages'] == 12
    assert slot.acquire(False)


def test_obsolete_queued_snapshot_is_discarded_before_expensive_build(monkeypatch):
    jobs = worker(monkeypatch)
    state = {'wanted': {'activity': 'current'},
             'queue': {'activity': ('obsolete', report(), {}, 'Activity')},
             'cache': {}, 'running': None}
    ui._advance_preview_queue(state)
    assert jobs == [], 'Do not assemble a source that is already known to be stale'
    assert not state['queue'] and state['running'] is None


def test_offscreen_report_open_does_not_render_every_section(monkeypatch):
    jobs = worker(monkeypatch)
    app = AppTest.from_string('''
import streamlit as st
from dataclasses import replace
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles, default_sections
from app.monthly_report_section_preview_ui import render_section_preview
value = st.text_area('Activity', 'Synthetic current work')
draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
    sections=tuple(replace(s, included=True) for s in default_sections()), blocks=(ResolvedBlock('activity_summary', 'This month', text=value),))
for section in ('cover', *(section.key for section in draft.sections)):
    render_section_preview(draft, section, {}, 'report_resource_test', deferred=True)
st.button('Save progress')
''', default_timeout=20).run()
    assert not app.exception
    assert jobs == [], 'The browser must report a visible pane before conversion starts'
    assert len(app.get('bidi_component')) == 13
    app.text_area[0].set_value('An edit while previews are offscreen').run()
    assert not app.exception and jobs == []
    assert next(item for item in app.button if item.label == 'Save progress')


def test_valid_preview_eviction_is_not_a_permanent_render_error(monkeypatch):
    monkeypatch.setattr(ui, 'ORDERED_CACHE_BYTES', 120)
    state = {'cache': {str(index): {'fingerprint': str(index), 'html': 'p' * 100}
                       for index in range(3)}}
    ui._bound_ordered_preview_cache(state)
    assert not any('error' in value for value in state['cache'].values())
    assert sum(len(value.get('html', '')) for value in state['cache'].values()) <= 120
