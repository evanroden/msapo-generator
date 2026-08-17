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

Depended on by app/web_ui.py (the contract/site/asset controls, the routing
snapshot that decides whether those controls are even visible, and the
pre-generation routing gate), app/expense_ui.py (the ENFRA account list and
the is_rrh coding defaults) and app/po_context.py (is_rrh). Everything here is
pure and process-cached: nothing reads or writes Streamlit session state.

app/data/contracts.json is DEPLOYMENT DATA, not a fixture.
tests/test_contracts.py pins its exact size (36 contracts / 106 sites / 11,368
rows) precisely because a truncated or placeholder regeneration would not raise
anywhere in this module -- every helper here degrades to an empty list, so the
only symptom would be sites and assets quietly ceasing to be offered.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RRH_CONTRACT = "Rochester Regional Health"
_DATA_PATH = Path(__file__).parent / "data" / "contracts.json"
# Rows whose facility column was blank in the All-ENFRA export land under this
# exact bucket name. It is a data-quality artifact, not a facility anyone can
# choose, so sites_for_contract() hides it -- casefolded, so a re-export that
# changes its capitalization cannot silently make it selectable again. _data()
# deliberately KEEPS the bucket so those rows stay reachable by UID.
_UNSPECIFIED_SITE = "(unspecified site)"


def _preferred_site_name(current: str, candidate: str) -> str:
    """Choose the more readable spelling for case-only duplicate site names."""
    # First-seen wins UNLESS it is the shouted spelling. The export lists both
    # "REHAB" and "Rehab" for Conway and their order within the JSON is not
    # guaranteed stable across regenerations, so a plain "keep the first" rule
    # would let the visible site label flip between deployments -- and a flipped
    # label silently empties assets_for_site(), which keys on the exact string.
    # Note isupper() ignores digits and punctuation: "REHAB 2" counts as
    # shouted, "3 North" does not.
    if current.isupper() and not candidate.isupper():
        return candidate
    return current


