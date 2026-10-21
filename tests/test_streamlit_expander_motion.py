"""Exact native expander lifecycle and measured-scroll negative control."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat
from scripts.streamlit_expander_motion import (
    EXPANDER_BUNDLE, DURATION_ORIGINAL, DURATION_REPAIRED,
    FINISH_ORIGINAL, FINISH_REPAIRED, repair_expander_motion,
)
from scripts.streamlit_overlay_resize import OVERLAY_BUNDLE, repair_overlay
from test_streamlit_frontend_compat import bundle


def native():
    return (Path(streamlit.__file__).parent / "static/static/js" / EXPANDER_BUNDLE).read_bytes()


def test_exact_native_expander_and_scroll_lifecycle(tmp_path):
    raw = native()
    repaired = repair_expander_motion(raw)
    def lifecycle(value):
        source = value.decode()
        return source[source.index("function ku(e,t,n,r={})"):source.index("var Nu=")]
    overlay = repair_overlay((Path(streamlit.__file__).parent / "static/static/js" / OVERLAY_BUNDLE).read_bytes()).decode()
    multiselect = (Path(streamlit.__file__).parent / "static/static/js/Multiselect.Bh_0JsCR.js").read_text()
    start = multiselect.index("Me=(0,w.useCallback)(") + len("Me=(0,w.useCallback)(")
    change = multiselect[start:multiselect.index(",[t.maxSelections,S,x]),Ne=", start)]
    source = tmp_path / "native.json"
    source.write_text(json.dumps({"before": lifecycle(raw), "after": lifecycle(repaired),
        "scroll": overlay[overlay.index("function Jt(e)"):overlay.index("function Yt()")],
        "latest": overlay[overlay.index("function Ze("):overlay.index("var Qe=")], "change": change}))
    run = subprocess.run(["node", str(Path(__file__).with_name("expander_motion_test.cjs")), str(source)],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr


def test_only_default_duration_and_synchronous_zero_path_change():
    raw = native()
    repaired = repair_expander_motion(raw)
    assert repaired.count(DURATION_REPAIRED) == repaired.count(FINISH_REPAIRED) == 1
    assert repaired.replace(DURATION_REPAIRED, DURATION_ORIGINAL, 1).replace(
        FINISH_REPAIRED, FINISH_ORIGINAL, 1) == raw
    # Toggle state/ref updates, summary onClick (including native keyboard
    # activation), content inert state, resize observer and cleanup stay exact.
    start, end = raw.index(b"function Mu("), raw.index(b"var Nu=")
    assert raw[start:end] in repaired
    assert b"onClick:k,ref:D" in repaired and b'inert:T?void 0:``' in repaired
    assert b"window.matchMedia" not in repaired[repaired.index(b"function ku("):repaired.index(b"var Nu=")]


def test_explicit_positive_duration_remains_native_and_zero_finishes_synchronously():
    raw = repair_expander_motion(native()).decode()
    helper = raw[raw.index("function ku("):raw.index("var Au=")]
    code = r'''
const assert=require('node:assert/strict'),source=JSON.parse(process.argv[1]);
const timers=new Map();let next=0,animated=0,finished=0,canceled=0;const listeners={};
const animation={playState:'running',addEventListener:(type,fn)=>listeners[type]=fn,
 cancel(){canceled++;listeners.cancel?.()},finish(){this.playState='finished';listeners.finish?.()}};
const element={style:{height:'40px',overflow:'hidden'},animate(frames,options){
 animated++;assert.equal(options.duration,500);return animation}};
const ku=new Function('Eu','Du','Ou','setTimeout','clearTimeout',source+';return ku')
 (0,'ease',1000,(fn,ms)=>{const id=++next;timers.set(id,{fn,ms});return id},id=>timers.delete(id));
const immediate=ku(element,40,561,{onFinish:()=>finished++});
assert.equal(animated,0);assert.equal(finished,1);assert.equal(element.style.height,'');
assert.equal(element.style.overflow,'');assert.equal(timers.size,0);immediate.cancel();assert.equal(canceled,0);
const timed=ku(element,40,561,{duration:500,onFinish:()=>finished++});
assert.equal(animated,1);assert.equal(finished,1);assert.equal(timers.size,1);
assert.equal([...timers.values()][0].ms,1500);animation.finish();assert.equal(finished,2);assert.equal(timers.size,0);
const canceledRun=ku(element,40,561,{duration:500,onFinish:()=>finished++});
canceledRun.cancel();assert.equal(canceled,1);assert.equal(finished,2);assert.equal(timers.size,0);
Promise.all([immediate.finished,timed.finished,canceledRun.finished]).then(()=>console.log('resolved'));
'''
    result = subprocess.run(["node", "-e", code, json.dumps(helper)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and "resolved" in result.stdout, result.stdout + result.stderr


def test_locked_expander_rejects_changed_source_and_composes_forward_cache():
    from scripts.streamlit_forward_cache import REPAIRED as CACHE_REPAIRED
    raw = native()
    assert repair_expander_motion(raw, no_cache_advertisements=True).count(CACHE_REPAIRED) == 1
    for damaged in (raw+b" ", repair_expander_motion(raw)):
        with pytest.raises(RuntimeError, match="Unexpected locked expander"):
            repair_expander_motion(damaged)


@pytest.mark.parametrize("no_cache", [False, True])
def test_previous_cache_and_selection_generations_remain_immutable_upgrade_inputs(bundle, no_cache):
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, True, no_cache_advertisements=no_cache, instant_expander=False, tab_navigation=False)
    assert old.names[compat.INDEX_BUNDLE] == ("index.enfra-frontend-e86cbf744776.js" if no_cache
                                            else "index.enfra-frontend-f581fba5f125.js")
    for name, raw in old.payloads.items():
        (scripts / old.names[name]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    assert compat.selected_frontend(root)["instant_expander"] is False
    new = compat.patch_bundle(root, installed_version="1.61.1")
    assert new["instant_expander"] and new["no_cache_advertisements"] and new["scalar_date"]
    for name, raw in old.payloads.items():
        assert (scripts / old.names[name]).read_bytes() == raw


def test_training_first_delivery_requires_synchronous_expander_bytes():
    from scripts.qa_shared_fixture_testing import _frontend_response_receipt
    for repaired in (False, True):
        from scripts.streamlit_forward_cache import repair_forward_cache
        raw = repair_expander_motion(native(), no_cache_advertisements=True) if repaired else repair_forward_cache(native())
        response = SimpleNamespace(url="http://127.0.0.1/static/js/test.js", status=200,
                                   headers={"content-length":str(len(raw))}, body=lambda:raw)
        receipt = _frontend_response_receipt(response, ("test.js",raw), require_instant_expander=True)
        assert receipt["matches"] is repaired


def test_expander_only_changes_trigger_both_native_browser_workflows():
    import re
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    sections = re.split(r'^  (pull_request|push):\n', workflow.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    events = dict(zip(sections[1::2], sections[2::2]))
    required = {'scripts/streamlit_expander_motion.py', 'tests/test_streamlit_expander_motion.py',
                'tests/expander_motion_test.cjs'}
    for event in ('push', 'pull_request'):
        assert required <= set(re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))
