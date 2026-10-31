"""Fail-closed parsing of a Monthly source page's review/ownership identity.

Canonical source pages are at most 500, but allow six ASCII digits to retain
historical padded references while preventing oversized int conversions.
This parser supplies *identity only*, never source review or page approval.
"""

import re


def page_identity(reference):
    """Return the stable (source id, positive page) or None for bad references."""
    if not isinstance(reference, str):
        return None
    parts = reference.split(":")
    if len(parts) != 3 or re.fullmatch(r"[0-9]{1,6}", parts[1]) is None:
        return None
    number = int(parts[1])
    return (parts[0], number) if number >= 1 else None
