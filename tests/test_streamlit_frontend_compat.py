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


def test_decoded_full_widget_scope_dominates_fragments_in_actual_caller_chain(bundle):
    root, scripts = bundle
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    source = (scripts / receipt["entry"]).read_text()
    def method(start, end):
        offset = source.index(start)
        return source[offset:source.index(end, offset)]
    protobuf = Path(streamlit.__file__).parent / "static/static/js/protobuf.CBn3jIav.js"
    code = r'''
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {methods,protobuf}=JSON.parse(process.argv[1]);
(async()=>{
 globalThis.window={};
 const p=await import(pathToFileURL(protobuf));
 // Decode a real ForwardMsg.delta with the absent optional fragment field.
 // Its generated default, not a guessed harness sentinel, reaches widgets.
 const full=p.v.decode(Uint8Array.of(42,0)).delta.fragmentId;
 assert.equal(full,'');
 for(const sequence of [['preview',full],[full,'preview'],
   ['preview',full,'another'],[undefined,'preview',full],
   ['preview',undefined,'another'],[full,'preview',undefined]]){
  const timers=[],sent=[],cleared=[];let resolved=0;
  const h=new Function('qg','setTimeout','A','return ({'+methods+'})')(
   {warn:()=>{}},fn=>timers.push(fn),form=>Boolean(form));
  Object.assign(h,{flushScheduled:false,scheduledFragmentId:undefined,hasFragmentIdConflict:false,
   pendingTriggerIds:new Set(['action']),triggerFlushResolvers:[()=>resolved++],
   createWidgetState(){return this.widget||(this.widget={})},maybeSyncValueToUrl(){},
   sendUpdateWidgetsMessage(fragment){sent.push({fragment,value:this.widget.stringValue})},
   deleteWidgetState:id=>cleared.push(id)});
  for(const scope of sequence)h.setStringValue({id:'native',formId:''},'exact native edit',{fromUi:true},scope);
  assert.equal(timers.length,1);timers.shift()();
  assert.equal(sent.length,1);assert.ok(sent[0].fragment===undefined||sent[0].fragment==='');
  assert.equal(sent[0].value,'exact native edit');assert.deepEqual(cleared,['action']);
  assert.equal(resolved,1);assert.equal(h.flushScheduled,false);assert.equal(h.scheduledFragmentId,undefined);
 }
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    methods = method("scheduleFlush(e){", "registerQueryParamBinding(")
    methods += "," + method("onWidgetValueChanged(e,t,n){", "syncFormsWithPendingChanges(){")
    methods += "," + method("setStringValue(e,t,n,r){", "setStringArrayValue(")
    subprocess.run(["node", "-e", code, json.dumps({"methods": methods, "protobuf": str(protobuf)})],
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


@pytest.mark.parametrize("with_date", [False, True])
def test_exact_previous_scheduler_entry_upgrades_without_discarding_date(bundle, with_date):
    root, scripts = bundle
    original = (scripts / compat.INDEX_BUNDLE).read_bytes()
    old = original.replace(compat.ORIGINAL, compat.LEGACY_REPAIRED, 1)
    if with_date:
        date = (scripts / compat.DATE_BUNDLE).read_bytes().replace(compat.DATE_ORIGINAL, compat.DATE_REPAIRED, 1)
        name = "DateInput.enfra-scalar-" + sha256(date).hexdigest()[:12] + ".js"
        (scripts / name).write_bytes(date)
        old = old.replace(compat.DATE_BUNDLE.encode(), name.encode())
    name = compat._entry_name(old)
    (scripts / name).write_bytes(old)
    (root / "index.html").write_bytes(b'<script src="./static/js/' + name.encode() + b'"></script>')
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    assert receipt["scalar_date"] == with_date and not receipt["already_patched"]
    assert receipt["entry"] != name and (scripts / name).read_bytes() == old
    repaired = (scripts / receipt["entry"]).read_bytes()
    assert repaired.count(compat.REPAIRED) == 1
    assert sha256(repaired).hexdigest() == receipt["patched_entry_sha256"]


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


def test_browser_frontend_receipt_hashes_the_delivered_bytes_without_writes(bundle):
    from scripts.qa_shared_fixture_testing import _expected_frontend, _frontend_response_receipt
    from types import SimpleNamespace
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    before = files(root)
    expected = _expected_frontend(root)
    assert files(root) == before
    entry, raw = expected
    response = SimpleNamespace(url="http://127.0.0.1:8521/static/js/" + entry,
                               status=200, headers={"content-length": str(len(raw))}, body=lambda: raw)
    receipt = _frontend_response_receipt(response, expected)
    assert receipt["matches"] and receipt["sha256"] == sha256(raw).hexdigest()
    assert receipt["full_scope_predicate_count"] == 1 and receipt["original_predicate_count"] == 0
    assert all(not isinstance(value, bytes) for value in receipt.values())
    # A correct filename and length cannot certify different JavaScript bytes.
    response.body = lambda: b" " + raw[1:]
    assert not _frontend_response_receipt(response, expected)["matches"]


@pytest.mark.parametrize("status,size", [(404, 0), (200, 2 * 1024 * 1024), (200, 0)])
def test_frontend_observer_does_not_read_unbounded_or_ineligible_response(bundle, status, size):
    from scripts.qa_shared_fixture_testing import _expected_frontend, _frontend_response_receipt
    from types import SimpleNamespace
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    expected = _expected_frontend(root)
    def forbidden_body():
        pytest.fail("The observer must reject this response before reading its body")
    response = SimpleNamespace(url="http://127.0.0.1:8521/static/js/" + expected[0],
                               status=status, headers={"content-length": str(size)}, body=forbidden_body)
    assert not _frontend_response_receipt(response, expected)["matches"]


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
