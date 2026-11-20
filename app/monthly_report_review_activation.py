"""A visibility receipt for the draft Review; never reads or submits report widgets.

The single-pixel marker only requests Review assembly after the user reaches
that part of the continuous Monthly workspace. A native button remains the
keyboard/no-JavaScript fallback. All content comes from the server-side draft.
"""
from functools import lru_cache

import streamlit as st
from streamlit.runtime import Runtime


HTML = '<span class="monthly-review-activation-marker" aria-hidden="true"></span>'
CSS = '.monthly-review-activation-marker { display:block; width:1px; height:1px; }'
JS = r"""
export default function(component) {
    const {parentElement, data, setStateValue} = component;
    const marker = parentElement.querySelector('.monthly-review-activation-marker');
    marker._reviewCleanup?.();
    let active = true, timer = null;
    const app = (parentElement.host || parentElement).closest('[data-testid="stApp"]');
    const identity = data.identity;
    function blocked() {
        const running = app?.getAttribute('data-test-script-state');
        const gate = app && window.__enfraPreviewNativeEditGates?.get(app);
        // An edit/blur/submit full rerun wins over this disposable view request.
        return Boolean((running && running !== 'notRunning') || gate?.pending);
    }
    function sendWhenVisible() {
        timer = null;
        if (!active || data.attempted || document.hidden ||
            marker._reviewSentIdentity === identity) return;
        if (blocked()) { schedule(); return; }
        const rect = marker.getBoundingClientRect();
        const viewport = window.visualViewport;
        const top = viewport?.offsetTop || 0, left = viewport?.offsetLeft || 0;
        const right = left + (viewport?.width || window.innerWidth);
        const bottom = top + (viewport?.height || window.innerHeight);
        if (!(rect.width > 0 && rect.height > 0 && rect.right > left &&
              rect.left < right && rect.bottom > top && rect.top < bottom)) return;
        marker._reviewSentIdentity = identity;
        // Only revision and visibility; no text, file content or form mutation.
        setStateValue('activation', {identity, visible:true});
    }
    function schedule() {
        if (!active) return;
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(sendWhenVisible, 200);
    }
    const observer = new IntersectionObserver(schedule, {rootMargin:'0px',threshold:0});
    observer.observe(marker);
    const appObserver = app ? new MutationObserver(schedule) : null;
    appObserver?.observe(app, {attributes:true,attributeFilter:['data-test-script-state']});
    document.addEventListener('visibilitychange', schedule);
    schedule();
    function cleanup() {
        if (!active) return;
        active = false;
        observer.disconnect();
        appObserver?.disconnect();
        document.removeEventListener('visibilitychange', schedule);
        if (timer !== null) clearTimeout(timer);
        if (marker._reviewCleanup === cleanup) marker._reviewCleanup = null;
    }
    marker._reviewCleanup = cleanup;
    return cleanup;
}
"""


def valid_activation(value, identity):
    """Reject missing, malformed or obsolete client visibility receipts.

    Streamlit hands a v2 component's state over as its AttributeDictionary (a
    dict subclass), so accept any mapping of dict type, not only a plain dict.
    """
    if not isinstance(value, dict) or type(identity) is not str or len(identity) != 64:
        return False
    signal = value.get("activation")
    return (isinstance(signal, dict) and signal.get("visible") is True
            and type(signal.get("identity")) is str and signal["identity"] == identity)


@lru_cache(maxsize=2)
def _component(_runtime):
    return st.components.v2.component(
        "monthly_review_activation", html=HTML, css=CSS, js=JS)


def render_activation(*, key, identity, attempted, on_change):
    return _component(Runtime.instance())(
        key=key, data={"identity": identity, "attempted": bool(attempted)},
        default={"activation": None}, on_activation_change=on_change,
        height="content")
