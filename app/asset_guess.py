"""Deterministic asset suggestion over the selected account/site registry.

The analyzer supplies a human-readable hint, while the account registry owns
the full Asset ID exported to Smartsheet.  This scorer selects only a unique
best match; it never invents an ID or silently chooses the first dropdown row.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


def _norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _bounded_contains(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    return bool(re.search(r"(?<![A-Z0-9])" + re.escape(needle) + r"(?![A-Z0-9])", haystack))


def guess_asset_uid(
    assets: Sequence[Mapping[str, str]],
    *,
    quote_text: object = "",
    hint: object = "",
) -> str | None:
    """Return a full registry UID when one asset is the unique best match."""
    rows = [row for row in assets if str(row.get("uid", "")).strip()]
    if not rows:
        return None

    raw_quote = str(quote_text or "").upper()
    raw_hint = str(hint or "").upper()
    norm_quote = _norm(raw_quote)
    norm_hint = _norm(raw_hint)

    scored: list[tuple[int, str]] = []
    for row in rows:
        uid = str(row.get("uid", "")).strip()
        tag = str(row.get("asset", "")).strip()
        equipment = str(row.get("equipment", "")).strip()
        serves = str(row.get("serves", "")).strip()
        uid_norm = _norm(uid)
        tag_norm = _norm(tag)
        equipment_norm = _norm(equipment)
        serves_norm = _norm(serves)
        score = 0

        if uid_norm and _bounded_contains(norm_quote, uid_norm):
            score += 150
        if uid_norm and _bounded_contains(norm_hint, uid_norm):
            score += 170
        if tag_norm and _bounded_contains(norm_quote, tag_norm):
            score += 105
        if tag_norm and _bounded_contains(norm_hint, tag_norm):
            score += 125
        if uid_norm and norm_hint == uid_norm:
            score += 200
        if tag_norm and norm_hint == tag_norm:
            score += 180
        if equipment_norm and equipment_norm in norm_hint:
            score += 45
        elif equipment_norm and equipment_norm in norm_quote:
            score += 24
        if serves_norm and serves_norm in norm_hint:
            score += 10

        # A unit number in the hint is a strong discriminator when it also
        # appears in the registry tag.  Equipment type alone often ties across
        # several rows and therefore will not select an arbitrary unit.
        hint_numbers = set(re.findall(r"\d+", norm_hint))
        tag_numbers = set(re.findall(r"\d+", tag_norm))
        if hint_numbers and hint_numbers & tag_numbers:
            score += 55

        if score:
            scored.append((score, uid))

    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_uid = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else -1
    if best_score < 45 or best_score == runner_up:
        return None
    return best_uid
