"""Explicit viewport-event injection for AppTest (not a browser upload test)."""
from concurrent.futures import Future
import json
from threading import BoundedSemaphore

import fitz

from app import monthly_report_section_preview_ui as ui
from app.monthly_report_preview import ReportPreview


def immediate_worker(monkeypatch):
    class Worker:
        def submit(self, fn, *args):
            future = Future()
            try:
                future.set_result(fn(*args))
            except Exception as exc:
                future.set_exception(exc)
            return future
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', BoundedSemaphore(1))
    monkeypatch.setattr(ui, 'DEBOUNCE_SECONDS', 0)


def enable_view(app, prefix, section):
    state = app.session_state[prefix + '_ordered_previews']
    state['visible'][section] = True
    state['page_requests'][section] = {'visible': True, 'pages': (0,), 'dpi': 120}
    state['ready_after'][section] = 0
    app.run()
    assert not app.exception


def payload(app, title=None):
    values = [json.loads(item.proto.json) for item in app.get('bidi_component')
              if item.proto.component_name == 'report_preview_surface']
    return next(value for value in values if title is None or value['title'] == title)


def completed_entry(state, text='Synthetic current page'):
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), text)
        preview = ReportPreview(pdf.tobytes(), 1, 'synthetic', 'September 2026')
    ticket = ui.STORE.put(state['owner'], preview)
    return {'ticket': ticket, 'pages': 1}
