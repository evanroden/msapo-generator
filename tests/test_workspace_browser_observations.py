from types import SimpleNamespace

import pytest

from scripts.workspace_browser_observations import require_synthetic_root, safe_snapshot


def test_observer_fails_closed_outside_explicit_disposable_root(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with pytest.raises(ValueError):
        require_synthetic_root(tmp_path)
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    (tmp_path / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    require_synthetic_root(tmp_path)
    with pytest.raises(ValueError):
        require_synthetic_root(tmp_path / 'other')


def test_safe_snapshot_has_counts_and_hashes_without_report_or_input_values():
    import json
    observed = safe_snapshot({
        'private_draft': SimpleNamespace(fingerprint='a' * 64, text='PRIVATE REPORT'),
        'private_text': 'PRIVATE INPUT',
        'private_ordered_previews': {'queue': {'activity': ('PRIVATE SOURCE',)},
            'running': ('PRIVATE SOURCE',), 'visible': {'activity': True},
            'wanted': {'activity': 'b' * 64, 'PRIVATE CLIENT': 'c' * 64,
                       'training': 'PRIVATE TEXT'}},
    }, {'full_runs': 2, 'preview_fragment_runs': 3, 'sequence': 4})
    assert observed['pending_jobs'] == observed['running_jobs'] == observed['visible_previews'] == 1
    assert observed['draft_hashes'] == ['a' * 64]
    assert observed['requested_hashes'] == {'activity': 'b' * 64}
    assert 'PRIVATE' not in json.dumps(observed)


def test_real_preview_fragment_observer_emits_only_safe_test_metadata(monkeypatch, tmp_path):
    import json
    import re
    from html import unescape
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_section_preview_ui as ui
    # Restore the real production function after this instrumentation test.
    monkeypatch.setattr(ui, '_render_ordered_preview', ui._render_ordered_preview)
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    (tmp_path / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    app = AppTest.from_string('''
import os
import streamlit as st
from scripts.workspace_browser_observations import install_synthetic_observations, emit_snapshot
from app.monthly_report_testing import isolated
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
from app.monthly_report_section_preview_ui import render_section_preview
install_synthetic_observations(os.environ['EPC_DATA_DIR'])
with isolated('a'*32):
    draft=synthetic_draft(synthetic_profiles()[0],ReportPeriod(2026,9))
    render_section_preview(draft,'activity',{},'synthetic')
    emit_snapshot()
''').run()
    assert not app.exception
    def latest():
        values = [match.group(1) for item in app.get('html')
                  if (match := re.search(r'data-enfra-workspace-observations="([^"]+)"', item.proto.body))]
        assert values
        assert not any(item.value.startswith('Synthetic workspace observations: ') for item in app.caption)
        return json.loads(unescape(values[-1]))
    observed = latest()
    assert observed['full_runs'] == observed['preview_mounts'] == 1
    assert observed['preview_fragment_runs'] == observed['pending_jobs'] == 0
    assert observed['running_jobs'] == 0
    assert observed['assembly_lease_active'] is False
    app.run()
    assert not app.exception
    observed = latest()
    assert observed['full_runs'] == observed['preview_mounts'] == 2
