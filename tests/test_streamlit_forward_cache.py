"""Exact pinned transport/cache bodies: stale advertisement fails before repair."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import streamlit
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.runtime.scriptrunner_utils.script_run_context import ScriptRunContext
from scripts import patch_streamlit_frontend as compat
from scripts.streamlit_forward_cache import ORIGINAL, REPAIRED, repair_forward_cache


def native():
    return (Path(streamlit.__file__).parent / 'static/static/js' / compat.INDEX_BUNDLE).read_bytes()


def test_exact_boundary_and_no_other_native_changes():
    raw = native()
    repaired = repair_forward_cache(raw)
    assert repaired.count(REPAIRED) == 1
    assert repaired.replace(REPAIRED, ORIGINAL, 1) == raw
    with pytest.raises(RuntimeError):
        repair_forward_cache(raw + b' ')
    with pytest.raises(RuntimeError):
        repair_forward_cache(repaired)


@pytest.mark.parametrize('repaired', [False, True])
def test_native_cache_expiry_between_advertisement_and_reference(repaired):
    raw = native()
    source = (repair_forward_cache(raw) if repaired else raw).decode()
    # Execute the wheel's exact cache and socket advertisement bodies. Only
    # protobuf decode/logging are inert test collaborators, not cache logic.
    classes = source[source.index('eC=class{getAge'):source.index(',nC=', source.index('eC=class{getAge'))]
    socket_start = source.index('rC=class{')
    start = source.index('getCachedMessageHashes(){', socket_start)
    end = source.index('async handleMessage(e)', start)
    getter = source[start:end]
    program = '''
const $S={info(){},error(){}}, AS=x=>x===undefined, gt={decode:x=>x};
var CLASSES;
class Socket {constructor(){this.cache=new tC;} GETTER}
(async()=>{
 const checks=[];
 // A second constructed socket models a fresh protected connection. Native
 // reconnect keeps the same getter/cache, so exercise that same object too.
 for(const socket of [new Socket(),new Socket()]) {
  for(let iteration=0;iteration<2;iteration++) {
   const h='synthetic-'+iteration;
   const m={type:'delta',hash:h,metadata:{cacheable:true},delta:{fragmentId:'preview'}};
   await socket.cache.processMessagePayload(m,m);
   socket.cache.incrementRunCount(2,[]);socket.cache.incrementRunCount(2,[]);
   const advertised=socket.getCachedMessageHashes();
   // Both full and fragment request snapshots use this same native getter;
   // coalescing takes the latest snapshot, never unions old advertisements.
   const coalesced=socket.getCachedMessageHashes();
   socket.cache.incrementRunCount(2,['preview']);
   let missing=false;
   try {await socket.cache.processMessagePayload(advertised.includes(h)?
    {type:'refHash',refHash:h,metadata:{}}:m,m);}catch(e){missing=e.message.startsWith('Cached ForwardMsg MISS');}
   checks.push({advertised,coalesced,missing});
  }
 }
 console.log(JSON.stringify(checks));
})();
'''.replace('CLASSES', classes).replace('GETTER', getter)
    result = subprocess.run(['node', '-e', program], text=True, capture_output=True, check=True)
    checks = json.loads(result.stdout)
    assert len(checks) == 4
    assert all(c['missing'] is (not repaired) for c in checks)
    if repaired:
        assert all(c['advertised'] == c['coalesced'] == [] for c in checks)


def test_native_server_empty_snapshot_sends_complete_payload():
    import contextvars
    contextvars.copy_context().run(_native_server_empty_snapshot)


def _native_server_empty_snapshot():
    from streamlit.runtime.forward_msg_cache import populate_hash_if_needed
    from streamlit.runtime.scriptrunner_utils.script_run_context import ThreadState
    ThreadState.initialize(active_script_hash="synthetic")
    message = ForwardMsg()
    message.delta.new_element.markdown.body = 'Synthetic repeated payload. ' * 1000
    populate_hash_if_needed(message)
    assert message.metadata.cacheable
    for hashes, expected in ((frozenset(), 'delta'), (frozenset([message.hash]), 'ref_hash')):
        sent = []
        ctx = SimpleNamespace(cached_message_hashes=hashes, _enqueue=sent.append)
        ScriptRunContext.enqueue(ctx, message)
        assert len(sent) == 1 and sent[0].WhichOneof('type') == expected


@pytest.mark.parametrize('fragments', [('preview', ''), ('', 'preview'), ('one', 'two', '')])
def test_native_request_coalescing_keeps_empty_advertisements(fragments):
    from streamlit.runtime.scriptrunner_utils.script_requests import ScriptRequests, RerunData
    requests = ScriptRequests()
    for fragment in fragments:
        assert requests.request_rerun(RerunData(fragment_id=fragment, cached_message_hashes=frozenset()))
    request = requests.on_scriptrunner_ready()
    assert request.rerun_data.cached_message_hashes == frozenset()


def test_previous_selection_safe_generation_remains_exact():
    scripts = Path(streamlit.__file__).parent / 'static/static/js'
    sources, members = compat._locked_sources(scripts)
    previous = compat._publication(sources, members, True, no_cache_advertisements=False, instant_expander=False)
    assert previous.generation.startswith('30ec452cc18221610df17')
    assert previous.names[compat.INDEX_BUNDLE] == 'index.enfra-frontend-f581fba5f125.js'
    assert ORIGINAL in previous.payloads[compat.INDEX_BUNDLE]
    current = compat._publication(sources, members, True)
    assert current.generation != previous.generation
    assert REPAIRED in current.payloads[compat.INDEX_BUNDLE]
    assert current.no_cache_advertisements and not previous.no_cache_advertisements


# Reuse the pinned-wheel disposable static directory, never installed assets.
from test_streamlit_frontend_compat import bundle


def test_upgrade_retains_previous_assets_and_receipt_rejects_old_entry(bundle):
    from scripts.qa_shared_fixture_testing import _expected_frontend
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    previous = compat._publication(sources, members, True, no_cache_advertisements=False, instant_expander=False)
    for name, raw in previous.payloads.items():
        (scripts / previous.names[name]).write_bytes(raw)
    html = (root / 'index.html').read_bytes()
    (root / 'index.html').write_bytes(compat._publication_html(
        html, compat.INDEX_BUNDLE, previous, (previous,)))
    with pytest.raises(RuntimeError, match='safe ForwardMsg'):
        _expected_frontend(root)
    receipt = compat.patch_bundle(root, installed_version='1.61.1')
    assert receipt['no_cache_advertisements'] and receipt['scalar_date']
    assert _expected_frontend(root)[0] == receipt['entry']
    for name, raw in previous.payloads.items():
        assert (scripts / previous.names[name]).read_bytes() == raw
