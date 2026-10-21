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
TAB_ORIGINAL = b"case`Enter`:case`Tab`:if(t.isOpen&&n.key===`Enter`&&n.preventDefault()"
# A multiple selector keeps its menu open after an explicit option click. The
# next focused option is not another selection: Tab must only leave the menu.
# Do not prevent default focus movement or change Enter/single-select commits.
TAB_REPAIRED = b"case`Enter`:case`Tab`:if(n.key===`Tab`&&t.selectionManager.selectionMode===`multiple`){t.isOpen&&t.close(),n.continuePropagation();break}if(t.isOpen&&n.key===`Enter`&&n.preventDefault()"


def repair_combobox_close(raw, *, virtualizer_resize=False, tab_navigation=True):
    if (sha256(raw).hexdigest() != COMBOBOX_SHA256 or raw.count(CLOSE_ORIGINAL) != 1
            or raw.count(TAB_ORIGINAL) != 1):
        raise RuntimeError("Unexpected locked ComboBox close asset; no bytes were changed.")
    if virtualizer_resize:
        try:
            from scripts.streamlit_virtualizer_resize import repair_virtualizer
        except ModuleNotFoundError:
            from streamlit_virtualizer_resize import repair_virtualizer
        raw = repair_virtualizer(raw)
    raw = raw.replace(CLOSE_ORIGINAL, CLOSE_REPAIRED, 1)
    return raw.replace(TAB_ORIGINAL, TAB_REPAIRED, 1) if tab_navigation else raw