@lru_cache(maxsize=1)
def _data() -> dict:
    """Return normalized contract -> site -> asset rows.

    The source export contains at least one case-only duplicate site name
    (Conway: ``REHAB`` and ``Rehab``). Merge those at load time and de-duplicate
    rows by UID so users see one site and one coherent asset list.

    Cached for the life of the process. The file is ~11k rows and is immutable
    for the life of a deployment; a regenerated contracts.json is picked up by a
    restart, which is intended rather than a gap to close with a reload hook.

    Deliberately RAISES on a missing or malformed file instead of degrading.
    Every helper below returns an empty list for an unknown contract, so a
    swallowed load error would present identically to "this account has no
    sites" on every screen, with no error text anywhere to explain it.
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
            # UID de-duplication applies ONLY on this merge path, because a
            # case-only duplicate is the one situation where the export is known
            # to list the same physical asset twice. Rows for a site with no
            # case twin are copied verbatim above, so a future export that
            # repeats a UID inside a single site shows it twice in the dropdown
            # rather than losing one -- visible beats silent here.
            seen_uids = {row[0] for row in current_rows if row}
            for row in rows:
                if row and row[0] not in seen_uids:
                    current_rows.append(row)
                    seen_uids.add(row[0])
            merged[key] = (preferred, current_rows)

        # Safe as a dict comprehension only because every surviving key is a
        # distinct casefold of a whitespace-collapsed name, so two entries can
        # never collide on ``name`` and drop one site's entire asset list.
        normalized[contract] = {name: rows for name, rows in merged.values()}
    return normalized


def contract_names() -> list[str]:
    """All known contracts — RRH first, then the rest alphabetically."""
    # RRH is prepended unconditionally because it is NOT in contracts.json -- it
    # has its own flow in app/config.py and app/assets.py. Deriving this list
    # from the registry alone would drop the highest-volume account out of both
    # the PO contract selector and the expense account selector. The filter
    # exists so a future export that starts including RRH cannot list it twice.
    others = sorted(_data().keys())
    return [RRH_CONTRACT] + [c for c in others if c != RRH_CONTRACT]


def is_known_contract(contract: str | None) -> bool:
    """Whether a value is a real configured contract.

    Exact and case-sensitive, and used as a GATE rather than a hint:
    web_ui._routing_for_generation drops the entire confirmed routing when a
    mirrored contract fails here, so relaxing this to a casefolded or fuzzy
    compare would let an account name retired by a contracts.json edit ride
    onto a freshly generated PO. The selector's placeholder option fails here by
    design -- that is what keeps it from being treated as a real account.
    """
    return bool(contract) and (contract == RRH_CONTRACT or contract in _data())


def is_rrh(contract: str | None) -> bool:
    """Whether this contract takes the dedicated RRH flow, not the registry one.

    Exact string identity on purpose -- never a substring or casefolded test.
    Every caller (web_ui routing and asset controls, po_context field rules,
    expense_ui coding defaults) switches to an entirely different data source on
    the result, so a false positive looks up RRH facilities for a non-RRH
    account, finds nothing, and renders empty dropdowns with no error.
    """
    return contract == RRH_CONTRACT


def sites_for_contract(contract: str | None) -> list[str]:
    """Selectable site names for a non-RRH contract, sorted.

    Export-only ``(unspecified site)`` buckets are retained in the source data
    but hidden from the user because they are not an actionable facility choice.

    The contract key is matched exactly; an unknown or misspelled contract
    yields [] rather than raising, which is why is_known_contract() is the gate
    upstream. Sorting is plain string order, so an all-caps site name sorts
    ahead of a mixed-case one -- cosmetic only, and the case-merge in _data()
    keeps it from producing near-duplicate neighbours.
    """
    if not contract:
        return []
    return sorted(
        site for site in _data().get(contract, {})
        if site.casefold() != _UNSPECIFIED_SITE.casefold()
    )


def assets_for_site(contract: str | None, site: str | None) -> list[dict[str, str]]:
    """Assets for a contract+site as {uid, asset, equipment, serves} dicts.

    Both keys are matched EXACTLY. A site string that no longer exists under
    that spelling -- the pre-merge "REHAB" restored from an old session, or a
    label from a previous deployment's export -- returns [] with no error and
    the asset dropdown simply disappears. web_ui sanitizes stored selections
    against sites_for_contract() before rendering for precisely this reason
    (FM-C08); do not lean on this function to detect a stale value.

    Unpacking assumes every registry row is exactly [uid, asset, equipment,
    serves]. That shape is pinned by the row-count assertions in
    tests/test_contracts.py, not here -- a short row raises ValueError rather
    than degrading, which is the right failure for corrupt deployment data.
    """
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

    Deliberately NOT app.assets.asset_label. That one serves the hardcoded RRH
    table, where every row is guaranteed both ``asset`` and ``equipment``, and
    it indexes those keys directly. Registry rows routinely carry a blank
    equipment or serves and occasionally a blank asset tag, so this variant
    falls through to the UID and omits empty segments. Merging the two would
    either raise KeyError on registry rows or emit labels like " · " for them.
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

    ORDERING IS LOAD-BEARING and both steps at the bottom are required. The
    de-dupe must run BEFORE the sort, so a phrase reachable under two contracts
    cannot change winner with dict iteration order. The sort must be by phrase
    LENGTH descending, so "main hospital" (MCH) is tested before "hospital"
    (Conway). Python's sort is stable, so equal-length ties fall back to
    insertion order: registry sites first, RRH aliases second.

    WARNING -- this index contains bare English words, because the export
    genuinely names Conway sites "Hospital" and "Rehab" and an EAMC site
    "Valley". Those single words are live matchable phrases for those accounts.
    Read the KNOWN DEFECT note on match_facility() before adding any new short
    phrase here, and before assuming a match implies a real facility.
    """
    # Deferred, and not only for the import cycle noted below: app/config.py
    # runs load_dotenv() and creates OUTPUT_DIR as import-time side effects, and
    # app/contracts.py is imported by pure registry tests that must trigger
    # neither. Keep this local even after verifying no cycle exists today.
    from app.config import FACILITIES, FACILITY_SHORT_NAMES  # local import avoids a cycle

    entries: list[tuple[str, str, str]] = []
    for contract in _data():
        for site in sites_for_contract(contract):
            s = site.strip()
            if s:
                entries.append((s.lower(), contract, s))
    for key, fac in FACILITIES.items():
        short = FACILITY_SHORT_NAMES.get(key)
        # An RRH facility with no short name is skipped SILENTLY: it can never
        # be auto-routed and nothing warns about it. The two dicts are in sync
        # today; add a facility to FACILITIES alone and quotes for it simply
        # stop being recognized, with no symptom to trace back to here.
        if not short:
            continue
        # A set per facility, so the non-deterministic iteration order cannot
        # leak: every term here maps to the SAME (contract, short) pair.
        for term in {fac["name"], *fac.get("aliases", [])}:
            # Only end-stripped, never whitespace-collapsed, while
            # match_facility() collapses its haystack. A FACILITIES name or
            # alias containing a double space would therefore never match --
            # silently. Registry site names are already collapsed in _data().
            term = term.strip()
            # Three characters minimum. Two-letter hospital aliases ("ED", "OR",
            # "GH") occur inside ordinary quote prose often enough that even a
            # whole-word match on them mis-routes. The five-digit ZIP aliases
            # are the shortest entries this floor is meant to let through.
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

    ``facility_name`` is exhausted COMPLETELY before ``quote_text`` -- all
    phrases against the first haystack, then all phrases against the second --
    so a recognised facility name always beats an incidental mention buried in
    the quote body.

    KNOWN DEFECT, reported and not fixed here: this matches phrases, not
    facilities, so an UNKNOWN facility whose name merely CONTAINS a registry
    site word is routed to that site's contract. "Mercy Hospital" resolves to
    ("Conway", "Hospital") and "Community Rehab Center" to ("Conway", "Rehab"),
    because Conway really does have sites by those names. Nothing downstream
    can distinguish that from a real hit: web_ui's routing snapshot then reports
    routing as complete, so the contract and site controls stay inside the
    COLLAPSED corrections panel and the operator never sees the wrong account
    unless they open it. Do NOT try to improve recall by lowering the length
    floor in _site_index() or by dropping the lookarounds below -- both widen
    exactly this failure.

    The lookarounds are explicit character classes rather than a word-boundary
    escape so that a phrase ending in punctuation ("st. mary's") still anchors
    and so a ZIP alias still matches inside "Rochester NY 14621-1234".
    re.escape() is mandatory: real site names contain ".", "(", "-" and "&".
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
    Returns None when nothing is confidently identified.

    Three stages, most confident first, and the order is deliberate:

    1. ``hint`` via match_asset_hint, which returns None for a hallucinated tag
       rather than mis-selecting a real asset.
    2. A UID appearing anywhere in the quote text. This branch is a bare
       substring test with NO word-boundary guard, unlike stage 3. That is safe
       only because registry UIDs are 11-22 characters and highly distinctive
       ("BEA-CH-1A-AHBD"); do not reuse the pattern for shorter identifiers. It
       returns the FIRST matching row in export order, not the longest match.
    3. The longest standalone asset TAG ("CH-1"). Its boundary class includes
       "-", which is what stops "AHU-1" matching inside "AHU-11" or
       "RTU-AHU-1". Dropping the hyphen from either lookaround produces
       confident matches on the wrong physical unit, with no warning.

    Returns None -- never a nearest guess -- when nothing is identified; the
    caller then defaults to "No asset applicable".

    Structurally this mirrors app.assets.guess_asset_id, which runs the same
    three stages over the hardcoded RRH table. They stay separate because that
    one keys on facility_key and this one on contract+site, and because registry
    rows may carry blank uid/asset values the RRH table never has -- hence the
    truthiness guards below that its twin does not need.
    """
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
