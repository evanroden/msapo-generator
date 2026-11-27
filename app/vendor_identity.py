"""Role boundaries for the operator, separate from requester identity."""
from __future__ import annotations

import re
import unicodedata


def is_operator_vendor_name(name: str | None) -> bool:
    """The operator must never be offered or learned as a vendor rep.

    Match the full identity, including common initial/comma formats. Do not
    reject someone merely because they share a first name or surname.
    """
    text = unicodedata.normalize("NFKC", str(name or "")).casefold()
    parts = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
    if len(parts) < 2:
        return False
    return ((parts[0] == "evan" and parts[-1] == "roden")
            or ("," in text and parts[0] == "roden" and parts[1] == "evan"))
