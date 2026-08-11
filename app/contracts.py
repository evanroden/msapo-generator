"""
Multi-contract asset registry for the project-agnostic flow.

Rochester Regional Health (RRH) keeps its own dedicated flow — short site
names, autofilled cost codes, and a privately configured administrator — driven
by app/config.py and app/assets.py, and intentionally NOT stored here.

Every other ENFRA contract is loaded from app/data/contracts.json
(generated from the All-ENFRA asset export) and gets the generic flow:
contract → site → asset dropdowns, a free-text cost code, and a per-contract
recipient. Sites/assets that don't exist for a contract simply don't appear,
and a site with no asset tags shows no asset dropdown at all.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RRH_CONTRACT = "Rochester Regional Health"
_DATA_PATH = Path(__file__).parent / "data" / "contracts.json"
_UNSPECIFIED_SITE = "(unspecified site)"


def _preferred_site_name(current: str, candidate: str) -> str:
    """Choose the more readable spelling for case-only duplicate site names."""
    if current.isupper() and not candidate.isupper():
        return candidate
    return current


@lru_cache(maxsize=1)
def _data() -> dict:
    """Return normalized contract -> site -> asset rows.

    The source export contains at least one case-only duplicate site name
    (Conway: ``REHAB`` and ``Rehab``). Merge those at load time and de-duplicate
    rows by UID so users see one site and one coherent asset list.
    """
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    normalized: dict[str, dict[str, list[list[str]]]] = {}
    for contract, sites in raw.items():
        merged: dict[str, tuple[str, list[list[str]]]] = {}
        for site, rows in sites.items():
            clean_site = " ".join(site.split())
            key = clean_site.casefold()
            if key not in merged:
                merged[key] = (clean_site, list(rows))
                continue

            current_name, current_rows = merged[key]
            preferred = _preferred_site_name(current_name, clean_site)
            seen_uids = {row[0] for row in current_rows if row}
            for row in rows:
                if row and row[0] not in seen_uids:
                    current_rows.append(row)
                    seen_uids.add(row[0])
            merged[key] = (preferred, current_rows)

        normalized[contract] = {name: rows for name, rows in merged.values()}
    return normalized


def contract_names() -> list[str]:
    """All known contracts — RRH first, then the rest alphabetically."""
    others = sorted(_data().keys())
    return [RRH_CONTRACT] + [c for c in others if c != RRH_CONTRACT]


def is_known_contract(contract: str | None) -> bool:
    """Whether a value is a real configured contract."""
    return bool(contract) and (contract == RRH_CONTRACT or contract in _data())


def is_rrh(contract: str | None) -> bool:
    return contract == RRH_CONTRACT


def sites_for_contract(contract: str | None) -> list[str]:
    """Selectable site names for a non-RRH contract, sorted.

    Export-only ``(unspecified site)`` buckets are retained in the source data
    but hidden from the user because they are not an actionable facility choice.
    """
    if not contract:
        return []
    return sorted(
        site for site in _data().get(contract, {})
        if site.casefold() != _UNSPECIFIED_SITE.casefold()
    )


def assets_for_site(contract: str | None, site: str | None) -> list[dict[str, str]]:
    """Assets for a contract+site as {uid, asset, equipment, serves} dicts."""
    if not contract or not site:
        return []
    rows = _data().get(contract, {}).get(site, [])
    return [
        {"uid": u, "asset": a, "equipment": e, "serves": s}
        for (u, a, e, s) in rows
    ]


def asset_label(a: dict[str, str]) -> str:
    """Human-readable asset name, e.g. 'CH-1 · Centrifugal Chiller (Chilled Water)'.

    Falls back gracefully when equipment or serves is blank (common outside RRH).
    """
    label = a.get("asset") or a.get("uid") or "Asset"
    if a.get("equipment"):
        label += f" · {a['equipment']}"
    if a.get("serves"):
        label += f" ({a['serves']})"
    return label


@lru_cache(maxsize=1)
def _site_index() -> list[tuple[str, str, str]]:
    """(matchable_lowercase_phrase, contract, site_label), longest phrase first.

    Covers every non-RRH site plus RRH facilities (names + aliases) so a quote's
    facility text can be resolved to a contract + site regardless of contract.
    """
    from app.config import FACILITIES, FACILITY_SHORT_NAMES  # local import avoids a cycle

    entries: list[tuple[str, str, str]] = []
    for contract in _data():
        for site in sites_for_contract(contract):
            s = site.strip()
            if s:
                entries.append((s.lower(), contract, s))
    for key, fac in FACILITIES.items():
        short = FACILITY_SHORT_NAMES.get(key)
        if not short:
            continue
        for term in {fac["name"], *fac.get("aliases", [])}:
            term = term.strip()
            if len(term) >= 3:
                entries.append((term.lower(), RRH_CONTRACT, short))
    # De-dupe, then longest phrase first so the most specific match wins.
    entries = list(dict.fromkeys(entries))
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return entries


def match_facility(facility_name: str | None, quote_text: str | None = None) -> tuple[str | None, str | None]:
    """Best-effort (contract, site) for a quote, from its extracted facility name
    (preferred) then the quote text. Whole-phrase, word-boundary matches only;
    the longest known site name wins. Returns (None, None) when nothing matches.
    """
    index = _site_index()
    for haystack in (facility_name, quote_text):
        if not haystack:
            continue
        h = re.sub(r"\s+", " ", haystack.lower())
        for phrase, contract, site in index:
            if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", h):
                return contract, site
    return None, None


def guess_uid(text: str | None, contract: str | None, site: str | None,
              hint: str | None = None) -> str | None:
    """Best-guess the ENFRA Unique Identifier a quote refers to within a
    contract+site: the AI-extracted asset tag ("hint") if it resolves to a real
    asset, then the longest standalone asset tag/UID found in the quote text.
    Returns None when nothing is confidently identified."""
    from app.assets import match_asset_hint  # shared tag-normalizing matcher

    rows = assets_for_site(contract, site)
    hinted = match_asset_hint(hint, rows)
    if hinted:
        return hinted
    if not text:
        return None
    upper = text.upper()
    for a in rows:
        if a["uid"] and a["uid"].upper() in upper:
            return a["uid"]
    best_uid, best_len = None, 0
    for a in rows:
        tag = (a["asset"] or "").upper()
        if tag and re.search(r"(?<![A-Z0-9-])" + re.escape(tag) + r"(?![A-Z0-9-])", upper):
            if len(tag) > best_len:
                best_len, best_uid = len(tag), a["uid"]
    return best_uid
