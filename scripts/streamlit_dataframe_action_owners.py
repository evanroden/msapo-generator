"""Keep a current DataFrame's native button intents alive until their flush.

Streamlit 1.61.1 queues a ButtonColumn string trigger, then sends it on a zero
delay timer. A preceding run's completion can clean widget state first. The
native active-ID collector includes the frame itself but omits its registered
button widgets, so this cleanup can erase an accepted action before the wire.

Add only button IDs owned by the already-filtered active DataFrame elements.
Do not retain pending/history IDs, change run/fragment filtering, bypass a
disabled control, replay an event, or change native batching/consumption.
The shared publisher selects a new immutable, content-named graph. Existing
loaded tabs must reload; retaining an old cached bundle is not a repair.
Docker/CI bootstrap run the publisher. A bare Streamlit app rerun does not.
"""
from hashlib import sha256

INDEX_SHA256 = "2ca8d2fdc237ec568ac10b8aae70c21e28c9e25ea1924378f068f7a81af6fe6e"
ORIGINAL = (b"removeInactiveWidgetState(){let{elements:e,blockIds:t}=this.state.elements.getActiveIds(),"
            b"n=new Set([...Array.from(e).map(e=>I(e)).filter(ce),...t]);this.widgetMgr.removeInactive(n)}")
REPAIRED = ORIGINAL.replace(
    b"...t]);", b"...t,...Array.from(e).flatMap(e=>e.type===`dataframe`?"
    b"Object.values(e.dataframe.buttonClickWidgets??{}):[])]);", 1)


def repair_dataframe_action_owners(raw, *, no_cache_advertisements=False, instant_expander=False):
    """Compose only known repairs from the exact original, never unknown bytes.

    Installer-level idempotence recognizes the complete expected content hash,
    not a marker. This recipe retains the previous entry repairs unchanged.
    """
    if sha256(raw).hexdigest() != INDEX_SHA256 or raw.count(ORIGINAL) != 1:
        raise RuntimeError("Unexpected locked DataFrame action-owner boundary; no bytes were changed.")
    if instant_expander:
        try:
            from scripts.streamlit_expander_motion import repair_expander_motion
        except ModuleNotFoundError:
            from streamlit_expander_motion import repair_expander_motion
        raw = repair_expander_motion(raw, no_cache_advertisements=no_cache_advertisements)
    elif no_cache_advertisements:
        try:
            from scripts.streamlit_forward_cache import repair_forward_cache
        except ModuleNotFoundError:
            from streamlit_forward_cache import repair_forward_cache
        raw = repair_forward_cache(raw)
    return raw.replace(ORIGINAL, REPAIRED, 1)
