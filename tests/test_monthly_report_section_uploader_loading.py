"""Section uploader reserves its own pinned native footprint before hydration.

Synthetic AppTest evidence is not a native browser geometry pass.
"""
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_native_loading as loading
from app import monthly_report_upload_ui as ui
from test_monthly_report_section_uploads import APP


@pytest.mark.parametrize('destination', [
    'vendor_reports', 'water_reports', 'mbcx_report', 'utility_analysis',
])
def test_section_uploader_reserves_before_same_native_input(monkeypatch, tmp_path, destination):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    reserve, upload = loading.reserve_empty_uploader, ui.st.file_uploader
    events = []

    def observed_reserve(key, label, **kwargs):
        events.append(('reserve', key, label))
        return reserve(key, label, **kwargs)

    def observed_upload(label, *args, **kwargs):
        events.append(('upload', kwargs['key'], label))
        return upload(label, *args, **kwargs)

    monkeypatch.setattr(loading, 'reserve_empty_uploader', observed_reserve)
    monkeypatch.setattr(ui.st, 'file_uploader', observed_upload)
    app = AppTest.from_string(APP, default_timeout=30).run()
    events.clear()
    app.radio[0].set_value(destination).run()
    assert not app.exception
    key = 'synthetic_evidence_section_' + destination + '_upload'
    own = [event for event in events if event[1] == key]
    assert [event[0] for event in own] == ['reserve', 'upload']
    assert own[0][1:] == own[1][1:]
    uploader, = app.get('file_uploader')
    identity = uploader.proto.id
    assert uploader.key == key and identity.endswith('-' + key)
    styles = [node.proto.body for node in app.get('html')
              if '.st-key-' + key + ' > [data-testid="stSkeleton"]' in node.proto.body]
    assert len(styles) == 1
    style = styles[0]
    assert 'height:4.25rem' in style and '(width < 23rem)' in style
    assert 'height:6.15rem' in style
    assert own[0][2] in style
    assert '<input' not in style and 'scroll' not in style and 'position:fixed' not in style
    assert not app.session_state['test_sources'] and not app.session_state['test_blocks']
    events.clear()
    app.run()
    assert not app.exception
    assert app.get('file_uploader')[0].proto.id == identity
    assert not app.session_state['test_sources'] and not app.session_state['test_blocks']
