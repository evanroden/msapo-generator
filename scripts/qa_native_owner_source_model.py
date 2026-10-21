"""Run a bounded source model of the observed deep-trigger/shallow-popup change.

No browser, app, server, network, draft or production asset is changed. Native
source is extracted from the independently pinned installed originals and the
already-authorized publication recipe. The async phase is a controlled model
seam, not a measurement of WebKit's microtask/rendering implementation.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import patch_streamlit_frontend as compat
from scripts.qa_native_owner_assets import FLOATING, FLOATING_SHA256
from scripts.streamlit_floating_resize import repair_floating


def between(source, start, end):
    if source.count(start) != 1:
        raise RuntimeError("Unexpected exact model start boundary")
    offset = source.index(start)
    finish = source.index(end, offset)
    return source[offset:finish]


def extracts(static, manifest):
    scripts = Path(static) / "static/js"
    sources, members = compat._locked_sources(scripts)
    selected = manifest["selected_production"]
    publication = compat._publication(sources, members, selected["scalar_date"], virtualizer_resize=True,
                                      floating_resize=False, queued_scroll=False, selection_safe_close=False, no_cache_advertisements=False, instant_expander=False)
    if publication.generation != selected["generation"]:
        raise RuntimeError("Model does not reconstruct the retained ordinary publication")
    rows = {}
    for name in (compat.OVERLAY_BUNDLE, compat.VIRTUALIZER_BUNDLE):
        published_name = publication.names[name]
        raw = publication.payloads[name]
        if sha256(raw).hexdigest() != manifest["assets"][published_name]["input_sha256"]:
            raise RuntimeError("Model source differs from the retained derivative's actual input")
        rows[name] = raw.decode()
    floating = (scripts / FLOATING).read_bytes()
    if (sha256(floating).hexdigest() != FLOATING_SHA256
            or sha256(floating).hexdigest() != manifest["assets"][FLOATING]["input_sha256"]):
        raise RuntimeError("Unexpected exact Floating UI model source")
    floating = floating.decode()
    overlay, virtual = rows[compat.OVERLAY_BUNDLE], rows[compat.VIRTUALIZER_BUNDLE]
    combo_start = "()=>{if(f.current&&!p.current){let e=d.current?.getBoundingClientRect()"
    combo = between(virtual, combo_start, ",[d,f,M])")
    popover_start = "j=(0,J.useCallback)(()=>{i.triggerRef.current&&A("
    popover = between(virtual, popover_start, ",[i.triggerRef]);T(j,[j])")
    popover = popover[len("j=(0,J.useCallback)("):]
    style = between(virtual, 'let M={...l.style,"--trigger-anchor-point":', ",N=J.createElement(b.div")
    values = {
        "xt": between(overlay, "function Xt(e){", "var Y="),
        "rn": between(floating, "function rn(e,t,n,r){", "var an="),
        "rnRepaired": between(repair_floating(floating.encode()).decode(), "function rn(e,t,n,r){", "var an="),
        "vr": between(floating, "function vr(e){", "export{"),
        "combo": combo, "popover": popover, "popoverStyle": style[len("let M="):],
    }
    return values, {name: {"bytes": len(value.encode()), "sha256": sha256(value.encode()).hexdigest()}
                    for name, value in values.items()}


def main():
    import streamlit
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_bytes())
    values, pins = extracts(Path(streamlit.__file__).parent / "static", manifest)
    result = subprocess.run(["node", str(ROOT / "tests/native_owner_depth_model.cjs"), json.dumps(values)],
                            capture_output=True, text=True, timeout=10, check=True)
    value = json.loads(result.stdout)
    value.update({"kind": "conditional source model, not native browser reproduction",
                  "input_manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
                  "source_generation": manifest["selected_production"]["generation"],
                  "extracted_source_pins": pins,
                  "async_timing_limit": "The model explicitly varies whether the width middleware commits before the next depth-gather or in the next cycle. The retained trace does not record setter calls or microtask checkpoints.",
                  "source_scope_limit": "Actual locked callbacks, width writer and popover-style composition run against controlled geometry/state sinks. CSS layout, React reconciliation and WebKit scheduling are not simulated.",
                  "specification": "https://drafts.csswg.org/resize-observer/#gather-active-observations-h",
                  "causation": "A reproduced source feedback class does not identify the unique cause of the recorded8218ms native error."})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
