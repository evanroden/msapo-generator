"""Execute the actual locked widget batcher and verify cache-safe publication."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat


@pytest.fixture
def bundle(tmp_path):
    installed = Path(streamlit.__file__).parent / "static"
    scripts = tmp_path / "static" / "js"
    scripts.mkdir(parents=True)
    for name in (compat.INDEX_BUNDLE, compat.DATE_BUNDLE):
        (scripts / name).write_bytes((installed / "static" / "js" / name).read_bytes())
    (tmp_path / "index.html").write_bytes(b'<script src="./static/js/' + compat.INDEX_BUNDLE.encode() + b'"></script>')
    return tmp_path, scripts


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_full_editor_request_dominates_fragments_in_actual_locked_scheduler(bundle):
    root, scripts = bundle
    original = (scripts / compat.INDEX_BUNDLE).read_text()
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    repaired = (scripts / receipt["entry"]).read_text()
    def method(source):
        start = source.index("scheduleFlush(e){")
        return source[start:source.index("registerQueryParamBinding(", start)]
    code = r'''
const {before,after}=JSON.parse(process.argv[1]);
const assert=require('node:assert/strict');
function instance(method){
 const timers=[],sent=[],warnings=[],cleared=[];let resolved=0;
 const target=new Function('qg','setTimeout','return ({'+method+'})')(
  {warn:(...args)=>warnings.push(args)},fn=>timers.push(fn));
 Object.assign(target,{flushScheduled:false,scheduledFragmentId:undefined,hasFragmentIdConflict:false,
  pendingTriggerIds:new Set(['native-action','view-action']),triggerFlushResolvers:[()=>resolved++],
  widgets:{native:'exact edit'},sendUpdateWidgetsMessage(fragment){sent.push({fragment,widgets:{...this.widgets}})},
  deleteWidgetState:id=>cleared.push(id)});
 return {target,timers,sent,warnings,cleared,get resolved(){return resolved}};
}
for(const sequence of [['preview',undefined],[undefined,'preview'],
 ['preview',undefined,'another'],[undefined,'preview',undefined]]){
 const old=instance(before);for(const fragment of sequence)old.target.scheduleFlush(fragment);
 old.timers.shift()();assert.notEqual(old.sent[0].fragment,undefined,'baseline reproduces lost full-run intent');
 const fixed=instance(after);for(const fragment of sequence)fixed.target.scheduleFlush(fragment);
 assert.equal(fixed.timers.length,1);fixed.timers.shift()();
 assert.deepEqual(fixed.sent,[{fragment:undefined,widgets:{native:'exact edit'}}]);
 assert.deepEqual(fixed.cleared,['native-action','view-action']);assert.equal(fixed.resolved,1);
 assert.equal(fixed.target.pendingTriggerIds.size,0);assert.equal(fixed.target.flushScheduled,false);
 assert.equal(fixed.target.scheduledFragmentId,undefined);
}
for(const sequence of [['preview'],['preview','preview'],['preview','another']]){
 for(const method of [before,after]){
  const h=instance(method);for(const fragment of sequence)h.target.scheduleFlush(fragment);
  assert.equal(h.timers.length,1);h.timers.shift()();
  assert.equal(h.sent.length,1);assert.equal(h.sent[0].fragment,'preview');
  assert.equal(h.warnings.length,sequence.includes('another')?1:0);
 }
}
const h=instance(after);h.target.scheduleFlush(undefined);h.timers.shift()();
h.target.widgets.native='next edit';h.target.scheduleFlush('preview');h.timers.shift()();
assert.equal(h.sent.length,2);assert.equal(h.sent[0].fragment,undefined);assert.equal(h.sent[1].fragment,'preview');
assert.equal(h.sent[1].widgets.native,'next edit');assert.equal(h.resolved,1);
'''
    subprocess.run(["node", "-e", code, json.dumps({"before": method(original), "after": method(repaired)})],
                   check=True, capture_output=True, text=True, timeout=15)


def test_content_named_scheduler_entry_preserves_originals_and_is_idempotent(bundle):
    root, scripts = bundle
    before = files(root)
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    assert not receipt["already_patched"] and not receipt["scalar_date"]
    assert (scripts / compat.INDEX_BUNDLE).read_bytes() == before["static/js/" + compat.INDEX_BUNDLE]
    raw = (scripts / receipt["entry"]).read_bytes()
    assert raw == before["static/js/" + compat.INDEX_BUNDLE].replace(compat.ORIGINAL, compat.REPAIRED, 1)
    assert sha256(raw).hexdigest() == receipt["patched_entry_sha256"]
    assert receipt["entry"].encode() in (root / "index.html").read_bytes()
    snapshot = files(root)
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert files(root) == snapshot


@pytest.mark.parametrize("first_date", [False, True])
def test_scalar_date_composes_with_scheduler_and_cannot_be_downgraded(bundle, first_date):
    root, scripts = bundle
    if first_date:
        # Exact output identity of the earlier independent date installer.
        date = (scripts / compat.DATE_BUNDLE).read_bytes().replace(compat.DATE_ORIGINAL, compat.DATE_REPAIRED, 1)
        date_name = "DateInput.enfra-scalar-" + sha256(date).hexdigest()[:12] + ".js"
        entry = (scripts / compat.INDEX_BUNDLE).read_bytes().replace(compat.DATE_BUNDLE.encode(), date_name.encode())
        name = "index.enfra-date-" + sha256(entry).hexdigest()[:12] + ".js"
        (scripts / date_name).write_bytes(date); (scripts / name).write_bytes(entry)
        (root / "index.html").write_bytes(b'<script src="./static/js/' + name.encode() + b'"></script>')
    else:
        compat.patch_bundle(root, installed_version="1.61.1")
    receipt = compat.patch_bundle(root, installed_version="1.61.1", scalar_date=True)
    raw = (scripts / receipt["entry"]).read_bytes()
    assert raw.count(compat.REPAIRED) == 1 and compat.ORIGINAL not in raw
    assert raw.count(receipt["bundle"].encode()) == 2 and compat.DATE_BUNDLE.encode() not in raw
    assert (scripts / receipt["bundle"]).read_bytes().count(compat.DATE_REPAIRED) == 1
    snapshot = files(root)
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert compat.patch_bundle(root, installed_version="1.61.1", scalar_date=True)["already_patched"]
    assert files(root) == snapshot


def test_actual_date_installer_entrypoint_composes_with_scheduler_installer(bundle):
    root, scripts = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(project / "scripts" / "patch_streamlit_date_input.py"),
                             "--static-dir", str(root)], cwd=project, check=True,
                            capture_output=True, text=True, timeout=15)
    receipt = json.loads(result.stdout)
    assert receipt["scalar_date"] and (scripts / receipt["entry"]).is_file()
    before = files(root)
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert files(root) == before


@pytest.mark.parametrize("mutation", ["version", "entry", "date", "missing", "html", "duplicate", "destination", "selected"])
def test_unknown_or_tampered_assets_fail_before_any_write(bundle, mutation):
    root, scripts = bundle
    installed_version = "1.61.2" if mutation == "version" else "1.61.1"
    if mutation in {"entry", "date"}:
        path = scripts / (compat.INDEX_BUNDLE if mutation == "entry" else compat.DATE_BUNDLE)
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "missing":
        (scripts / compat.INDEX_BUNDLE).unlink()
    elif mutation == "html":
        (root / "index.html").write_bytes(b"Unknown client entry")
    elif mutation == "duplicate":
        (root / "index.html").write_bytes((root / "index.html").read_bytes() * 2)
    elif mutation == "destination":
        raw = (scripts / compat.INDEX_BUNDLE).read_bytes().replace(compat.ORIGINAL, compat.REPAIRED, 1)
        (scripts / compat._entry_name(raw)).write_bytes(b"Unexpected existing asset")
    elif mutation == "selected":
        receipt = compat.patch_bundle(root, installed_version="1.61.1")
        (scripts / receipt["entry"]).write_bytes(b"Tampered selected entry")
    before = files(root)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        compat.patch_bundle(root, installed_version=installed_version)
    assert files(root) == before
