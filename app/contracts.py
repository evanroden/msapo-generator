"""
Multi-contract asset registry for the project-agnostic flow.

Rochester Regional Health (RRH) keeps its own dedicated flow — short site
names, autofilled cost codes, David as the recipient — driven by app/config.py
and app/assets.py, and is intentionally NOT stored here.

Every other ENFRA contract is loaded from app/data/contracts.json
(generated from the All-ENFRA asset export) and gets the generic flow:
contract → site → asset dropdowns, a free-text cost code, and a per-contract
recipient.  Sites/assets that don't exist for a contract simply don't appear,
and a site with no asset tags shows no asset dropdown at all.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RRH_CONTRACT = "Rochester Regional Health"
_DATA_PATH = Path(__file__).parent / "data" / "contracts.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    """contract -> site -> list of [uid, asset, equipment, serves]."""
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def contract_names() -> list[str]:
    """All selectable contracts — RRH first, then the rest alphabetically."""
    others = sorted(_data().keys())
    return [RRH_CONTRACT] + [c for c in others if c != RRH_CONTRACT]


def is_rrh(contract: str | None) -> bool:
    return contract == RRH_CONTRACT


def sites_for_contract(contract: str | None) -> list[str]:
    """Site names available for a (non-RRH) contract, sorted."""
    if not contract:
        return []
    return sorted(_data().get(contract, {}).keys())


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
    for contract, sites in _data().items():
        for site in sites:
            s = site.strip()
            if s and s.lower() != "(unspecified site)":
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
    the longest known site name wins. Returns (None, None) when nothing matches
    — callers then fall back to the default (RRH)."""
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
