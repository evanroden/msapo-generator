"""Water's existing source task is directly reachable without Add files."""
import pytest
from streamlit.testing.v1 import AppTest

from test_monthly_report_section_uploads import APP, section_app
from test_monthly_report_sources import pdf_bytes


def add_file_popovers(app):
    return [element for element in app.get('popover') if element.proto.popover.label == 'Add files']


@pytest.mark.parametrize('destination', ['water_reports', 'mbcx_report', 'utility_analysis', 'vendor_reports'])
def test_empty_section_has_one_uploader_with_stable_identity(tmp_path, monkeypatch, destination):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_string(APP, default_timeout=20).run()
    app.radio[0].set_value(destination).run()
    assert not app.exception
    uploaders = app.get('file_uploader')
    assert len(uploaders) == 1
    assert uploaders[0].proto.id.endswith(f'-synthetic_evidence_section_{destination}_upload')
    # Every section's existing uploader is now directly reachable; no
    # Add files popover may hide saved-source reuse or the first upload.
    assert not add_file_popovers(app)
    assert any(value.value == 'Upload new' for value in app.text)
    assert app.session_state['test_blocks'] == {}
    assert app.session_state['test_sources'] == ()


def test_populated_water_rerun_keeps_source_without_implicit_inclusion(tmp_path, monkeypatch):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(3), label='Water-treatment files')
    app.radio[0].set_value('water_reports').run()
    assert not app.exception
    assert not add_file_popovers(app)
    before = app.session_state['test_sources']
    assert len(before) == 1
    assert not app.session_state['test_blocks']
    app.run()
    assert not app.exception
    assert app.session_state['test_sources'] == before
    assert not app.session_state['test_blocks']
    assert not add_file_popovers(app)
