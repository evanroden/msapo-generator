"""Read-only synthetic fixture diagnostics never supply or repair an upload."""
from hashlib import sha256
from io import BytesIO
from types import MappingProxyType

from scripts.workspace_logo_upload_observations import upload_observation
from app.monthly_report_editor import _signature


def key(selected, revision):
    return 'report_single_logo_' + _signature((selected, revision)) + '_upload'


def test_receipt_binds_exact_selected_record_revision_and_upload_without_consuming():
    raw = b'synthetic-upload-only'
    upload = BytesIO(raw); upload.seek(4)
    state = MappingProxyType({key('sample', 3): upload})
    receipt = upload_observation(state, 'sample', 3)
    assert receipt == {'selected_key': 'sample', 'catalog_revision': 3,
        'upload_widget_key': key('sample', 3), 'upload_present': True,
        'upload_size': len(raw), 'upload_sha256': sha256(raw).hexdigest()}
    assert upload.tell() == 4 and upload.getvalue() == raw
    assert list(state) == [key('sample', 3)]
    assert not upload_observation(state, 'other', 3)['upload_present']
    assert not upload_observation(state, 'sample', 4)['upload_present']


def test_missing_and_empty_upload_are_distinct_observations():
    absent = upload_observation(MappingProxyType({}), 'sample', 3)
    empty = upload_observation(MappingProxyType({key('sample', 3): BytesIO()}), 'sample', 3)
    assert not absent['upload_present'] and absent['upload_sha256'] == ''
    assert empty['upload_present'] and empty['upload_sha256'] == sha256(b'').hexdigest()
    assert absent['upload_size'] == empty['upload_size'] == 0
