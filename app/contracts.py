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


def guess_uid(text: str | None, contract: str | None, site: str | None) -> str | None:
    """Best-guess the ENFRA Unique Identifier a quote refers to within a
    contract+site — same rule as RRH: longest matching standalone asset tag."""
    if not text:
        return None
    rows = assets_for_site(contract, site)
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
