"""Exact locked React Aria overlay positioning and queued-scroll repairs."""
from hashlib import sha256

OVERLAY_BUNDLE = "Tooltip.DJg7muty.js"
OVERLAY_SHA256 = "5e80c1c53af853d75e4116c2a3a036016395f6175b1d9089a80b65444750b36a"
OVERLAY_ORIGINAL = b";p(T,C),Qt(T),Xt({ref:i,onResize:T}),Xt({ref:r,onResize:T});let E="
OVERLAY_REPAIRED = b""";let enfraPositionFrame=(0,u.useRef)(null),enfraPositionActive=(0,u.useRef)(true),enfraResizePosition=(0,u.useCallback)(()=>{if(!enfraPositionActive.current||enfraPositionFrame.current!==null)return;enfraPositionFrame.current=requestAnimationFrame(()=>{enfraPositionFrame.current=null;if(enfraPositionActive.current)T()})},[T]);p(()=>{enfraPositionActive.current=true;return()=>{enfraPositionActive.current=false;if(enfraPositionFrame.current!==null){cancelAnimationFrame(enfraPositionFrame.current);enfraPositionFrame.current=null}}},[T]);p(T,C),Qt(T),Xt({ref:i,onResize:enfraResizePosition}),Xt({ref:r,onResize:enfraResizePosition});let E="""
SCROLL_ORIGINAL = b"""function Jt(e){let{triggerRef:t,isOpen:n,onClose:r}=e;(0,u.useEffect)(()=>{if(!n||r===null)return;let e=e=>{let n=z(e);if(!t.current||n instanceof Node&&!L(n,t.current)||n instanceof HTMLInputElement||n instanceof HTMLTextAreaElement)return;let i=r||qt.get(t.current);i&&i()};return window.addEventListener(`scroll`,e,!0),()=>{window.removeEventListener(`scroll`,e,!0)}},[n,r,t])}"""
# Opening can occur after scrolling has moved the input but before that scroll's
# queued event is dispatched. Compare against the positions at listener setup;
# an already-completed movement must not immediately dismiss the new popup.
# A subsequent ancestor/document movement, native close actions, input scrolling
# exclusions and the original listener cleanup retain their existing behavior.
# No timer, global event suppression, DOM write or input replacement is added.
SCROLL_QUEUED_ONLY = b"""function Jt(e){let{triggerRef:t,isOpen:n,onClose:r}=e;(0,u.useEffect)(()=>{if(!n||r===null)return;const enfraScrollPositions=new WeakMap,enfraScrollRead=node=>{const target=node===window||node===document?document.scrollingElement||document.documentElement:node;return target&&Number.isFinite(target.scrollLeft)&&Number.isFinite(target.scrollTop)?[target.scrollLeft,target.scrollTop]:null},enfraScrollRemember=node=>{const position=enfraScrollRead(node);if(position)enfraScrollPositions.set(node,position);return position};for(let ancestor=t.current;ancestor;ancestor=ancestor.parentNode||ancestor.host)enfraScrollRemember(ancestor);enfraScrollRemember(window);enfraScrollRemember(document);let e=e=>{let n=z(e);if(!t.current||n instanceof Node&&!L(n,t.current)||n instanceof HTMLInputElement||n instanceof HTMLTextAreaElement)return;const before=enfraScrollPositions.get(n),current=enfraScrollRemember(n);if(before&&current&&before[0]===current[0]&&before[1]===current[1])return;let i=r||qt.get(t.current);i&&i()};return window.addEventListener(`scroll`,e,!0),()=>{window.removeEventListener(`scroll`,e,!0)}},[n,r,t])}"""

# Passive listener replacement can lag a committed selection. Native ComboBox
# close replays its controlled value; dispatch through the existing insertion-
# effect-backed helper so an old listener cannot replay an older render's value.
# Retain the exact previous bytes above for immutable-generation upgrades.
SCROLL_REPAIRED = SCROLL_QUEUED_ONLY.replace(
    b"onClose:r}=e;(0,u.useEffect)",
    b"onClose:r}=e;const enfraClose=Ze(()=>{if(!n||r===null||!t.current)return;let i=r||qt.get(t.current);i&&i()});(0,u.useEffect)",
    1,
).replace(b"let i=r||qt.get(t.current);i&&i()};return window", b"enfraClose()};return window", 1)


def repair_overlay(raw, *, queued_scroll=True, latest_scroll_close=True):
    if (sha256(raw).hexdigest() != OVERLAY_SHA256 or raw.count(OVERLAY_ORIGINAL) != 1
            or raw.count(SCROLL_ORIGINAL) != 1):
        raise RuntimeError("Unexpected locked overlay position asset; no bytes were changed.")
    repaired = raw.replace(OVERLAY_ORIGINAL, OVERLAY_REPAIRED, 1)
    scroll = SCROLL_REPAIRED if latest_scroll_close else SCROLL_QUEUED_ONLY
    return repaired.replace(SCROLL_ORIGINAL, scroll, 1) if queued_scroll else repaired
