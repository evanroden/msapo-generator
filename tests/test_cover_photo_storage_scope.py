"""Report-photo recovery writes cannot approve unrelated stored mutations."""
from copy import deepcopy
import ast
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.qa_cover_photo_controls import unchanged_shared


def record(group, raw=b'older', mtime=10):
    return {'group': group, 'bytes': len(raw), 'mtime_ns': mtime, 'sha256': sha256(raw).hexdigest()}


def transition():
    paths = {role: sha256(role.encode()).hexdigest() for role in ('journal', 'photo', 'object', 'object_lock')}
    digest = sha256(b'new-photo').hexdigest()
    asset = {'reference': digest + '.jpg', 'bytes': 9, 'sha256': digest}
    storage = {'groups': {group: {'files': 1, 'sha256': group} for group in ('history', 'standing', 'assets', 'journal')},
               'entries': {paths['journal']: record('journal'), 'old-asset': record('assets'),
                           'profile': record('standing'), 'other-journal': record('journal')}}
    before = {'scope': 'current-cookie', 'generation': 'current-generation', 'saved_revision': 3,
              'versions': [{'revision': 3}], 'memory_assets': [['old-reference', 5, 'old-hash']],
              'working': {'without_cover': 'same-other-content'}, 'storage': storage}
    after = deepcopy(before)
    after['working']['cover'] = {'assets': [asset]}
    after['memory_assets'].append([asset['reference'], asset['bytes'], asset['sha256']])
    after['storage']['entries'][paths['journal']] = record('journal', b'new-current-journal', 11)
    for role, group in (('photo', 'journal'), ('object', 'assets')):
        after['storage']['entries'][paths[role]] = record(group, b'new-photo', 11)
    after['storage']['entries'][paths['object_lock']] = record('assets', b'', 11)
    after['storage']['groups']['assets'] = {'files': 3, 'sha256': 'expected-new-object-and-lock'}
    return before, after, asset, paths


def test_exact_new_report_photo_and_immutable_object_are_allowed_but_not_shared_settings():
    before, after, asset, paths = transition()
    unchanged_shared(before, after, asset=asset, storage_paths=paths)
    omitted = deepcopy(after)
    omitted['working']['cover']['source'] = 'Omit'
    omitted['storage']['entries'][paths['journal']] = record('journal', b'omitted-current-journal', 12)
    unchanged_shared(before, omitted, asset=asset, storage_paths=paths)


@pytest.mark.parametrize('change', ['old-asset-mtime', 'old-asset-bytes', 'profile', 'other-journal',
    'unrelated-new-object', 'unrelated-new-journal', 'unrelated-new-standing', 'deleted-old-asset',
    'wrong-photo-bytes', 'wrong-object-digest', 'nonempty-lock', 'missing-photo', 'wrong-other-content',
    'wrong-version'])
def test_expected_report_photo_does_not_waive_any_other_storage_or_report_change(change):
    before, after, asset, paths = transition()
    entries = after['storage']['entries']
    if change == 'old-asset-mtime': entries['old-asset']['mtime_ns'] += 1
    elif change == 'old-asset-bytes': entries['old-asset']['sha256'] = 'altered'
    elif change == 'profile': entries['profile']['sha256'] = 'altered'
    elif change == 'other-journal': entries['other-journal']['sha256'] = 'altered'
    elif change.startswith('unrelated-new-'):
        entries['unexpected-path'] = record('standing' if change.endswith('standing') else 'journal' if change.endswith('journal') else 'assets')
    elif change == 'deleted-old-asset': del entries['old-asset']
    elif change == 'wrong-photo-bytes': entries[paths['photo']]['bytes'] += 1
    elif change == 'wrong-object-digest': entries[paths['object']]['sha256'] = 'altered'
    elif change == 'nonempty-lock': entries[paths['object_lock']] = record('assets', b'not-empty')
    elif change == 'missing-photo': del entries[paths['photo']]
    elif change == 'wrong-other-content': after['working']['without_cover'] = 'different'
    elif change == 'wrong-version': after['saved_revision'] = 4
    with pytest.raises((AssertionError, KeyError)):
        unchanged_shared(before, after, asset=asset, storage_paths=paths)


