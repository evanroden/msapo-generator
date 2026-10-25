"""No-upload first-display transport for an exact-site standing photograph.

AppTest injects only component viewport/poll receipts and a synthetic converter.
This is not native-browser or real-renderer acceptance. No real report is read.
"""
from concurrent.futures import Future
from threading import BoundedSemaphore

import fitz
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_section_preview_ui as ui
from app.monthly_report_preview import ReportPreview, section_preview_fingerprint
from test_cover_default_diagnosis import _standing_profile, _cover
from test_cover_import_task_ui import current
from test_monthly_report_ui import ROOT, choose_report
from report_preview_test_support import payload


def test_exact_site_photo_first_preview_without_upload_or_rescue_click(monkeypatch, tmp_path):
    state, photograph, original = _standing_profile(monkeypatch, tmp_path / 'store')
    actual_render = ui.render_section_preview
    jobs, rendered, delivery = [], [], {}
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', BoundedSemaphore(1))
    monkeypatch.setattr(ui, 'DEBOUNCE_SECONDS', 0)

    class Worker:
        def submit(self, function, *args):
            future = Future()
            jobs.append((future, function, args))
            return future
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())

    def convert(draft, section, loader):
        assert section == 'cover'
        photo = _cover(draft)
        raw = loader(photo.asset_hashes[0])
        assert raw == original
        rendered.append(raw)
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_image(fitz.Rect(40, 80, 440, 380), stream=raw)
            return ReportPreview(pdf.tobytes(), 1, section_preview_fingerprint(draft, section), draft.period.label)
    monkeypatch.setattr(ui, 'preview_section', convert)

    def with_receipt(draft, section, assets, prefix, **kwargs):
        if section == 'cover' and delivery:
            preview = ui._ordered_preview_state(prefix)
            generation = preview['wanted'].get(section)
            if generation:
                key = prefix + '_preview_surface_' + section
                if delivery.pop('kind') == 'viewport':
                    ui.st.session_state[key] = {'viewport': {'generation': generation, 'visible': True,
                                                            'pages': [0], 'dpi': 96}}
                    ui._viewport_changed(prefix, section, key)
                else:
                    ui.st.session_state[key] = {'poll': {'generation': generation, 'sequence': 1}}
                    ui._poll_changed(prefix, section, key)
        return actual_render(draft, section, assets, prefix, **kwargs)
    monkeypatch.setattr(ui, 'render_section_preview', with_receipt)

    app = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    app.segmented_control[0].set_value('Monthly report').run()
    choose_report(app, state.profile.facilities[0].title)
    assert not app.exception
    draft = current(app)
    assert _cover(draft).asset_hashes == photograph.asset_hashes
    assert library.load_imported_draft(state.profile.contract, state.profile.key) is None
    assert not jobs
    delivery['kind'] = 'viewport'
    app.run()
    assert not app.exception and len(jobs) == 1
    future, function, args = jobs[0]
    future.set_result(function(*args))
    delivery['kind'] = 'poll'
    app.run()
    assert not app.exception
    view = payload(app, 'Cover')
    assert view['ready'] and not view['stale'] and not view['pending']
    assert len(view['pages']) == 1 and rendered == [original]
    assert current(app) == draft
    assert library.read_asset(state.profile.contract, state.profile.key, photograph.asset_hashes[0]) == original
