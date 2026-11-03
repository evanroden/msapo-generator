"""The new preview gate adds coverage without rewriting frozen native budgets."""
from pathlib import Path

from test_ci_native_test_budget import parse_jobs, validate_workflow

ROOT = Path(__file__).resolve().parents[1]


def test_preview_mount_gate_preserves_all_existing_native_jobs():
    text = (ROOT / '.github/workflows/adaptive-workspaces.yml').read_text()
    validate_workflow(text)
    job = ''.join(parse_jobs(text)['preview-first-paint'])
    for required in ('timeout-minutes: 30', 'timeout-minutes: 20',
                     'timeout-minutes: 6', '--minutes 5', 'timeout-minutes: 3',
                     'python scripts/qa_preview_first_paint.py', 'if: always()',
                     'playwright==1.58.0', 'chromium webkit',
                     'path: test-artifacts/adaptive-workspaces/preview-first-paint/'):
        assert required in job
    assert 'continue-on-error' not in job
    for path in ('scripts/qa_preview_first_paint.py',
                 'tests/test_preview_first_paint_contract.py'):
        assert text.count("- '" + path + "'") == 2


def test_actual_mount_fixture_reserves_native_notes_and_preserves_callbacks(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_native_loading as loading
    from app import monthly_report_preview_view as preview
    from app import workspace_layout
    import streamlit as st

    # The fixture installs delayed synthetic adapters. Restore process globals
    # after this test; no delay is removed or evaluated by this AppTest.
    monkeypatch.setattr(preview, '_preview_component', preview._preview_component)
    monkeypatch.setattr(workspace_layout, '_adapter', workspace_layout._adapter)
    reserve, text_area = loading.reserve_text_area, st.text_area
    events = []

    def observed_reserve(key, height):
        events.append(('reserve', key, height))
        return reserve(key, height)

    def observed_text_area(label, *args, **kwargs):
        events.append(('text', kwargs.get('key'), kwargs.get('height')))
        return text_area(label, *args, **kwargs)

    monkeypatch.setattr(loading, 'reserve_text_area', observed_reserve)
    monkeypatch.setattr(st, 'text_area', observed_text_area)
    app = AppTest.from_file(str(ROOT / 'tests/fixtures/workspaces/preview_mount_app.py'),
                            default_timeout=30).run()
    assert not app.exception
    assert events == [('reserve', 'activity_notes', 122), ('text', 'activity_notes', 122)]
    note, = app.text_area
    identity = note.proto.id
    assert note.key == 'activity_notes' and note.value == 'Synthetic activity'
    styles = [item.proto.body for item in app.get('html')
              if '.st-key-activity_notes > [data-testid="stSkeleton"]' in item.proto.body]
    assert styles == ['<style>.st-key-activity_notes > [data-testid="stSkeleton"]{height:122px;}</style>']
    note.set_value('Pending human activity note')
    next(b for b in app.button if b.label == 'Clear Activity').click().run()
    assert not app.exception
    assert app.session_state['cleared'] == 1
    assert app.text_area[0].value == 'Pending human activity note'
    assert app.text_area[0].proto.id == identity
    next(b for b in app.button if b.label == 'Render synthetic outputs').click().run()
    assert not app.exception
    assert app.session_state['rendered'] == 1
    assert app.session_state['cleared'] == 1
    assert app.text_area[0].value == 'Pending human activity note'
    assert app.text_area[0].proto.id == identity
