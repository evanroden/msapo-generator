"""The additive native acceptance cannot silently skip or repair its own task."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/monthly-simplicity.yml'
HARNESS = ROOT / 'scripts/qa_monthly_simplicity.py'
FIXTURE = ROOT / 'tests/fixtures/workspaces/monthly_simplicity_app.py'


def test_new_gate_runs_on_every_pr_without_weakening_existing_gates():
    workflow = WORKFLOW.read_text()
    assert "on:\n  pull_request:\n  push:\n    branches: [main]" in workflow
    assert "paths:" not in workflow and "workflow_dispatch:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "jobs:\n  monthly-simplicity:" in workflow
    assert "timeout-minutes: 35" in workflow
    assert "continue-on-error" not in workflow and "|| true" not in workflow
    assert "requirements-dev.lock playwright==1.58.0" in workflow
    assert "patch_streamlit_frontend.py" in workflow and "patch_streamlit_date_input.py" in workflow
    assert "install --with-deps chromium webkit" in workflow
    assert "ci_native_test_budget.py --minutes 10" in workflow
    assert "python scripts/qa_monthly_simplicity.py" in workflow
    assert "if: always()" in workflow
    assert "path: test-artifacts/monthly-simplicity/" in workflow
    assert "if-no-files-found: error" in workflow


def test_harness_and_fixture_are_parseable_and_do_not_reuse_autoopening_helper():
    tree = ast.parse(HARNESS.read_text())
    ast.parse(FIXTURE.read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(call.func, ast.Name) and call.func.id == 'open_form' for call in calls)
    assert not any(isinstance(call.func, ast.Attribute) and call.func.attr == 'open_form' for call in calls)
    assert 'monthly_fresh_app.py' in FIXTURE.read_text()
    assert 'runpy' in FIXTURE.read_text()


@pytest.mark.parametrize('address', [
    'https://example.com', 'http://localhost.evil.test:8539/',
    'http://127.0.0.1.evil.test:8539/', 'http://192.168.0.1/',
    'https://msapo-generator.onrender.com', 'file:///tmp/example',
])
def test_browser_route_rejects_non_loopback(address):
    from scripts.qa_monthly_simplicity import allowed_url
    assert not allowed_url(address)


def test_only_the_dedicated_loopback_server_is_allowed():
    from scripts.qa_monthly_simplicity import PORT, URL, allowed_url
    assert allowed_url(URL)
    assert allowed_url(f'http://127.0.0.1:{PORT}/_stcore/health')
    assert not allowed_url(f'http://127.0.0.1:{PORT + 1}/')
    assert not allowed_url(f'http://user:password@127.0.0.1:{PORT}/')
    assert not allowed_url('http://127.0.0.1:not-a-port/')


def clean_errors():
    from scripts.qa_monthly_simplicity import PORT
    return {'installed': True, 'schema': 'enfra-fresh-native-errors-v1',
            'origin': f'http://127.0.0.1:{PORT}', 'limit': 16,
            'total': 0, 'overflow': 0, 'errors': []}


def test_clean_native_error_receipt_is_required():
    from scripts.qa_monthly_simplicity import require_native_errors_clean
    require_native_errors_clean(clean_errors())
    with pytest.raises(AssertionError):
        require_native_errors_clean(None)


@pytest.mark.parametrize('change', [
    {'installed': False}, {'schema': 'unknown'}, {'origin': 'https://example.com'},
    {'total': 1, 'errors': [{'message': 'native error'}]}, {'overflow': 1},
    {'total': False}, {'errors': None}, {'limit': 999},
])
def test_missing_or_nonzero_native_errors_cannot_be_hidden(change):
    from scripts.qa_monthly_simplicity import require_native_errors_clean
    with pytest.raises(AssertionError):
        require_native_errors_clean({**clean_errors(), **change})


def test_native_participant_menu_is_completed_before_addressing_hours():
    import inspect
    from scripts.qa_monthly_simplicity import fill_training
    source = inspect.getsource(fill_training)
    assert source.index('combo.press("Escape")') < source.index('name="Hours (optional)"')
    assert source.index('to_have_attribute("aria-expanded", "false")') < source.index('name="Hours (optional)"')
    assert 'include_hidden' not in source


def test_only_same_origin_canonical_uuid_blob_modules_are_allowed():
    from scripts.qa_monthly_simplicity import PORT, allowed_url
    identity = 'c9bcb2d8-daea-4d24-acb4-bbb63d94d57a'
    base = f'blob:http://127.0.0.1:{PORT}/{identity}'
    assert allowed_url(base)
    for rejected in (
        base + '?x=1', base + '#fragment', base.replace(str(PORT), str(PORT + 1)),
        base.replace('127.0.0.1', 'example.com'), base.replace(identity, 'arbitrary'),
        base.replace('http:', 'ws:'), base.replace('http:', 'https:'),
        base.replace('127.0.0.1', 'user:password@127.0.0.1'),
        'data:text/javascript,export default 1', 'file:///tmp/preview.js',
    ):
        assert not allowed_url(rejected), rejected


def test_existing_adaptive_task_still_dismisses_and_reopens_native_source_tools():
    source = (ROOT / 'scripts/qa_monthly_adaptive.py').read_text()
    done = source.index('name="Done with source files", exact=True)')
    close = source.index('done.click()', done)
    reopen = source.index('manager.click()', close)
    visible = source.index('Read source files, check their pages, or match spreadsheet columns.', reopen)
    assert done < close < reopen < visible
    assert 'native source-manager button opens the broad file tools' in source[visible:]
