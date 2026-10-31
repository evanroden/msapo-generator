"""Registration regression: real pinned server bytes, no installed-runtime edits.

The local candidate is compiled in memory; the installed dependency is untouched.
These tests are allocation/semantic evidence, not the hosted cgroup acceptance.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tracemalloc

import pytest
from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.state import session_state as native
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec

KEY = 'report_cover_photograph_upload_' + 'a' * 20


def uploaded(raw=b'original', cls=UploadedFile):
    return cls(UploadedFileRec('id', 'photo.jpg', 'image/jpeg', raw),
               FileURLs(file_id='id', upload_url='local-upload', delete_url='local-delete'))


def runtime_source():
    from hashlib import sha256
    from scripts import streamlit_cover_upload_copy as repair
    raw = Path(native.__file__).read_bytes()
    if sha256(raw).hexdigest() == repair.REPAIRED_SHA256:
        raw = raw.replace(repair.HELPER, b'', 1).replace(repair.REPAIRED_RETURN, repair.RETURN_COPY, 1)
    assert sha256(raw).hexdigest() == repair.SOURCE_SHA256
    return raw


def candidate():
    from scripts.streamlit_cover_upload_copy import repaired_source
    raw = repaired_source(runtime_source(), installed_version='1.61.1')
    namespace = dict(native.__dict__)
    exec(compile(raw, '<isolated-cover-registration-candidate>', 'exec'), namespace)
    return namespace


def register(namespace, value, *, key=KEY, value_type='file_uploader_state_value'):
    state = namespace['SessionState']()
    ident = '$$ID-cover-' + str(key)
    state._new_widget_state.set_from_value(ident, value)
    metadata = WidgetMetadata(ident, lambda _: None, lambda value: None, value_type)
    result = state.register_widget(metadata, key)
    return result, state, ident


def test_real_registration_avoids_another_64_mib_encoded_buffer():
    namespace = candidate()
    original = uploaded(b'x' * (64 * 1024 * 1024))
    original.seek(17)
    tracemalloc.start()
    try:
        result, state, ident = register(namespace, original)
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024 * 1024, (current, peak)
    assert result.value is not original
    assert result.value.tell() == original.tell() == 17
    assert BytesIO.getvalue(result.value) == BytesIO.getvalue(original)
    assert state[ident] is original


def test_return_still_has_independent_bytes_cursor_metadata_and_alias_graph():
    original = uploaded()
    original.seek(3)
    original.extra = {'nested': ['retained'], 'self': original}
    original.alias = original.extra
    result, state, ident = register(candidate(), original)
    clone = result.value
    assert clone is not original and type(clone) is UploadedFile
    assert clone.tell() == original.tell() == 3
    assert clone.extra is clone.alias and clone.extra is not original.extra
    assert clone.extra['self'] is clone
    assert clone._file_urls == original._file_urls and clone._file_urls is not original._file_urls
    clone.write(b'CHANGED')
    clone.name = 'other.jpg'; clone.size = 1
    clone._file_urls.delete_url = 'other-delete'
    clone.extra['nested'].append('changed')
    assert original.getvalue() == b'original' and original.tell() == 3
    assert original.name == 'photo.jpg' and original.size == 8
    assert original._file_urls.delete_url == 'local-delete'
    assert original.extra['nested'] == ['retained']
    assert state[ident] is original
    original.seek(0); original.write(b'NEW')
    assert clone.getvalue() == b'oriCHANGED'
    clone.close()
    assert original.getvalue() == b'NEWginal'


@pytest.mark.parametrize('case', ['unrelated-key', 'short-suffix', 'uppercase-suffix',
                                  'empty-prefix', 'no-key', 'other-widget', 'subclass',
                                  'list', 'plain-bytesio'])
def test_noncover_or_nonexact_native_types_use_ordinary_deepcopy(case):
    namespace = candidate()
    calls = []
    real_copy = namespace['deepcopy']
    def tracked(value, *args):
        calls.append(value)
        return real_copy(value, *args)
    namespace['deepcopy'] = tracked
    original = uploaded(); key = KEY; value_type = 'file_uploader_state_value'
    if case == 'unrelated-key': key = 'report_source_upload'
    if case == 'short-suffix': key = KEY[:-1]
    if case == 'uppercase-suffix': key = KEY[:-20] + 'A' * 20
    if case == 'empty-prefix': key = '_cover_photograph_upload_' + 'a' * 20
    if case == 'no-key': key = None
    if case == 'other-widget': value_type = 'bytes_value'
    if case == 'subclass':
        class Foreign(UploadedFile): pass
        original = uploaded(cls=Foreign)
    if case == 'list': original = [original]
    if case == 'plain-bytesio': original = BytesIO(b'original')
    result, _, _ = register(namespace, original, key=key, value_type=value_type)
    assert any(value is original for value in calls)
    assert result.value is not original


def test_mutable_exported_buffer_cannot_mutate_returned_original_snapshot():
    original = uploaded()
    view = original.getbuffer()
    try:
        clone = register(candidate(), original)[0].value
        view[0] = ord('X')
        assert original.getvalue() == b'Xriginal'
        assert clone.getvalue() == b'original'
    finally:
        view.release()


def test_malformed_size_metadata_is_not_repaired_into_admission():
    from app.monthly_report_cover_images import read_picture_upload
    original = uploaded(); original.size = 65 * 1024 * 1024
    clone = register(candidate(), original)[0].value
    assert clone.size == original.size
    with pytest.raises(ValueError, match='no larger'):
        read_picture_upload(clone, cover_photo=True)


def test_closed_file_keeps_native_failure():
    original = uploaded(); original.close()
    with pytest.raises(ValueError):
        register(candidate(), original)


def test_two_independent_visitors_keep_full_64_mib_originals_on_repeated_registration():
    namespace = candidate()
    originals = [uploaded(bytes([n]) * (64 * 1024 * 1024)) for n in (120, 121)]
    states = []
    tracemalloc.start()
    try:
        for index, original in enumerate(originals):
            original.file_id = 'visitor-' + str(index)
            key = 'visitor-' + str(index) + KEY
            first, state, ident = register(namespace, original, key=key)
            metadata = state._new_widget_state.widget_metadata[ident]
            second = state.register_widget(metadata, key)
            assert first.value is not second.value and first.value is not original
            assert first.value.file_id == second.value.file_id == original.file_id
            assert BytesIO.getvalue(first.value) is BytesIO.getvalue(original)
            assert BytesIO.getvalue(second.value) is BytesIO.getvalue(original)
            states.append((state, ident, first.value, second.value))
        assert tracemalloc.get_traced_memory()[1] < 1024 * 1024
    finally:
        tracemalloc.stop()
    assert [len(state[ident].getvalue()) for state, ident, _, _ in states] == [64 * 1024 * 1024] * 2
    assert states[0][2].getvalue() != states[1][2].getvalue()


def test_native_disabled_widget_discard_still_precedes_return_copy():
    namespace = candidate()
    state = namespace['SessionState']()
    ident = '$$ID-disabled-' + KEY
    original = uploaded()
    state._new_widget_state.set_from_value(ident, original)
    metadata = WidgetMetadata(ident, lambda _: None, lambda value: None,
                              'file_uploader_state_value', disabled=True)
    result = state.register_widget(metadata, KEY)
    assert result.value is None and result.value_changed
    assert original.getvalue() == b'original'


@pytest.mark.parametrize('already_installed', [False, True])
def test_installer_pins_complete_source_and_changes_only_return_copy(tmp_path, already_installed):
    import stat
    from scripts import streamlit_cover_upload_copy as repair
    path = tmp_path / repair.RELATIVE_PATH
    path.parent.mkdir(parents=True)
    original = runtime_source()
    expected = original.replace(repair.ANCHOR, repair.HELPER + repair.ANCHOR, 1).replace(
        repair.RETURN_COPY, repair.REPAIRED_RETURN, 1)
    path.write_bytes(expected if already_installed else original)
    path.chmod(0o644)
    receipt = repair.patch_cover_upload_copy(tmp_path, installed_version='1.61.1')
    assert receipt['cover_return_copy_on_write'] and receipt['already_patched'] == already_installed
    assert path.read_bytes() == expected
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert repair.patch_cover_upload_copy(tmp_path, installed_version='1.61.1')['already_patched']
    assert not list(path.parent.glob('.pending-enfra-cover-copy-*'))


@pytest.mark.parametrize('version,corruption', [('1.61.2', b''), ('1.61.1', b'\n# other source\n')])
def test_installer_refuses_unknown_version_or_source_without_writes(tmp_path, version, corruption):
    from scripts import streamlit_cover_upload_copy as repair
    path = tmp_path / repair.RELATIVE_PATH
    path.parent.mkdir(parents=True)
    original = runtime_source() + corruption
    path.write_bytes(original)
    with pytest.raises(RuntimeError):
        repair.patch_cover_upload_copy(tmp_path, installed_version=version)
    assert path.read_bytes() == original
    assert not list(path.parent.glob('.pending-enfra-cover-copy-*'))


def test_installer_does_not_overwrite_concurrent_owner_change(tmp_path, monkeypatch):
    from scripts import streamlit_cover_upload_copy as repair
    path = tmp_path / repair.RELATIVE_PATH
    path.parent.mkdir(parents=True)
    original = runtime_source(); path.write_bytes(original)
    concurrent = original + b'\n# concurrent owner\n'
    read_bytes = Path.read_bytes
    reads = 0
    def read(candidate):
        nonlocal reads
        if candidate == path:
            reads += 1
            if reads == 2:
                path.write_bytes(concurrent)
        return read_bytes(candidate)
    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises(RuntimeError, match='changed during installation'):
        repair.patch_cover_upload_copy(tmp_path, installed_version='1.61.1')
    assert path.read_bytes() == concurrent
    assert not list(path.parent.glob('.pending-enfra-cover-copy-*'))


@pytest.mark.parametrize('repaired', [False, True])
def test_two_retained_uploads_register_under_bounded_additional_address_space(repaired):
    """Differential allocation proof, NOT a replacement for the512MiB service.

    The fresh child retains two complete64MiB sources, then admits only32MiB
    additional address space. Native registration exhausts that bounded budget;
    the COW candidate keeps both exact originals and an independent return.
    """
    import json
    import subprocess
    import sys
    code = r'''
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json, os, resource, sys
from pathlib import Path
from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.state import session_state as native
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec
from scripts import streamlit_cover_upload_copy as repair
raw=Path(native.__file__).read_bytes()
if sha256(raw).hexdigest()==repair.REPAIRED_SHA256:
 raw=raw.replace(repair.HELPER,b'',1).replace(repair.REPAIRED_RETURN,repair.RETURN_COPY,1)
assert sha256(raw).hexdigest()==repair.SOURCE_SHA256
if sys.argv[1]=='repaired':raw=repair.repaired_source(raw,installed_version='1.61.1')
namespace=dict(native.__dict__)
exec(compile(raw,'<bounded-native-registration>','exec'),namespace)
files=[UploadedFile(UploadedFileRec(str(n),'synthetic.jpg','image/jpeg',bytes([n])* (64*1024*1024)),FileURLs()) for n in (120,121)]
expected=[sha256(f.getvalue()).hexdigest() for f in files]
state=namespace['SessionState']();key='report_cover_photograph_upload_'+'a'*20;ident='$$ID-cover-'+key
state._new_widget_state.set_from_value(ident,files[1])
metadata=WidgetMetadata(ident,lambda _:None,lambda value:None,'file_uploader_state_value')
current=int(Path('/proc/self/statm').read_text().split()[0])*os.sysconf('SC_PAGE_SIZE')
limit=current+32*1024*1024
resource.setrlimit(resource.RLIMIT_AS,(limit,limit))
try:
 result=state.register_widget(metadata,key)
 assert result.value is not files[1]
 assert result.value.getvalue()==files[1].getvalue()
 result.value.seek(4);assert files[1].tell()==0
 outcome='registered'
except MemoryError:
 outcome='memory-error'
assert [sha256(f.getvalue()).hexdigest() for f in files]==expected
print(json.dumps({'outcome':outcome,'retained_bytes':sum(len(f.getvalue()) for f in files),'additional_address_space':32*1024*1024}))
'''
    run = subprocess.run([sys.executable, '-c', code, 'repaired' if repaired else 'native'],
                         capture_output=True, text=True, timeout=30, check=True)
    result = json.loads(run.stdout)
    assert result['outcome'] == ('registered' if repaired else 'memory-error')
    assert result['retained_bytes'] == 128 * 1024 * 1024
    assert result['additional_address_space'] == 32 * 1024 * 1024


def test_actual_installer_then_fresh_streamlit_bootstrap_needs_no_application_imports(tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import sys
    import streamlit
    from hashlib import sha256
    from scripts import streamlit_cover_upload_copy as repair
    original_root = Path(streamlit.__file__).parent
    original_hash = sha256((original_root / repair.RELATIVE_PATH).read_bytes()).hexdigest()
    # Match installed-package layout: Streamlit intentionally selects developer
    # mode for source checkouts outside site-packages, unlike production.
    cloned = tmp_path / 'isolated-dependency' / 'site-packages' / 'streamlit'
    shutil.copytree(original_root, cloned, ignore=shutil.ignore_patterns('__pycache__'))
    (cloned / repair.RELATIVE_PATH).write_bytes(runtime_source())
    project = Path(__file__).resolve().parents[1]
    # Real entrypoint and direct-import fallback, in a copied dependency only.
    env = {**os.environ, 'PYTHONPATH': str(cloned.parent)}
    run = subprocess.run([sys.executable, str(project / 'scripts' / 'patch_streamlit_frontend.py')],
                         cwd=tmp_path, env=env, check=True, capture_output=True, text=True, timeout=30)
    receipt = json.loads(run.stdout)
    assert receipt['cover_upload_runtime']['source_sha256'] == repair.REPAIRED_SHA256
    assert not receipt['cover_upload_runtime']['already_patched']
    assert receipt['native_trigger_runtime']['string_trigger_coalescing']
    assert sha256((cloned / repair.RELATIVE_PATH).read_bytes()).hexdigest() == repair.REPAIRED_SHA256
    code = r'''
import json, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import streamlit
from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.state.session_state import SessionState
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.uploaded_file_manager import UploadedFile,UploadedFileRec
assert Path(streamlit.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert not any(name=='app' or name.startswith(('app.','scripts.')) for name in sys.modules)
assert streamlit.config.get_option('global.developmentMode') is False
original=UploadedFile(UploadedFileRec('id','synthetic.jpg','image/jpeg',b'original'),FileURLs())
key='report_cover_photograph_upload_'+'a'*20;ident='$$ID-cover-'+key
state=SessionState();state._new_widget_state.set_from_value(ident,original)
result=state.register_widget(WidgetMetadata(ident,lambda _:None,lambda value:None,'file_uploader_state_value'),key)
assert result.value is not original and result.value.getvalue() is original.getvalue()
result.value.write(b'changed!');assert original.getvalue()==b'original'
from streamlit.web import cli
assert callable(cli.main)
print(json.dumps({'bootstrap':'passed','application_imports_required':False}))
'''
    fresh = subprocess.run([sys.executable, '-I', '-c', code, str(cloned.parent)], cwd=tmp_path,
                           check=True, capture_output=True, text=True, timeout=20)
    assert json.loads(fresh.stdout) == {'bootstrap': 'passed', 'application_imports_required': False}
    # The shared installed dependency remains unchanged after both subprocesses.
    assert sha256((original_root / repair.RELATIVE_PATH).read_bytes()).hexdigest() == original_hash


def test_cover_runtime_changes_trigger_unchanged_resource_and_running_service_jobs():
    import re
    text = Path('.github/workflows/cover-photo-resources.yml').read_text()
    trigger_sections = re.split(r'^  (pull_request|push):\n', text.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    events = dict(zip(trigger_sections[1::2], trigger_sections[2::2]))
    for event in ('pull_request', 'push'):
        assert {'scripts/streamlit_cover_upload_copy.py', 'scripts/patch_streamlit_frontend.py',
                'tests/test_cover_recovery_native_copy.py'} <= set(
                    re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))
    assert '  cover-photo-resources:' in text and '  cover-recovery-running-service:' in text
    assert '--memory=512m --memory-swap=512m --cpus=0.5' in text


@pytest.mark.parametrize('explicit_static',[False,True])
def test_cover_cli_installs_runtime_but_keeps_explicit_static_fixture_isolated(monkeypatch,tmp_path,capsys,explicit_static):
    import json
    import sys
    import streamlit
    from scripts import patch_streamlit_frontend as frontend
    from scripts import streamlit_cover_upload_copy as repair
    from scripts import streamlit_string_trigger_coalescing as triggers
    calls=[]
    monkeypatch.setattr(triggers,'patch_script_requests',lambda root,**kw:calls.append(('trigger-runtime',root,kw)) or {'string_trigger_coalescing':True})
    monkeypatch.setattr(frontend,'version',lambda _:'1.61.1')
    monkeypatch.setattr(repair,'patch_cover_upload_copy',lambda root,**kw:calls.append(('cover-runtime',root,kw)) or {'cover_return_copy_on_write':True})
    monkeypatch.setattr(frontend,'patch_bundle',lambda root,**kw:calls.append(('frontend',root,kw)) or {'entry':'unchanged-entry'})
    monkeypatch.setattr(sys,'argv',['patch_streamlit_frontend.py']+(['--static-dir',str(tmp_path)] if explicit_static else []))
    frontend.main()
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['entry']=='unchanged-entry'
    if explicit_static:
        assert [c[0] for c in calls]==['frontend']
        assert 'cover_upload_runtime' not in receipt
        assert 'native_trigger_runtime' not in receipt
    else:
        assert [c[0] for c in calls]==['trigger-runtime','cover-runtime','frontend']
        assert calls[0][1]==calls[1][1]==Path(streamlit.__file__).parent
        assert receipt['native_trigger_runtime']['string_trigger_coalescing']
        assert receipt['cover_upload_runtime']['cover_return_copy_on_write']
