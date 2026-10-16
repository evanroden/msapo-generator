"""Defer only the locked Floating UI ResizeObserver update, owned by its lifetime.

Its width middleware can resize a shallow popup while deeper trigger observers
are broadcasting. Unobserving its own popup does not remove other observers.
Initial, scroll, window-resize, layout-shift and animation-frame updates stay
native. This bounded mitigation needs strict browser verification.
"""
from hashlib import sha256

FLOATING_BUNDLE = "useFloatingOverlay.NyFxHaQF.js"
FLOATING_SHA256 = "0bb3da6d472fd03e249c6c42e6cb3c1e6f4e9f57804278d94cda231638d06e80"
FLOATING_START = b"let d=l&&s?nn(l,n,a):null,f=-1,p=null;o&&(p=new ResizeObserver(e=>{"
FLOATING_END = b"f=requestAnimationFrame(()=>{var e;(e=p)==null||e.observe(t)})),n()}),l&&!c&&p.observe(l),t&&p.observe(t));"
FLOATING_CLEANUP = b"return n(),()=>{var e;u.forEach"
FLOATING_START_REPAIRED = b"let d=l&&s?nn(l,n,a):null,f=-1,p=null,enfraFloatingFrame=null,enfraFloatingActive=true;o&&(p=new ResizeObserver(e=>{if(!enfraFloatingActive)return;"
FLOATING_END_REPAIRED = b"f=requestAnimationFrame(()=>{var e;(e=p)==null||e.observe(t)})),enfraFloatingFrame===null&&(enfraFloatingFrame=requestAnimationFrame(()=>{enfraFloatingFrame=null;if(enfraFloatingActive)n()}))}),l&&!c&&p.observe(l),t&&p.observe(t));"
FLOATING_CLEANUP_REPAIRED = b"return n(),()=>{var e;enfraFloatingActive=false;if(enfraFloatingFrame!==null){cancelAnimationFrame(enfraFloatingFrame);enfraFloatingFrame=null}cancelAnimationFrame(f);u.forEach"


def repair_floating(raw):
    replacements = ((FLOATING_START, FLOATING_START_REPAIRED),
                    (FLOATING_END, FLOATING_END_REPAIRED),
                    (FLOATING_CLEANUP, FLOATING_CLEANUP_REPAIRED))
    if sha256(raw).hexdigest() != FLOATING_SHA256 or any(raw.count(old) != 1 for old, _ in replacements):
        raise RuntimeError("Unexpected locked Floating UI asset; no bytes were changed.")
    for old, new in replacements:
        raw = raw.replace(old, new, 1)
    return raw
