"""Initialize the pinned native textarea from its synchronous saved state.

A first focus can precede passive native hydration. If the DOM is blank then,
a native clear produces no input event and the stored text survives the clear.
Only initialization changes; all native dirty, blur and form behavior remains.
"""
from hashlib import sha256

TEXTAREA_BUNDLE = "TextArea.BRlPhbKO.js"
TEXTAREA_SHA256 = "256650eb750b31c872c46f2c5152941fbbfb5e1fe607185c39141198c2baf907"
ORIGINAL = b"useState)(()=>w(i,t)??null)"
REPAIRED = b"useState)(()=>w(i,t)??(t.setValue?E(t):T(t)))"


def repair_textarea_default(raw):
    if sha256(raw).hexdigest() != TEXTAREA_SHA256 or raw.count(ORIGINAL) != 1:
        raise RuntimeError("Unexpected locked textarea asset; no bytes were changed.")
    return raw.replace(ORIGINAL, REPAIRED, 1)
