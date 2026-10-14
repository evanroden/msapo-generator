from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('archive_audit',Path(__file__).resolve().parent.parent / 'scripts' / 'qa_render_archive_redeploy_readonly.py')
checker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

DIGEST='a'*64
BUNDLE='b'*32
BEFORE='1'*40
AFTER='2'*40

def receipt(phase, *, commit=BEFORE, moment='2026-10-14T10:00:00Z', **changes):
    x={
        'schema':1,'kind':checker.KIND,'phase':phase,'endpoint':checker.ORIGIN,
        'archive_kind':'synthetic','bundle_id':BUNDLE,'archive_sha256':DIGEST,
        'archive_size':13_199_548,'served_commit':commit,'verified_at_utc':moment,
        'read_only_checks':['exact_served_commit_before','selected_archive_identity','downloaded_original_sha256','exact_served_commit_after'],
    }
    return {**x,**changes}

def test_archive_receipt_compare_requires_distinct_served_commits_same_bytes():
    a=receipt('before')
    b=receipt('after',commit=AFTER,moment='2026-10-14T10:01:00Z')
    result=checker.compare(a,b)
    assert result['hash_identical_across_distinct_served_builds']
    assert result['archive_sha256']==DIGEST

@pytest.mark.parametrize('change', [
    {'bundle_id':'c'*32},{'archive_sha256':'f'*64},{'archive_kind':'originals'},
    {'archive_size':13_199_549}, {'served_commit':BEFORE},
    {'verified_at_utc':'2026-10-13T10:00:00Z'},
])
def test_compare_never_accepts_different_data_or_false_redeploy(change):
    with pytest.raises(ValueError):
        checker.compare(receipt('before'), receipt('after',commit=AFTER,moment='2026-10-14T10:01:00Z',**change))

@pytest.mark.parametrize('bad', [
    {'bundle_id':'xxx'}, {'archive_sha256':'a'*63},
    {'endpoint':'https://elsewhere.invalid'}, {'phase':'after'},
    {'read_only_checks':['downloaded_original_sha256']},
    {'verified_at_utc':'2026-10-14T12:00:00-04:00'},
])
def test_invalid_receipt_fails_closed(bad):
    with pytest.raises(ValueError): checker._validated_receipt({**receipt('before'),**bad},'before')

def test_native_source_action_matches_full_id_and_hash():
    prefix=checker.SHELVES['originals']['key_prefix']
    classes=['st-key-'+prefix+BUNDLE+'_'+DIGEST[:16]]
    assert checker._native_archive_id(classes,prefix,BUNDLE[:12],DIGEST)==BUNDLE
    with pytest.raises(AssertionError): checker._native_archive_id(classes,prefix,'c'*12,DIGEST)
    with pytest.raises(AssertionError): checker._native_archive_id(classes,prefix,BUNDLE[:12],'f'*64)
    with pytest.raises(AssertionError): checker._native_archive_id(classes+[classes[0].replace(BUNDLE,'c'*32)],prefix,BUNDLE[:12],DIGEST)


def test_inputs_are_shelf_specific():
    checker._valid_inputs('originals',BUNDLE[:12],DIGEST,88_159_285,BEFORE,'before')
    with pytest.raises(ValueError): checker._valid_inputs('synthetic',BUNDLE[:12],DIGEST,88_159_285,BEFORE,'before')


def test_read_only_receipt_uses_exclusive_file_creation(tmp_path):
    path=tmp_path/'result.json'
    checker._save_new(path,receipt('before'))
    with pytest.raises(FileExistsError): checker._save_new(path,receipt('before'))
    assert path.read_text().count(DIGEST)==1


def test_browser_route_accepts_only_primary_origin():
    class Request:
        def __init__(self,url): self.url=url
    class Route:
        def __init__(self,url):self.request=Request(url);self.action=None
        def continue_(self):self.action='continue'
        def abort(self):self.action='abort'
    rejects=[]
    for url in ['https://msapo-generator.onrender.com/path','data:text/plain,hello','blob:https://msapo-generator.onrender.com/abc']:
        route=Route(url);checker._browser_route(route,rejects);assert route.action=='continue'
    route=Route('https://another-domain.example.com/unauthorized')
    checker._browser_route(route,rejects)
    assert route.action=='abort' and rejects==['https:another-domain.example.com']