"""Native media ownership and transport checks; synthetic bytes only."""
from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest
from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
from streamlit.runtime.media_file_storage import MediaFileStorageError

from app import monthly_report_picture_group as group


@pytest.fixture
def native(monkeypatch):
    import streamlit.runtime.media_file_manager as manager_module
    storage = MemoryMediaFileStorage('/media')
    manager = MediaFileManager(storage)
    monkeypatch.setattr(manager_module, '_get_session_id', lambda: 'synthetic-session')
    monkeypatch.setattr(group.Runtime, 'instance', lambda: SimpleNamespace(media_file_mgr=manager))
    monkeypatch.setattr(group.config, 'get_option', lambda key: 'reports')
    return manager, storage


def png(color):
    out = BytesIO()
    Image.new('RGB', (20, 20), color).save(out, format='PNG')
    return out.getvalue()


def test_original_bytes_stable_url_and_full_fragment_lifetime(native):
    manager, storage = native
    raw = png('blue')
    url = group._media_url(raw, 'image/png', 'picture-review:context:0')
    file_id = url.rsplit('/', 1)[1].split('.')[0]
    assert url.startswith('/reports/media/')
    assert storage.get_file(file_id).content == raw
    # Native fragment runs retain references without clear_session_refs.
    manager.remove_orphaned_files()
    assert storage.get_file(file_id).content == raw
    # Full runs clear then rebuild exactly the current references.
    manager.clear_session_refs('synthetic-session')
    assert group._media_url(raw, 'image/png', 'picture-review:context:0') == url
    manager.remove_orphaned_files()
    assert storage.get_file(file_id).content == raw
    # Replacing this slot does not retain the old picture indefinitely.
    replacement = group._media_url(png('red'), 'image/png', 'picture-review:context:0')
    assert replacement != url
    manager.remove_orphaned_files()
    with pytest.raises(MediaFileStorageError):
        storage.get_file(file_id)
    manager.clear_session_refs('synthetic-session')
    manager.remove_orphaned_files()
    with pytest.raises(MediaFileStorageError):
        storage.get_file(replacement.rsplit('/', 1)[1].split('.')[0])


def test_component_arguments_do_not_contain_image_payload(native, monkeypatch):
    captured = {}
    monkeypatch.setattr(group, '_component', lambda runtime: lambda **kwargs: captured.update(kwargs))
    raw = png('blue') + bytes(4 * 1024 * 1024)
    pictures = [(raw, 'Synthetic picture', 'Selected synthetic site')] * 4
    group.render_group(key='component-nonce', media_scope='context',
                       envelope={'identity': 'exact', 'nonce': 'once'},
                       pictures=pictures, on_change=lambda: None)
    data = captured['data']
    assert len(json.dumps(data)) < 1500
    assert all(set(p) == {'url', 'title', 'context'} for p in data['pictures'])
    assert all(p['url'].startswith('/reports/media/') for p in data['pictures'])


@pytest.mark.parametrize('bad', ['https://external.invalid/x.png', '//external.invalid/x.png', '/other/x.png'])
def test_unexpected_media_routes_fail_closed(native, monkeypatch, bad):
    monkeypatch.setattr(native[0], 'add', lambda *args, **kwargs: bad)
    with pytest.raises(ValueError, match='registered safely'):
        group._media_url(png('blue'), 'image/png', 'picture-review:context:0')


@pytest.mark.parametrize('base, prefix', [('', '/media/'), ('reports', '/reports/media/'), ('/reports/team/', '/reports/team/media/')])
def test_configured_base_path_not_current_multipage_path(native, monkeypatch, base, prefix):
    monkeypatch.setattr(group.config, 'get_option', lambda key: base)
    assert group._media_url(png('blue'), 'image/png', 'picture-review:context:0').startswith(prefix)


def test_native_partial_hash_collision_cannot_substitute_old_bytes(native):
    from streamlit.runtime.memory_media_file_storage import _calculate_file_id
    first = png('blue') + bytes(2 * 1024 * 1024)
    second = bytearray(first)
    second[200_000] = 1  # Outside the native head/middle/tail sample windows.
    second = bytes(second)
    assert _calculate_file_id(first, 'image/png') == _calculate_file_id(second, 'image/png')
    a = group._media_url(first, 'image/png', 'picture-review:context:0')
    b = group._media_url(second, 'image/png', 'picture-review:context:0')
    assert a != b
    assert native[1].get_file(b.rsplit('/', 1)[1].split('.')[0]).content == second
    assert native[1].get_file(a.rsplit('/', 1)[1].split('.')[0]).content == first
    # Even if an old decoded surface submits, receipt proof still rehashes all
    # original bytes, not the native sampled media fingerprint.
    from dataclasses import replace
    from test_monthly_report_picture_batch import sample, request
    from app import monthly_report_picture_batch_ui as batch
    from app.monthly_report_library import asset_reference
    draft, _ = sample(1)
    ref = asset_reference(first, 'png')
    draft = replace(draft, blocks=(replace(draft.blocks[0], asset_hashes=(ref,)),))
    assets = {ref: first}
    req, draft = request(draft, assets)
    assets[ref] = second
    with pytest.raises(ValueError, match='identity'):
        batch._apply(draft, assets, 'epoch', req)
    assert not draft.blocks[0].client_asset_reviews
