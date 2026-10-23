"""Hosted harness contracts; AppTest remains distinct from native browser proof."""
from html import unescape
import json
from pathlib import Path
import re

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_about_logo_refresh_journey import app_test_process
from scripts.qa_compact_contact_journey import validate_outputs

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'cd' * 16


def receipt(app):
    raw = next(re.search(r'data-enfra-contact-receipt="([^"]+)"', element.proto.body).group(1)
               for element in app.get('html') if 'data-enfra-contact-receipt=' in element.proto.body)
    return json.loads(unescape(raw))


def test_fixture_requires_marked_isolated_storage(monkeypatch,tmp_path):
    from scripts.workspace_contact_observations import setup
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    with pytest.raises((ValueError,OSError)):
        setup(tmp_path,TOKEN)
    assert not (tmp_path / 'monthly_reports').exists()


def test_guided_contact_fixture_receipts_and_real_native_outputs(monkeypatch,tmp_path,app_test_process):
    if not app_test_process:
        return
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE','1')
    monkeypatch.setenv('EPC_MONTHLY_DOM_APPTEST','1')
    monkeypatch.setenv('EPC_MONTHLY_CONTACT_TASK','1')
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    from app import monthly_report_section_preview_ui as preview
    monkeypatch.setattr(preview,'render_section_preview',lambda *args,**kwargs: None)
    app = AppTest.from_file(str(ROOT/'tests/fixtures/workspaces/monthly_app.py'),default_timeout=45)
    app.session_state['_monthly_dom_app_test_token'] = TOKEN
    app.run()
    assert not app.exception
    next(b for b in app.button if b.label=='Create synthetic compact contact report').click().run()
    assert not app.exception
    baseline = receipt(app)
    assert baseline['working'] == baseline['durable']
    assert baseline['working']['contacts']['source'] == 'Library'
    assert len(baseline['working']['vendors']['extra_tables'][0]['rows']) == 3
    app.run()
    assert receipt(app)['working'] == baseline['working']
    next(b for b in app.button if b.label=='Edit contacts').click().run()
    next(b for b in app.button if b.label=='Add contact').click().run()
    for label,value in [('Facility','Demo North'),('Role','Engineer'),('Name','Synthetic Added North'),('Phone','202-555-0174')]:
        next(w for w in app.text_input if w.label==label).set_value(value).run()
        assert not app.exception
    state = receipt(app)
    assert state['working'] == state['durable']
    assert state['directory']['sites'][0]['contacts'][-1]['phone'] == '202-555-0174'
    assert state['working']['vendors'] == baseline['working']['vendors']
    assert state['saved_unchanged'] and state['original_unchanged']
    next(b for b in app.button if b.label=='Close editing').click().run()
    next(b for b in app.button if b.label=='Fail next synthetic shared save before commit').click().run()
    next(b for b in app.button if b.label=='Edit contact').click().run()
    next(w for w in app.text_input if w.label=='Phone').set_value('202-555-0175')
    next(b for b in app.button if b.label=='Remove contact').click().run()
    failed = receipt(app)
    assert len(failed['attempts']) == len(state['attempts']) + 1
    assert failed['directory']['revision'] == state['directory']['revision']
    next(b for b in app.button if b.label=='Retry shared contact correction').click().run()
    final = receipt(app)
    assert final['directory']['revision'] == state['directory']['revision'] + 1
    assert len(final['attempts']) == len(state['attempts']) + 2
    assert final['working']['contacts']['source'] == 'Library'
    next(b for b in app.button if b.label=='Render synthetic native contact outputs').click().run()
    assert not app.exception
    word,pdf = app.session_state['_contact_native_outputs']
    result = validate_outputs(word,pdf,receipt(app)['working']['contacts']['rows'])
    assert result['pdf_pages'] >= 1
    with pytest.raises(AssertionError):
        validate_outputs(word,pdf,[("Wrong site","Wrong role","Wrong name","Wrong phone","")])
    assert not (tmp_path/'monthly_reports').exists()


def test_ci_runs_native_contact_journey_and_retains_first_failure_evidence():
    source = (ROOT/'.github/workflows/adaptive-workspaces.yml').read_text()
    assert 'python scripts/qa_compact_contact_journey.py' in source
    assert 'test-artifacts/compact-contact-journey/' in source
    script = (ROOT/'scripts/qa_compact_contact_journey.py').read_text()
    assert "record['result'] = 'failed'" in script
    assert 'first-failure.png' in script
    assert 'page.expect_download' in script
    assert 'force=True' not in script
    assert 'dispatchEvent' not in script
    assert 'expected.every((v,i) => row[i]===v)' in script
    assert 'expected_contact[index] = value' in script
    assert "current['node'] == native['node']" in script
    assert 'trusted:e.isTrusted' in script
    assert "event['trusted'] is True" in script
    assert "record['pre_reload_native_events'] = native_events" in script


def test_fault_seam_revalidates_namespace_before_any_attempt(monkeypatch, tmp_path):
    from app import monthly_report_testing as testing, monthly_report_library as library
    from app import monthly_report_directory as directory
    from scripts.workspace_contact_observations import install_fault_seam, _folder
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    monkeypatch.setenv('EPC_MONTHLY_CONTACT_TASK', '1')
    marker = tmp_path / 'monthly-dom-synthetic-only.marker'
    marker.write_text('synthetic-monthly-dom-v1')
    calls = []
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', lambda *a, **kw: calls.append(a))
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        folder = _folder(tmp_path, TOKEN)
        folder.mkdir(parents=True)
        (folder / 'setup.json').write_text('{}')
        (folder / 'attempts.json').write_text('[]')
        install_fault_seam(tmp_path, TOKEN)
    with pytest.raises(AssertionError):
        directory.automatically_keep_directory_contact_edits(None, None)
    with testing.isolated('ef' * 16):
        testing.data_dir(tmp_path)
        with pytest.raises(AssertionError):
            directory.automatically_keep_directory_contact_edits(None, None)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        marker.write_text('not-a-synthetic-marker')
        with pytest.raises(ValueError):
            directory.automatically_keep_directory_contact_edits(None, None)
    assert calls == []
    assert (folder / 'attempts.json').read_text() == '[]'
    assert not (tmp_path / 'monthly_reports').exists()
