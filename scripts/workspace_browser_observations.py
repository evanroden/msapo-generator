"""Bounded observations for the disposable actual-workflow browser fixture only.

Nothing here is imported by production. The caller must pass the same marked
synthetic storage root as tests/fixtures/workspaces/monthly_app.py. No report
text, input values, source names, cookies, paths or owner identities are emitted.
"""
from __future__ import annotations

from functools import wraps
import json
import os
from pathlib import Path
import re

LABEL = "Synthetic workspace observations: "
_KEY = "_synthetic_workspace_observations"


def require_synthetic_root(base):
    base = Path(base).resolve()
    marker = base / "monthly-dom-synthetic-only.marker"
    if (os.environ.get("EPC_MONTHLY_DOM_FIXTURE") != "1"
            or base != Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
            or not marker.is_file()
            or marker.read_text(encoding="ascii") != "synthetic-monthly-dom-v1"):
        raise ValueError("Workspace observations require the marked disposable synthetic root.")


def _counts():
    import streamlit as st
    return st.session_state.setdefault(_KEY, {
        "full_runs": 0, "preview_fragment_runs": 0, "preview_mounts": 0, "sequence": 0,
    })


def install_synthetic_observations(base):
    """Call once per fixture full run, before its real application render."""
    require_synthetic_root(base)
    import streamlit as st
    from app import monthly_report_section_preview_ui as preview
    counts = _counts()
    counts["full_runs"] += 1
    if getattr(preview._render_ordered_preview, "_synthetic_observer", False):
        return
    original = preview._render_ordered_preview

    @wraps(original)
    def observed(*args, **kwargs):
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        context = get_script_run_ctx()
        counts = _counts()
        counts["preview_fragment_runs" if context and context.fragment_ids_this_run else "preview_mounts"] += 1
        try:
            return original(*args, **kwargs)
        finally:
            # The observer neither requests a rerun nor changes any report.
            emit_snapshot()
    observed._synthetic_observer = True
    preview._render_ordered_preview = observed


def safe_snapshot(state, counts):
    """Allowlist numeric job counts and content hashes; reject arbitrary text."""
    drafts, requested = [], {}
    pending = running = visible = 0
    for key, value in state.items():
        if key.endswith("_draft"):
            digest = getattr(value, "fingerprint", "")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                drafts.append(digest)
        if key.endswith("_ordered_previews") and isinstance(value, dict):
            pending += len(value.get("queue", {}))
            running += int(bool(value.get("running")))
            visible += sum(v is True for v in value.get("visible", {}).values())
            for section, digest in value.get("wanted", {}).items():
                if (isinstance(section, str) and re.fullmatch(r"[a-z_]{1,40}", section)
                        and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
                    requested[section] = digest
    return {**{key: int(counts.get(key, 0)) for key in (
        "full_runs", "preview_fragment_runs", "preview_mounts", "sequence")},
        "draft_hashes": sorted(set(drafts))[:4], "requested_hashes": dict(sorted(requested.items())[:16]),
        "pending_jobs": min(pending, 100), "running_jobs": min(running, 100),
        "visible_previews": min(visible, 100)}


def emit_snapshot():
    import streamlit as st
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_preview_store import STORE
    counts = _counts()
    counts["sequence"] += 1
    observed = safe_snapshot(st.session_state, counts)
    observed["assembly_lease_active"] = jobs._WORK_SLOT.locked()
    observed["conversion_lease_active"] = jobs._SLOT.locked()
    with jobs._PRIORITY_LOCK:
        observed["foreground_waiters"] = jobs._FOREGROUND_WAITING
    observed["cache"] = {key: value for key, value in STORE.stats().items()
                         if isinstance(value, (int, float))}
    st.caption(LABEL + json.dumps(observed, separators=(",", ":"), sort_keys=True))


# Use page.add_init_script before navigation. Only durations and stable DOM
# location metadata are sampled; input value/selection text and network are not.
CLIENT_INIT = r"""(() => {
 if(window.__enfraSyntheticObservations) return;
 const state={longTasks:[],longTaskCount:0,maxLongTaskMs:0,supported:false};
 window.__enfraSyntheticObservations=state;
 try {
  if(PerformanceObserver.supportedEntryTypes?.includes('longtask')) {
   const observer=new PerformanceObserver(list=>{
    for(const task of list.getEntries()) {
     state.longTaskCount++;state.maxLongTaskMs=Math.max(state.maxLongTaskMs,task.duration);
     state.longTasks.push({start:Math.round(task.startTime),duration:Math.round(task.duration)});
     if(state.longTasks.length>100) state.longTasks.shift();
    }
   });observer.observe({type:'longtask',buffered:true});state.supported=true;
   addEventListener('pagehide',()=>observer.disconnect(),{once:true});
  }
 } catch(_) {}
})();"""

CLIENT_SNAPSHOT = r"""() => {
 const safe=window.__enfraSyntheticObservations;
 let focus=document.activeElement;
 while(focus?.shadowRoot?.activeElement) focus=focus.shadowRoot.activeElement;
 const pair=focus?.closest?.('.epc-workspace-pair');
 const state=[...document.querySelectorAll('[data-testid="stCaptionContainer"]')]
  .map(n=>n.textContent).filter(text=>text.startsWith('Synthetic workspace observations: '))
  .map(text=>{try{return JSON.parse(text.slice('Synthetic workspace observations: '.length));}catch(_){return null;}})
  .filter(Boolean).sort((a,b)=>b.sequence-a.sequence)[0]||null;
 return {server:state,client:safe?{...safe,longTasks:safe.longTasks.slice(-100)}:null,
  focus:{tag:focus?.tagName||null,type:focus?.getAttribute?.('type')||null,
   pair:pair?.querySelector('[data-epc-pair]')?.dataset.epcPair||null},
  visibility:document.visibilityState};
}"""
