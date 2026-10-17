"""Execute the actual locked widget batcher and verify cache-safe publication."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
import time

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat


@pytest.fixture
def bundle(tmp_path):
    installed = Path(streamlit.__file__).parent / "static"
    scripts = tmp_path / "static" / "js"
    scripts.mkdir(parents=True)
    for name in {**json.loads(compat.MANIFEST_PATH.read_bytes())["members"],
                 **json.loads(compat.FLOATING_MANIFEST_PATH.read_bytes())["members"]}:
        (scripts / name).write_bytes((installed / "static" / "js" / name).read_bytes())
    (tmp_path / "index.html").write_bytes((installed / "index.html").read_bytes())
    return tmp_path, scripts


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def previous_overlay(bundle, scalar_date, virtualizer=False):
    """Install an exact former 81-member generation from pinned originals."""
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    publication = compat._publication(sources, members, scalar_date, virtualizer_resize=virtualizer,
                                      floating_resize=False, queued_scroll=False)
    # These are independently retained published identities, not names inferred
    # from the selected files or supplied by the current implementation.
    assert publication.names[compat.INDEX_BUNDLE] == {
        (False, False): "index.enfra-frontend-82ffaa997d27.js",
        (False, True): "index.enfra-frontend-9dafff8ac486.js",
        (True, False): "index.enfra-frontend-8b4db936843b.js",
        (True, True): "index.enfra-frontend-e78baf101bbc.js",
    }[virtualizer, scalar_date]
    for native, raw in publication.payloads.items():
        (scripts / publication.names[native]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, publication, (publication,)))
    return publication


@pytest.mark.parametrize("previous_date", [False, True])
@pytest.mark.parametrize("requested_date", [False, True])
def test_published_83_member_generation_upgrades_without_losing_originals_or_date(bundle, previous_date, requested_date):
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, previous_date, queued_scroll=False)
    # Exact deployed Water and tested Training identities retained before this
    # repair; deriving these expectations from current output would miss a
    # backwards-compatibility break in the publication recipe.
    assert old.names[compat.INDEX_BUNDLE] == {
        False: "index.enfra-frontend-fbb0a97cf659.js",
        True: "index.enfra-frontend-25142a252245.js",
    }[previous_date]
    for native, raw in old.payloads.items():
        (scripts / old.names[native]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    before = files(root)
    assert compat.selected_frontend(root)["queued_scroll"] is False
    assert files(root) == before
    receipt = compat.patch_bundle(root, installed_version="1.61.1", scalar_date=requested_date)
    assert receipt["queued_scroll"] is True and receipt["closure_count"] == 83
    assert receipt["scalar_date"] is (previous_date or requested_date)
    assert receipt["entry"] != old.names[compat.INDEX_BUNDLE]
    for name, raw in before.items():
        if name != "index.html":
            assert (root / name).read_bytes() == raw
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]


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
    members = json.loads(compat.MANIFEST_PATH.read_bytes())["members"]
    assert receipt["closure_count"] == len(members) + 2 == 83
    assert receipt["floating_resize"] is True
    assert receipt["virtualizer_resize"] is True
    assert receipt["queued_scroll"] is True
    for name in members:
        assert (scripts / name).read_bytes() == before["static/js/" + name]
    raw = (scripts / receipt["entry"]).read_bytes()
    assert raw.count(compat.REPAIRED) == 1 and compat.ORIGINAL not in raw
    assert sha256(raw).hexdigest() == receipt["patched_entry_sha256"]
    overlay = (scripts / receipt["overlay_bundle"]).read_bytes()
    assert sha256(overlay).hexdigest() == receipt["overlay_sha256"]
    virtualizer = (scripts / receipt["virtualizer_bundle"]).read_bytes()
    assert sha256(virtualizer).hexdigest() == receipt["virtualizer_sha256"]
    assert receipt["original_virtualizer_sha256"] == members[compat.VIRTUALIZER_BUNDLE]["sha256"]
    assert receipt["overlay_bundle"].encode() in raw
    assert compat.OVERLAY_BUNDLE.encode() not in raw
    assert receipt["entry"].encode() in (root / "index.html").read_bytes()
    assert receipt["overlay_bundle"].encode() in (root / "index.html").read_bytes()
    assert all(name.encode() not in (root / "index.html").read_bytes() for name in members)
    assert compat.selected_frontend(root) == {key: value for key, value in receipt.items() if key != "already_patched"}
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


@pytest.mark.parametrize("mutation", ["version", "entry", "date", "virtualizer", "floating", "json", "missing", "html", "duplicate", "destination", "selected"])
def test_unknown_or_tampered_assets_fail_before_any_write(bundle, mutation):
    root, scripts = bundle
    installed_version = "1.61.2" if mutation == "version" else "1.61.1"
    if mutation in {"entry", "date", "virtualizer", "floating", "json"}:
        path = scripts / {"entry": compat.INDEX_BUNDLE, "date": compat.DATE_BUNDLE,
                          "virtualizer": compat.VIRTUALIZER_BUNDLE, "floating": compat.FLOATING_BUNDLE, "json": "Json.C9LKsaSO.js"}[mutation]
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "missing":
        (scripts / compat.INDEX_BUNDLE).unlink()
    elif mutation == "html":
        (root / "index.html").write_bytes(b"Unknown client entry")
    elif mutation == "duplicate":
        (root / "index.html").write_bytes((root / "index.html").read_bytes() * 2)
    elif mutation == "destination":
        sources, members = compat._locked_sources(scripts)
        publication = compat._publication(sources, members, False)
        (scripts / publication.names[compat.OVERLAY_BUNDLE]).write_bytes(b"Unexpected existing asset")
    elif mutation == "selected":
        receipt = compat.patch_bundle(root, installed_version="1.61.1")
        (scripts / receipt["entry"]).write_bytes(b"Tampered selected entry")
    before = files(root)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        compat.patch_bundle(root, installed_version=installed_version)
    assert files(root) == before


@pytest.mark.parametrize("target", ["overlay", "virtualizer", "floating", "json", "cyclic", "entry", "date", "missing"])
def test_read_only_expected_receipt_rejects_corrupt_selected_generation(bundle, target):
    root, scripts = bundle
    receipt = compat.patch_bundle(root, installed_version="1.61.1", scalar_date=True)
    sources, members = compat._locked_sources(scripts)
    publication = compat._publication(sources, members, True)
    name = {"overlay": receipt["overlay_bundle"], "cyclic": publication.names["MermaidChart.Bk0sk5TL.js"],
            "virtualizer": receipt["virtualizer_bundle"], "floating": receipt["floating_bundle"],
            "json": publication.names["Json.C9LKsaSO.js"],
            "entry": receipt["entry"], "date": receipt["bundle"],
            "missing": publication.names["Toolbar.DumIAbTb.js"]}[target]
    path = scripts / name
    if target == "missing":
        path.unlink()
    else:
        raw = path.read_bytes()
        path.write_bytes(b" " + raw[1:])  # Same filename and length, different body.
    before = files(root)
    with pytest.raises(RuntimeError):
        compat.selected_frontend(root)
    with pytest.raises(RuntimeError):
        compat.patch_bundle(root, installed_version="1.61.1")
    assert files(root) == before


@pytest.mark.parametrize("previous_date", [False, True])
@pytest.mark.parametrize("requested_date", [False, True])
@pytest.mark.parametrize("virtualizer", [False, True])
def test_previous_overlay_generations_upgrade_without_losing_date_or_history(bundle, previous_date, requested_date, virtualizer):
    root, scripts = bundle
    old = previous_overlay(bundle, previous_date, virtualizer)
    before = files(root)
    prior_receipt = compat.selected_frontend(root)
    assert prior_receipt["virtualizer_resize"] is virtualizer
    assert prior_receipt["floating_resize"] is False
    assert prior_receipt["scalar_date"] is previous_date
    assert prior_receipt["virtualizer_bundle"] == old.names[compat.VIRTUALIZER_BUNDLE]
    assert prior_receipt["virtualizer_sha256"] == sha256(old.payloads[compat.VIRTUALIZER_BUNDLE]).hexdigest()
    assert files(root) == before, "Inspecting known prior output must perform no upgrade or write."
    receipt = compat.patch_bundle(root, installed_version="1.61.1", scalar_date=requested_date)
    assert receipt["virtualizer_resize"] is True and not receipt["already_patched"]
    assert receipt["scalar_date"] is (previous_date or requested_date)
    assert receipt["entry"] != old.names[compat.INDEX_BUNDLE]
    for name, raw in before.items():
        if name != "index.html":
            assert (root / name).read_bytes() == raw, "Upgrade must retain every original and prior immutable chunk."
    html = (root / "index.html").read_bytes()
    assert all(name.encode() not in html for name in old.names.values())
    selected = compat.selected_frontend(root)
    assert selected["virtualizer_resize"] is True and selected["entry"] == receipt["entry"]
    assert selected["virtualizer_sha256"] == sha256((scripts / selected["virtualizer_bundle"]).read_bytes()).hexdigest()
    snapshot = files(root)
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert compat.patch_bundle(root, installed_version="1.61.1", scalar_date=receipt["scalar_date"])["already_patched"]
    assert files(root) == snapshot


@pytest.mark.parametrize("previous_date", [False, True])
@pytest.mark.parametrize("target", ["virtualizer", "cyclic", "missing", "preload"])
def test_prior_selected_closure_corruption_cannot_be_hidden_by_upgrade(bundle, previous_date, target):
    root, scripts = bundle
    old = previous_overlay(bundle, previous_date)
    name = old.names[compat.VIRTUALIZER_BUNDLE if target == "virtualizer" else "Toolbar.DumIAbTb.js"]
    path = scripts / name
    if target == "missing":
        path.unlink()
    elif target == "preload":
        html = (root / "index.html").read_bytes()
        assert name.encode() in html
        (root / "index.html").write_bytes(html.replace(name.encode(), b"Toolbar.DumIAbTb.js"))
    else:
        raw = path.read_bytes()
        path.write_bytes(b" " + raw[1:])
    before = files(root)
    with pytest.raises(RuntimeError):
        compat.selected_frontend(root)
    with pytest.raises(RuntimeError):
        compat.patch_bundle(root, installed_version="1.61.1")
    assert files(root) == before


@pytest.mark.parametrize("previous_date", [False, True])
def test_interrupted_previous_overlay_upgrade_keeps_old_complete_selection(bundle, monkeypatch, previous_date):
    root, _ = bundle
    old = previous_overlay(bundle, previous_date)
    before = files(root)
    publish = compat._publish

    def interrupt_html(path, raw, **kwargs):
        if path.name == "index.html":
            raise OSError("Synthetic prior-generation HTML interruption")
        return publish(path, raw, **kwargs)

    monkeypatch.setattr(compat, "_publish", interrupt_html)
    with pytest.raises(OSError, match="prior-generation HTML interruption"):
        compat.patch_bundle(root, installed_version="1.61.1")
    assert compat.selected_frontend(root)["virtualizer_resize"] is False
    assert compat.selected_frontend(root)["entry"] == old.names[compat.INDEX_BUNDLE]
    for name, raw in before.items():
        assert (root / name).read_bytes() == raw
    monkeypatch.setattr(compat, "_publish", publish)
    upgraded = compat.patch_bundle(root, installed_version="1.61.1")
    assert upgraded["virtualizer_resize"] is True and upgraded["scalar_date"] is previous_date


@pytest.mark.parametrize("root_bundle", [compat.OVERLAY_BUNDLE, compat.FLOATING_BUNDLE])
def test_unknown_incoming_native_importer_fails_before_any_write(bundle, root_bundle):
    root, scripts = bundle
    (scripts / "UnknownNative.js").write_bytes(b'import"./' + root_bundle.encode() + b'";')
    before = files(root)
    with pytest.raises(RuntimeError, match="Unpinned frontend importer"):
        compat.patch_bundle(root, installed_version="1.61.1")
    assert files(root) == before


def test_pinned_import_edges_are_validated_before_any_write(bundle, tmp_path, monkeypatch):
    root, _ = bundle
    manifest = json.loads(compat.MANIFEST_PATH.read_bytes())
    manifest["members"][compat.OVERLAY_BUNDLE]["references"] = []
    changed = tmp_path / "wrong-manifest.json"
    changed.write_text(json.dumps(manifest))
    monkeypatch.setattr(compat, "MANIFEST_PATH", changed)
    monkeypatch.setattr(compat, "MANIFEST_SHA256", sha256(changed.read_bytes()).hexdigest())
    before = files(root)
    with pytest.raises(RuntimeError, match="Unexpected locked Streamlit frontend asset"):
        compat.patch_bundle(root, installed_version="1.61.1")
    assert files(root) == before


def test_real_cyclic_graph_has_one_generation_and_no_original_context_imports(bundle):
    root, scripts = bundle
    receipt = compat.patch_bundle(root, installed_version="1.61.1", scalar_date=True)
    sources, members = compat._locked_sources(scripts)
    publication = compat._publication(sources, members, True)
    cycle = {"MermaidChart.Bk0sk5TL.js", "StreamlitMarkdown.8wKeixZI.js", "Toolbar.DumIAbTb.js",
             "CodeBlockCopyToolbar.BpnuDZwR.js", "StreamlitSyntaxHighlighter.DDgmdug5.js"}
    for native, record in members.items():
        raw = (scripts / publication.names[native]).read_bytes()
        assert compat._references(raw) == {publication.names.get(name, name) for name in record["references"]}
        assert not (compat._references(raw) & set(members))
        if native in cycle:
            assert receipt["generation"][:20] in publication.names[native]
    date = (scripts / receipt["bundle"]).read_bytes()
    assert receipt["patched_sha256"] == sha256(date).hexdigest() == receipt["date_sha256"]


@pytest.mark.parametrize("with_date", [False, True])
def test_interrupted_html_publication_leaves_previous_client_and_retry_is_safe(bundle, monkeypatch, with_date):
    root, scripts = bundle
    html_before = (root / "index.html").read_bytes()
    originals = files(root)
    original_publish = compat._publish
    writes = []
    def interrupted(path, raw, *, immutable=False):
        writes.append(path.name)
        if path.name == "index.html":
            assert len(writes) == 84  # Every immutable asset is complete first.
            raise OSError("Synthetic HTML publication interruption")
        return original_publish(path, raw, immutable=immutable)
    monkeypatch.setattr(compat, "_publish", interrupted)
    with pytest.raises(OSError, match="HTML publication interruption"):
        compat.patch_bundle(root, installed_version="1.61.1", scalar_date=with_date)
    assert (root / "index.html").read_bytes() == html_before
    for name, raw in originals.items():
        assert (root / name).read_bytes() == raw
    assert len(list(scripts.glob("*.enfra-overlay-*.js"))) == 82
    monkeypatch.setattr(compat, "_publish", original_publish)
    receipt = compat.patch_bundle(root, installed_version="1.61.1", scalar_date=with_date)
    assert not receipt["already_patched"] and receipt["scalar_date"] == with_date
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]


def test_interrupted_generated_asset_never_replaces_html_or_originals(bundle, monkeypatch):
    root, scripts = bundle
    before = files(root)
    real_link = compat.os.link
    count = 0
    def interrupted(source, destination):
        nonlocal count
        count += 1
        if count == 4:
            raise OSError("Synthetic immutable publication interruption")
        return real_link(source, destination)
    monkeypatch.setattr(compat.os, "link", interrupted)
    with pytest.raises(OSError, match="immutable publication interruption"):
        compat.patch_bundle(root, installed_version="1.61.1")
    assert not list(scripts.glob(".pending-enfra-*"))
    for name, raw in before.items():
        assert (root / name).read_bytes() == raw
    monkeypatch.setattr(compat.os, "link", real_link)
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    assert compat.selected_frontend(root)["entry"] == receipt["entry"]


@pytest.mark.parametrize("first_scalar", [False, True])
def test_actual_two_publishers_lock_before_validation_and_never_downgrade_date(bundle, tmp_path_factory, first_scalar):
    """Hold A at HTML publication while B really attempts the same directory lock.

    This uses independent processes, not a nested installer inside a mocked
    HTML write. B must validate only after A publishes, then preserve the newly
    selected scalar configuration even when B requested only the scheduler.
    """
    import fcntl
    import os
    root, scripts = bundle
    coordination = tmp_path_factory.mktemp("frontend-publish-concurrency")
    originals = files(root)
    code = r'''
from contextlib import contextmanager
import json
from pathlib import Path
import sys,time
from scripts import patch_streamlit_frontend as c
root, coordination, role, scalar = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]=='true'
real_lock, real_publish, real_validate = c._directory_lock, c._publish, c._validated_publications
def mark(name): (coordination/name).write_text('ready')
@contextmanager
def traced_lock(path):
    mark(role+'-before-lock')
    with real_lock(path):
        mark(role+'-acquired-lock')
        yield
def traced_validation(*args,**kwargs):
    mark(role+'-validated')
    return real_validate(*args,**kwargs)
def held_publish(path,raw,**kwargs):
    if role=='a' and path.name=='index.html':
        mark('a-at-html')
        deadline=time.monotonic()+25
        while not (coordination/'release-a').exists():
            if time.monotonic()>deadline: raise RuntimeError('test coordination timed out')
            time.sleep(.01)
    return real_publish(path,raw,**kwargs)
c._directory_lock, c._publish, c._validated_publications = traced_lock, held_publish, traced_validation
receipt=c.patch_bundle(root,installed_version='1.61.1',scalar_date=scalar)
(coordination/(role+'-receipt.json')).write_text(json.dumps(receipt))
'''
    project = Path(__file__).resolve().parents[1]
    processes = []

    def start(role, scalar):
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(root), str(coordination), role, "true" if scalar else "false"],
            cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(process)
        return process

    def await_marker(name):
        deadline = time.monotonic() + 15
        while not (coordination / name).exists():
            assert time.monotonic() < deadline, "Publisher did not reach " + name
            assert all(process.poll() is None for process in processes), "A publisher exited before " + name
            time.sleep(.01)

    try:
        start("a", first_scalar)
        await_marker("a-at-html")
        # A's lock remains held through the actual atomic HTML replacement.
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        start("b", not first_scalar)
        await_marker("b-before-lock")
        # Give the waiting process an actual scheduling opportunity. No second
        # validation/has_date read may slip between A's lease check and replace.
        until = time.monotonic() + .3
        while time.monotonic() < until:
            assert not (coordination / "b-acquired-lock").exists()
            assert not (coordination / "b-validated").exists()
            assert processes[1].poll() is None
            time.sleep(.01)
        (coordination / "release-a").write_text("continue")
        for process in processes:
            output, error = process.communicate(timeout=20)
            assert process.returncode == 0, (output, error)
        a = json.loads((coordination / "a-receipt.json").read_text())
        b = json.loads((coordination / "b-receipt.json").read_text())
        assert a["scalar_date"] is first_scalar
        assert b["scalar_date"] is True
        assert (coordination / "b-acquired-lock").exists() and (coordination / "b-validated").exists()
        selected = compat.selected_frontend(root)
        assert selected["scalar_date"] is True and selected["entry"] == b["entry"]
        assert (scripts / selected["bundle"]).read_bytes().count(compat.DATE_REPAIRED) == 1
        for name, raw in originals.items():
            if name != "index.html":
                assert (root / name).read_bytes() == raw
        # The directory lock creates no persistent coordination or lock file.
        assert all(name.startswith("static/js/") and name.endswith(".js")
                   for name in files(root).keys() - originals.keys())
    finally:
        (coordination / "release-a").write_text("continue")
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=3)
