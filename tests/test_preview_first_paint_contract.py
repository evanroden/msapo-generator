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


def test_preview_mount_reserves_activity_notes_before_native_text_area():
    fixture = (ROOT / 'tests/fixtures/workspaces/preview_mount_app.py').read_text()
    helper = 'from app.monthly_report_native_loading import reserve_text_area'
    reserve = "reserve_text_area('activity_notes', 122)"
    live = "st.text_area('Activity notes', key='activity_notes',"
    assert helper in fixture
    assert fixture.count(reserve) == 1
    assert fixture.count(live) == 1
    assert fixture.index(reserve) < fixture.index(live)
    assert "value='Synthetic activity', height=122)" in fixture
    # Native buttons, delayed mount and callback paths stay intact.
    assert "st.button('Clear Activity', key='clear_activity'," in fixture
    assert "st.button('Render synthetic outputs', key='render_outputs'," in fixture
    assert "st.components.v2.component('synthetic_late_preview'" in fixture
    assert "st.components.v2.component('synthetic_late_workspace'" in fixture
    assert 'class="epc-section-next"' in fixture


def test_preview_mount_native_skeleton_reservation_uses_pinned_height(monkeypatch):
    import streamlit as st
    from app.monthly_report_native_loading import reserve_text_area

    emitted = []
    monkeypatch.setattr(st, 'html', emitted.append)
    monkeypatch.setattr(st, '__version__', '1.61.1')
    reserve_text_area('activity_notes', 122)
    assert emitted == [
        '<style>.st-key-activity_notes > [data-testid="stSkeleton"]{height:122px;}</style>'
    ]
    assert 'scrollTop' not in emitted[0]
    assert '[data-testid="stTextArea"]' not in emitted[0]
