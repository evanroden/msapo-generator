"""One exact locked React Aria virtual-list resize compatibility repair."""
from hashlib import sha256

VIRTUALIZER_BUNDLE = "fuzzyFilterSelectOptions.Bf8rcmtM.js"
VIRTUALIZER_SHA256 = "1ebdea14d07b36247a221305bfbb455b368a7fe79c86b24f509743c278a29ce6"
VIRTUALIZER_ORIGINAL = b"T(()=>{w(e=>e())},[D]),k({ref:t,box:`border-box`,onResize:(0,J.useCallback)(()=>{C(Sr.flushSync)},[C])});"
# `w` is the existing latest-render event callback for C. Initial, scroll and
# window-resize paths keep their original timing; only this native RO owner
# coalesces work, and its layout-effect cleanup invalidates/cancels pending work.
VIRTUALIZER_REPAIRED = b"""T(()=>{w(e=>e())},[D]);let enfraFrame=(0,J.useRef)(null),enfraActive=(0,J.useRef)(true),enfraQueue=(0,J.useCallback)(()=>{if(!enfraActive.current||enfraFrame.current!==null)return;enfraFrame.current=requestAnimationFrame(()=>{enfraFrame.current=null;if(enfraActive.current)w(Sr.flushSync)})},[w]);T(()=>{enfraActive.current=true;return()=>{enfraActive.current=false;if(enfraFrame.current!==null){cancelAnimationFrame(enfraFrame.current);enfraFrame.current=null}}},[w]),k({ref:t,box:`border-box`,onResize:enfraQueue});"""


def repair_virtualizer(raw):
    if sha256(raw).hexdigest() != VIRTUALIZER_SHA256 or raw.count(VIRTUALIZER_ORIGINAL) != 1:
        raise RuntimeError("Unexpected locked virtual-list asset; no bytes were changed.")
    return raw.replace(VIRTUALIZER_ORIGINAL, VIRTUALIZER_REPAIRED, 1)
