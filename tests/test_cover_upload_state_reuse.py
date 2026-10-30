from copy import deepcopy
from io import BytesIO
import pytest
from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec
from app import monthly_report_cover_ui as ui


def uploaded(raw=b'abc', file_id='id', name='photo.jpg', mime='image/jpeg'):
    return UploadedFile(UploadedFileRec(file_id,name,mime,raw),FileURLs())


def test_verified_current_key_releases_returned_deepcopy(monkeypatch):
    import weakref,gc,tracemalloc
    stored=uploaded(b'x'*(8*1024*1024));stored.seek(2)
    monkeypatch.setattr(ui.st,'session_state',{'current-editor':stored})
    tracemalloc.start()
    try:
        returned=deepcopy(stored);reference=weakref.ref(returned)
        before=tracemalloc.get_traced_memory()[0]
        returned=ui._reuse_cover_upload(returned,'current-editor')
        gc.collect()
        assert returned is stored and reference() is None
        assert before-tracemalloc.get_traced_memory()[0]>7*1024*1024
        assert stored.tell()==2 and BytesIO.getvalue(stored)==b'x'*(8*1024*1024)
    finally:tracemalloc.stop()


@pytest.mark.parametrize('case',['missing','other-key','id','name','mime','data','actual-size','metadata','subclass'])
def test_mismatch_keeps_returned_file_without_state_mutation(monkeypatch,case):
    original=uploaded();returned=deepcopy(original);returned.seek(1)
    candidate=uploaded()
    if case=='id':candidate.file_id='other'
    if case=='name':candidate.name='other.jpg'
    if case=='mime':candidate.type='image/png'
    if case=='data':candidate=uploaded(b'xyz')
    if case=='actual-size':candidate=uploaded(b'abcd');candidate.size=3
    if case=='metadata':candidate.size=2
    if case=='subclass':
        class Foreign(UploadedFile):pass
        candidate=Foreign(UploadedFileRec('id','photo.jpg','image/jpeg',b'abc'),FileURLs())
    state={} if case=='missing' else {('old-editor' if case=='other-key' else 'current-editor'):candidate}
    before=dict(state);monkeypatch.setattr(ui.st,'session_state',state)
    assert ui._reuse_cover_upload(returned,'current-editor') is returned
    assert returned.tell()==1 and state==before
    assert BytesIO.getvalue(returned)==b'abc'


@pytest.mark.parametrize('which',['stored','returned'])
def test_closed_native_object_does_not_make_equivalence_probe_abort(monkeypatch,which):
    stored=uploaded();returned=deepcopy(stored)
    (stored if which=='stored' else returned).close()
    monkeypatch.setattr(ui.st,'session_state',{'current':stored})
    assert ui._reuse_cover_upload(returned,'current') is returned
