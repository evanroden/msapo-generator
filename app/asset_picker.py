"""Bounded, operator-driven search for large non-RRH asset registries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

LARGE_ASSET_SITE_THRESHOLD = 200
ASSET_SEARCH_LIMIT = 25
_SEARCH_FIELDS = ("asset", "uid", "equipment", "serves")


def search_asset_uids(
    assets: Sequence[Mapping[str, str]], query: str, *, limit: int = ASSET_SEARCH_LIMIT
) -> list[str]:
    """Find site UIDs by all typed terms without returning a whole-site option list.

    Search-only matching is case-insensitive and ignores tag/UID separators.
    It is not an automatic asset guess; the operator still selects a result.
    """
    terms = [word.casefold() for word in str(query or "").split()]
    if not terms or limit < 1:
        return []
    compact_terms = [re.sub(r"[^\w]+", "", word) for word in terms]
    matches: list[str] = []
    seen: set[str] = set()
    for asset in assets:
        uid = str(asset.get("uid") or "").strip()
        if not uid or uid in seen:
            continue
        fields = " ".join(str(asset.get(field) or "") for field in _SEARCH_FIELDS)
        plain = fields.casefold()
        compact = re.sub(r"[^\w]+", "", plain)
        if all(
            term in plain or (normalized and normalized in compact)
            for term, normalized in zip(terms, compact_terms)
        ):
            matches.append(uid)
            seen.add(uid)
            if len(matches) >= limit:
                break
    return matches
