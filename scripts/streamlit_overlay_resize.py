"""One exact locked React Aria overlay-position resize compatibility repair."""
from hashlib import sha256

OVERLAY_BUNDLE = "Tooltip.DJg7muty.js"
OVERLAY_SHA256 = "5e80c1c53af853d75e4116c2a3a036016395f6175b1d9089a80b65444750b36a"
OVERLAY_ORIGINAL = b";p(T,C),Qt(T),Xt({ref:i,onResize:T}),Xt({ref:r,onResize:T});let E="
OVERLAY_REPAIRED = b""";let enfraPositionFrame=(0,u.useRef)(null),enfraPositionActive=(0,u.useRef)(true),enfraResizePosition=(0,u.useCallback)(()=>{if(!enfraPositionActive.current||enfraPositionFrame.current!==null)return;enfraPositionFrame.current=requestAnimationFrame(()=>{enfraPositionFrame.current=null;if(enfraPositionActive.current)T()})},[T]);p(()=>{enfraPositionActive.current=true;return()=>{enfraPositionActive.current=false;if(enfraPositionFrame.current!==null){cancelAnimationFrame(enfraPositionFrame.current);enfraPositionFrame.current=null}}},[T]);p(T,C),Qt(T),Xt({ref:i,onResize:enfraResizePosition}),Xt({ref:r,onResize:enfraResizePosition});let E="""


def repair_overlay(raw):
    if sha256(raw).hexdigest() != OVERLAY_SHA256 or raw.count(OVERLAY_ORIGINAL) != 1:
        raise RuntimeError("Unexpected locked overlay position asset; no bytes were changed.")
    return raw.replace(OVERLAY_ORIGINAL, OVERLAY_REPAIRED, 1)
