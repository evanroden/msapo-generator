"""Source regression only; hosted shell geometry remains required."""
import re
from pathlib import Path
from app.web_ui import CUSTOM_CSS

ROOT = Path(__file__).parents[1]


def test_shared_shell_width_precedes_workspace_and_preserves_gutters():
    css = re.sub(r'/\*.*?\*/', '', CUSTOM_CSS, flags=re.S)
    block = css.split('\n    .block-container {', 1)[1].split('}', 1)[0]
    assert 'max-width: 1680px !important;' in block
    for side in ('left', 'right'):
        assert f'padding-{side}: max(1rem, env(safe-area-inset-{side})) !important;' in block
    assert '1000px' not in block
    source = (ROOT / 'app/web_ui.py').read_text()
    assert source.index('st.markdown(CUSTOM_CSS, unsafe_allow_html=True)') < source.index('st.segmented_control(')


def test_workspace_mount_and_mode_never_resize_the_outer_shell():
    for filename in ('workspace_layout.css', 'workspace_initial.css'):
        css = re.sub(r'/\*.*?\*/', '', (ROOT / 'app' / filename).read_text(), flags=re.S)
        assert not re.search(r'(?:stMainBlockContainer|\.block-container)[^{]*\{[^}]*max-width', css)
    css = (ROOT / 'app/workspace_layout.css').read_text()
    assert 'grid-template-columns:minmax(0,1.12fr) minmax(0,1fr)' in css
    assert '[data-epc-mode="compact"] .epc-workspace-row {grid-template-columns:minmax(0,1fr);}' in css
    assert '[data-epc-mode="book"]' in css and '[data-epc-mode="tabletop"]' in css


def test_browser_matrix_covers_requested_states_and_sidebar_boundary():
    from scripts.qa_workflow_shell_width import WIDTHS, CASES, FIXTURE
    assert WIDTHS == (390, 768, 1024, 1440, 1780, 1781, 1920)
    assert set(CASES) == {'po', 'expense', 'monthly-setup', 'monthly-conflict', 'monthly-ready'}
    compile(FIXTURE, 'synthetic-shell-fixture', 'exec')
    assert 'label=st.segmented_control' in FIXTURE
    assert 'on_click=phase_to' in FIXTURE
    assert 'window.__shellAdapterGate' in FIXTURE
    assert 'monthly_report_library' not in FIXTURE


def test_frame_gate_rejects_wrong_width_and_a_late_width_change():
    import pytest
    from scripts.qa_workflow_shell_width import validate_samples
    good={'maxWidth':'1680px','width':1440,'x':0,'tabX':16,'tabWidth':1408}
    validate_samples([good,dict(good)],good)
    for samples in ([],[{'maxWidth':'1000px','width':1000}],
                    [good,{**good,'width':1000}], [good,{**good,'x':20}],
                    [good,{**good,'tabX':30}], [good,{**good,'tabWidth':1380}]):
        with pytest.raises(AssertionError):validate_samples(samples,good)


def test_browser_network_boundary_is_exact_loopback_only():
    from scripts.qa_workflow_shell_width import local_url
    assert local_url('http://127.0.0.1:8591/media/test')
    assert local_url('ws://127.0.0.1:8591/_stcore/stream',websocket=True)
    for value in ('http://127.0.0.1:8592/','http://user@127.0.0.1:8591/',
                  'https://example.com/','file:///tmp/a','data:text/html,test',
                  'http://127.0.0.1.evil:8591/'):
        assert not local_url(value)


def test_hosted_shell_job_is_separate_mandatory_and_bounded():
    workflow=(ROOT/'.github/workflows/adaptive-workspaces.yml').read_text()
    job=workflow.split('\n  workflow-shell-width:\n',1)[1]
    assert 'timeout-minutes: 50' in job and 'timeout-minutes: 20' in job
    assert 'timeout-minutes: 26' in job and 'timeout-minutes: 3' in job
    assert "ci_native_test_budget.py --minutes 25 <<'NATIVE_TEST'" in job
    assert 'python scripts/qa_workflow_shell_width.py' in job
    assert 'continue-on-error' not in job
    assert 'if:' not in job.split('      - name: Retain first shell-width',1)[0]
    assert 'if: always()' in job
    for path in ('scripts/qa_workflow_shell_width.py','tests/test_workflow_shell_width.py'):
        assert workflow.count("      - '"+path+"'")==2
