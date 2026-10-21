"""Keep native multiple-selection close separate from selection changes.

The controlled value can lag a pending widget update. Re-emitting it on close
can overwrite that update even when the close callback is the latest committed
one. Actual option selection already calls the native selection setter. Single
selection commit, custom input handling, validation and real dismissal stay native.
"""
from hashlib import sha256

COMBOBOX_BUNDLE = "fuzzyFilterSelectOptions.Bf8rcmtM.js"
COMBOBOX_SHA256 = "1ebdea14d07b36247a221305bfbb455b368a7fe79c86b24f509743c278a29ce6"
CLOSE_ORIGINAL = b"(t||o===`multiple`||T!==n)&&(e.onSelectionChange?.(C),e.onChange?.(v)),V(n),z()"
CLOSE_REPAIRED = b"o!==`multiple`&&(t||o===`multiple`||T!==n)&&(e.onSelectionChange?.(C),e.onChange?.(v)),V(n),z()"


def repair_combobox_close(raw, *, virtualizer_resize=False):
    if sha256(raw).hexdigest() != COMBOBOX_SHA256 or raw.count(CLOSE_ORIGINAL) != 1:
        raise RuntimeError("Unexpected locked ComboBox close asset; no bytes were changed.")
    if virtualizer_resize:
        try:
            from scripts.streamlit_virtualizer_resize import repair_virtualizer
        except ModuleNotFoundError:
            from streamlit_virtualizer_resize import repair_virtualizer
        raw = repair_virtualizer(raw)
    return raw.replace(CLOSE_ORIGINAL, CLOSE_REPAIRED, 1)
