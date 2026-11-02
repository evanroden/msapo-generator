"""Initialize a native text input before its first focus can deliver an edit.

The pinned client initializes displayed text from the widget manager alone,
then supplies the protobuf default in a passive effect. A newly mounted key
can therefore receive native input while blank, before that effect restores
the saved value. Use the same native initial-state precedence synchronously.
All change, blur, form, password and later server-update behavior stays native.
"""
from hashlib import sha256

TEXT_INPUT_BUNDLE = "TextInput.DGmsvknN.js"
TEXT_INPUT_SHA256 = "9fceba0a0a68612b6f90d56751b89234109782e19242da3ccb606d1db700b212"
ORIGINAL = b"useState)(()=>k(i,t)??null)"
REPAIRED = b"useState)(()=>k(i,t)??(t.setValue?j(t):A(t)))"


def repair_text_input_default(raw):
    if sha256(raw).hexdigest() != TEXT_INPUT_SHA256 or raw.count(ORIGINAL) != 1:
        raise RuntimeError("Unexpected locked text-input asset; no bytes were changed.")
    return raw.replace(ORIGINAL, REPAIRED, 1)