def test_failed_upload_storage_comparison_keeps_the_actual_first_diff():
    source = Path(__file__).resolve().parents[1] / 'scripts/qa_cover_photo_controls.py'
    outer = next(node for node in ast.parse(source.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'exercise_cover_photo')
    capture = next(node for node in outer.body if isinstance(node, ast.FunctionDef) and node.name == 'capture')
    before, after, _, _ = transition()
    before.update(generation='generation', durable=before['working'])
    actual = deepcopy(before)
    actual['storage'].update(scope='current-cookie', generation='generation', live_library_absent=True)
    actual['storage']['entries']['unexpected-upload-write'] = record('standing', b'unexpected')
    stages = []
    namespace = {'evidence': {}, 'stages': stages, 'identity': 'current-cookie', 'author': 'author',
                 'activity': 'activity', 'base': None, 'token': None, 'page': None,
                 'await_state': lambda *a, **kw: actual,
                 'storage_state': lambda *a, **kw: actual['storage']}
    exec(compile(ast.Module(body=[capture], type_ignores=[]), str(source), 'exec'), namespace)
    with pytest.raises(AssertionError, match='display, upload-only or reload'):
        namespace['capture']('uploaded-not-used', same=before)
    assert stages == [{'stage': 'uploaded-not-used', **actual}]
    assert namespace['evidence']['phase'] == 'cover-uploaded-not-used'


def test_actual_cookie_isolated_native_upload_use_omission_and_recovery_scope(tmp_path):
    # This subprocess confines the fixture's process-wide no-network guard.
    # AppTest supplies only uploader bytes; normal native buttons/edits/saves
    # and the actual browser journal/object publisher remain authoritative.
    script = r'''
import json,re,sys
from html import unescape
from io import BytesIO
from pathlib import Path
from streamlit.testing.v1 import AppTest
from app import monthly_report_section_preview_ui as preview, monthly_report_cover_ui as ui
from app import monthly_report_qa_fixture as fixture, monthly_report_testing as testing
from scripts.qa_cover_photo_controls import photograph,selected_asset,unchanged_shared
from scripts.workspace_history_observations import storage_state,photograph_storage_paths,prepared_cover_storage
from app import monthly_report_render_jobs as jobs
jobs.memory_headroom=lambda:400*1024*1024 # Unit admission, not actual cgroup certification.
base=Path(sys.argv[1]);token='d'*32;other='e'*32
preview.render_section_preview=lambda *a,**kw: None
incoming={};original=ui.st.file_uploader
def upload(label,*args,**kwargs):
    current=original(label,*args,**kwargs)
    return incoming.get(label,current)
ui.st.file_uploader=upload
with testing.isolated(other):
    testing.data_dir(base);fixture.prepare('prefill')
foreign=storage_state(base,other)
app=AppTest.from_file('tests/fixtures/workspaces/monthly_app.py',default_timeout=20)
app.session_state['_monthly_dom_app_test_token']=token
def run(action=None):
    (action or app).run()
    assert not app.exception,[x.message for x in app.exception]
def button(label):return next(x for x in app.button if x.label==label)
def capture():
    node=next(x.proto.body for x in app.get('html') if 'data-enfra-history-receipt=' in x.proto.body)
    value=json.loads(unescape(re.search('data-enfra-history-receipt="([^"]+)"',node)[1]))
    result={key:value[key] for key in ('scope','generation','saved_revision','working','durable','versions','memory_assets')}
    result['storage']=storage_state(base,token)
    return result
run();run(button('Load known-value report').click())
for wording in ('First distinct native version.','Second distinct native version.'):
    run(next(x for x in app.text_area if x.label=='Activity summary').set_value(wording))
    run(button('Save shared version').click())
run(next(x for x in app.text_area if x.label=='Activity summary').set_value('Current acknowledged unsaved wording.'))
before=capture();assert before['saved_revision']==3
raw=photograph();item=BytesIO(raw);item.name='synthetic-current-report-cover.png';item.size=len(raw)
incoming['New photograph for this report']=item
run();prepared=capture()
prepared_asset,recovery_records=prepared_cover_storage(base,token,raw)
paths=photograph_storage_paths(base,token,prepared_asset['reference'])
unchanged_shared(before,prepared,asset=prepared_asset,storage_paths=paths,recovery_records=recovery_records,preparing=True)
run(button('Use this photograph').click());used=capture()
asset=selected_asset(used);paths=photograph_storage_paths(base,token,asset['reference'])
unchanged_shared(before,used,asset=asset,storage_paths=paths,recovery_records=recovery_records)
run();assert capture()==used,'Display changed report/storage'
run(button('No cover photograph').click());omitted=capture()
unchanged_shared(before,omitted,asset=asset,storage_paths=paths,recovery_records=recovery_records)
assert selected_asset(omitted)==asset and omitted['working']['cover']['source']=='Omit'
incoming.clear();run();assert capture()==omitted
assert storage_state(base,other)==foreign,'Another namespace changed'
assert not (base/'monthly_reports').exists(),'A live-root fallback was created'
print('PASS actual native photo actions preserve shared/foreign storage and exact old files')
'''
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, '-c', script, str(tmp_path)], cwd=root,
        env={**os.environ, 'EPC_DATA_DIR': str(tmp_path), 'EPC_MONTHLY_DOM_FIXTURE': '1',
             'EPC_MONTHLY_HISTORY_TASK': '1', 'EPC_MONTHLY_DOM_APPTEST': '1',
             'ANTHROPIC_API_KEY': '', 'SMARTSHEET_API_MODE': 'disabled'},
        capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'PASS actual native photo actions' in run.stdout
