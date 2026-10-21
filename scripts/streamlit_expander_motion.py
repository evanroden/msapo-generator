"""Immediate native expander geometry for the exact locked Streamlit client.

Inputs become interactive as soon as an expander opens. Interpolating a clipped
ancestor's height after that point can scroll it and dismiss an open native
popup. Finish only this native expander operation synchronously; do not change
window animation APIs, native input handlers or genuine scroll dismissal.
"""
from hashlib import sha256

EXPANDER_BUNDLE = "index.bE3scgDe.js"
EXPANDER_SHA256 = "2ca8d2fdc237ec568ac10b8aae70c21e28c9e25ea1924378f068f7a81af6fe6e"
DURATION_ORIGINAL = b"}),Eu=500,Du=`cubic-bezier(0.23, 1, 0.32, 1)`,Ou=1e3;function ku(e,t,n,r={})"
DURATION_REPAIRED = DURATION_ORIGINAL.replace(b"Eu=500", b"Eu=0", 1)
FINISH_ORIGINAL = b"let{duration:i=Eu,easing:a=Du,onFinish:o}=r,s=e.animate"
FINISH_REPAIRED = b"let{duration:i=Eu,easing:a=Du,onFinish:o}=r;if(i===0){e.style.height=``,e.style.overflow=``,o?.();return{cancel:()=>{},finished:Promise.resolve()}}let s=e.animate"


def repair_expander_motion(raw, *, no_cache_advertisements=False):
    if (sha256(raw).hexdigest() != EXPANDER_SHA256
            or raw.count(DURATION_ORIGINAL) != 1 or raw.count(FINISH_ORIGINAL) != 1):
        raise RuntimeError("Unexpected locked expander asset; no bytes were changed.")
    if no_cache_advertisements:
        try:
            from scripts.streamlit_forward_cache import repair_forward_cache
        except ModuleNotFoundError:
            from streamlit_forward_cache import repair_forward_cache
        raw = repair_forward_cache(raw)
    return raw.replace(DURATION_ORIGINAL, DURATION_REPAIRED, 1).replace(FINISH_ORIGINAL, FINISH_REPAIRED, 1)
