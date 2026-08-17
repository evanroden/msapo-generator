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


def _tag_sort_key(tag: str) -> tuple:
    """Order asset tags by their unit NUMBER, not their text.

    Registries are inconsistent about padding -- Rochester General uses CH-01
    while United Memorial uses CH-2 -- so a string sort would rank "CH-10"
    before "CH-2". Sort on the trailing integer, falling back to the text when a
    tag carries no number at all.
    """
    numbers = re.findall(r"\d+", tag or "")
    return (0, int(numbers[-1]), tag) if numbers else (1, 0, tag or "")


# Only distinctive equipment nouns are safe enough to trigger an automatic
# lowest-unit choice. Registry descriptions also end in broad words such as
# SYSTEM, UNIT and PUMP; those occur throughout scopes and can otherwise select
# an unrelated asset merely because it has the lowest tag at the site.
_SAFE_TYPE_HEADS = frozenset(
    {
        "BOILER",
        "CHILLER",
        "EXCHANGER",
        "SEPARATOR",
        "SOFTENER",
        "STARTER",
        "TOWER",
        "VFD",
    }
)


def lowest_numbered_of_type(
    assets: Sequence[Mapping[str, str]], *, quote_text: object = "", hint: object = ""
) -> str | None:
    """Pick the lowest-numbered unit when the TYPE is clear but the unit is not.

    Scope text routinely identifies equipment without naming a unit -- "repair
    the chiller", "boiler teardown". The scorer deliberately refuses to break
    those ties, which left the operator with no asset at all in exactly the
    cases where the type was obvious. Product direction is to default to the
    lowest-numbered unit of that type and let the operator change it.

    "Lowest-numbered" means the lowest that EXISTS at the site, not the number
    one: United Memorial's chillers are CH-2 and CH-3, so chiller work there
    resolves to CH-2.

    Only fires when exactly ONE equipment type matches, so a quote touching both
    a chiller and a cooling tower still resolves to nothing rather than guessing
    between them. Matching is on the registry's equipment description appearing
    in the text, which keeps "cooling tower" off "Cooling Tower Fill" and
    "chiller" off "Chiller VFD".
    """
    rows = [
        row
        for row in assets
        if str(row.get("uid", "")).strip() and str(row.get("equipment", "")).strip()
    ]
    if not rows:
        return None

    haystack = _norm(f"{hint or ''} {quote_text or ''}")
    if not haystack:
        return None

    # Group by the equipment's HEAD NOUN rather than its full description.
    # Scope text says "chiller", never "Centrifugal Chiller", so requiring the
    # whole description to appear matched nothing -- which is precisely why the
    # tool kept coming back with no asset. The head noun also keeps the
    # near-misses apart, because theirs differ: "Centrifugal Chiller" -> CHILLER
    # but "Chiller VFD" -> VFD, and "Cooling Tower" -> TOWER but "Cooling Tower
    # Fill" -> FILL. Grouping by noun rather than description also means a site
    # with both a Centrifugal and an Absorption Chiller still resolves to one
    # chiller group.
    matched: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        words = _norm(row.get("equipment")).split()
        if not words:
            continue
        head = words[-1]
        if head not in _SAFE_TYPE_HEADS:
            continue
        if _bounded_contains(haystack, head):
            matched.setdefault(head, []).append(row)
    # More than one type in play (a chiller AND a cooling tower) is genuinely
    # ambiguous; guessing between them is worse than leaving it unset.
    if len(matched) != 1:
        return None

    candidates = next(iter(matched.values()))
    candidates.sort(key=lambda row: _tag_sort_key(str(row.get("asset", ""))))
    return str(candidates[0].get("uid", "")).strip() or None
