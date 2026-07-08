"""
ENFRA asset registry (Appendix B).

Maps every known ENFRA Unique Identifier to its facility so the UI can
offer a site-filtered asset dropdown and take a best-guess at the asset a
quote refers to.  Regenerate from the source asset-list export if it changes.
"""

from __future__ import annotations

import re

# Asset-list site codes -> facility keys used in config.FACILITIES
ASSET_SITE_TO_FACILITY: dict[str, str] = {
    "CPH": "canton_potsdam",
    "CSHC": "clifton_springs",
    "NWCH": "newark_wayne",
    "RGH": "rochester_general",
}

# Each asset: uid, site_code, facility_key, asset tag, equipment type
ASSETS: list[dict[str, str]] = [
    {"uid": "EEA-ACC-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-1", "equipment": "C02-COOL-0-100T AC RECIP CHILLER"},
    {"uid": "EEA-ACC-2-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-2", "equipment": "C02-COOL-0-100T AC RECIP CHILLER"},
    {"uid": "EEA-ACC-3-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-3", "equipment": "C02-COOL-0-100T AC RECIP CHILLER"},
    {"uid": "EEA-ACC-4-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-4", "equipment": "C02-COOL-0-100T AC RECIP CHILLER"},
    {"uid": "EEA-AS-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "AS-1", "equipment": "C07-COOL-AIR SEPARATOR"},
    {"uid": "EEA-ACC-1STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-1STR", "equipment": "B18-BAS VFD INTEGRATION CONTROL"},
    {"uid": "EEA-ACC-2STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-2STR", "equipment": "B18-BAS VFD INTEGRATION CONTROL"},
    {"uid": "EEA-ACC-3STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-3STR", "equipment": "B18-BAS VFD INTEGRATION CONTROL"},
    {"uid": "EEA-ACC-4STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-4STR", "equipment": "B18-BAS VFD INTEGRATION CONTROL"},
    {"uid": "EEA-CHWP-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "CHWP-1", "equipment": "P16-PUMP (ALL HP) CHILL WATER PUMP"},
    {"uid": "EEA-CHWP-2-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "CHWP-2", "equipment": "P16-PUMP (ALL HP) CHILL WATER PUMP"},
    {"uid": "EEA-CHWP-3-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "CHWP-3", "equipment": "P16-PUMP (ALL HP) CHILL WATER PUMP"},
    {"uid": "EEA-SCHWP-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "SCHWP-1", "equipment": "P16-PUMP (ALL HP) CHILL WATER PUMP"},
    {"uid": "EEA-SCHWP-2-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "SCHWP-2", "equipment": "P16-PUMP (ALL HP) CHILL WATER PUMP"},
    {"uid": "EEA-SCHWP-3-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "SCHWP-3", "equipment": "P16-PUMP (ALL HP) CHILL WATER PUMP"},
    {"uid": "EEA-CH-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-1", "equipment": "Absorption Chiller"},
    {"uid": "EEA-CH-5-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-5", "equipment": "Absorption Chiller"},
    {"uid": "EEA-CH-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-2", "equipment": "Centrifugal Chiller"},
    {"uid": "EEA-CH-1STR-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-1STR", "equipment": "Chiller Starter"},
    {"uid": "EEA-CH-5STR-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-5STR", "equipment": "Chiller Starter"},
    {"uid": "EEA-CH-2VFD-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-2VFD", "equipment": "Chiller VFD"},
    {"uid": "EEA-CWP-1BP-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-1BP", "equipment": "End Suction Pump"},
    {"uid": "EEA-CWP-2BP-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-2BP", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-13-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-13", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-14-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-14", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-15-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-15", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-3A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-3A", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-3B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-3B", "equipment": "End Suction Pump"},
    {"uid": "EEA-CWP-1A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-1A", "equipment": "End Suction Pump"},
    {"uid": "EEA-CWP-1B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-1B", "equipment": "End Suction Pump"},
    {"uid": "EEA-CWP-2A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-2A", "equipment": "End Suction Pump"},
    {"uid": "EEA-CWP-2B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-2B", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-45-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-45", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-CHP-46-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-46", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-TP-69-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TP-69", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-TP-70-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TP-70", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-CRU-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CRU-1", "equipment": "Condensate Return Unit"},
    {"uid": "EEA-CRU-4-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CRU-4", "equipment": "Condensate Return Unit"},
    {"uid": "EEA-DA-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "DA-1", "equipment": "Deaerator Tank"},
    {"uid": "EEA-B-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "B-1", "equipment": "Steam Boiler"},
    {"uid": "EEA-B-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "B-2", "equipment": "Steam Boiler"},
    {"uid": "EEA-SGT-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "SGT-1", "equipment": "Surge Tank"},
    {"uid": "EEA-CT-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-1", "equipment": "Cooling Tower"},
    {"uid": "EEA-CT-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-2", "equipment": "Cooling Tower"},
    {"uid": "EEA-CT-4-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-4", "equipment": "Cooling Tower"},
    {"uid": "EEA-CT-5-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-5", "equipment": "Cooling Tower"},
    {"uid": "EEA-CTF-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-1", "equipment": "Cooling Tower Fill"},
    {"uid": "EEA-CTF-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-2", "equipment": "Cooling Tower Fill"},
    {"uid": "EEA-CTF-4-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-4", "equipment": "Cooling Tower Fill"},
    {"uid": "EEA-CTF-5-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-5", "equipment": "Cooling Tower Fill"},
    {"uid": "EEA-TWP-6A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-6A", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-6B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-6B", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-7A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-7A", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-7B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-7B", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-8A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-8A", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-8B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-8B", "equipment": "End Suction Pump"},
    {"uid": "EEA-CH-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1", "equipment": "Absorption Chiller"},
    {"uid": "EEA-ACC-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "ACC-1", "equipment": "Air Cooled Chiller"},
    {"uid": "EEA-CH-1STR-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1STR", "equipment": "Chiller Starter"},
    {"uid": "EEA-CH-1ASTR-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1ASTR", "equipment": "Chiller Starter"},
    {"uid": "EEA-ACC-1STR-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "ACC-1STR", "equipment": "Chiller VFD"},
    {"uid": "EEA-CHP-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CHP-1", "equipment": "Hori. Split Pump"},
    {"uid": "EEA-CHP-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CHP-2", "equipment": "Hori. Split Pump"},
    {"uid": "EEA-FWP-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FWP-1", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-FWP-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FWP-2", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-FWP-3-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FWP-3", "equipment": "Vert. In-Line Pump"},
    {"uid": "EEA-CS-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CS-2", "equipment": "Chemical Station"},
    {"uid": "EEA-CRU-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CRU-1", "equipment": "Condensate Return Unit"},
    {"uid": "EEA-CRU-21-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CRU-21", "equipment": "Condensate Return Unit"},
    {"uid": "EEA-DA-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "DA-1", "equipment": "Deaerator Tank"},
    {"uid": "EEA-FT-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FT-1", "equipment": "Flash Tank"},
    {"uid": "EEA-FT-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FT-2", "equipment": "Flash Tank"},
    {"uid": "EEA-B-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "B-1", "equipment": "Steam Boiler"},
    {"uid": "EEA-B-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "B-2", "equipment": "Steam Boiler"},
    {"uid": "EEA-CT-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CT-1", "equipment": "Cooling Tower"},
    {"uid": "EEA-CT-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CT-2", "equipment": "Cooling Tower"},
    {"uid": "EEA-CTF-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CTF-1", "equipment": "Cooling Tower Fill"},
    {"uid": "EEA-CTF-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CTF-2", "equipment": "Cooling Tower Fill"},
    {"uid": "EEA-TWP-3-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "TWP-3", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-4-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "TWP-4", "equipment": "End Suction Pump"},
    {"uid": "EEA-TWP-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "TWP-1", "equipment": "Hori. Split Pump"},
    {"uid": "EEA-CH-01-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-01", "equipment": "Centrifugal Chiller"},
    {"uid": "EEA-CH-02-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-02", "equipment": "Centrifugal Chiller"},
    {"uid": "EEA-CH-03-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-03", "equipment": "Centrifugal Chiller"},
    {"uid": "EEA-CS-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CS-2", "equipment": "Chemical Station"},
    {"uid": "EEA-CH-01VFD-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-01VFD", "equipment": "Chiller VFD"},
    {"uid": "EEA-CH-02VFD-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-02VFD", "equipment": "Chiller VFD"},
    {"uid": "EEA-CH-03VFD-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-03VFD", "equipment": "Chiller VFD"},
    {"uid": "EEA-CHP-22-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CHP-22", "equipment": "End Suction Pump"},
    {"uid": "EEA-CHP-24-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CHP-24", "equipment": "End Suction Pump"},
]



def assets_for_facility(facility_key: str | None) -> list[dict[str, str]]:
    """All assets at a facility, ordered by their tag."""
    if not facility_key:
        return []
    rows = [a for a in ASSETS if a["facility_key"] == facility_key]
    return sorted(rows, key=lambda a: a["asset"])


def asset_uids_for_facility(facility_key: str | None) -> list[str]:
    """Just the ENFRA Unique Identifiers at a facility (for a dropdown)."""
    return [a["uid"] for a in assets_for_facility(facility_key)]


def guess_asset_id(text: str | None, facility_key: str | None) -> str | None:
    """Best-guess the ENFRA Unique Identifier a quote refers to.

    Scans the quote text for each of the facility's asset tags (e.g. "CH-1",
    "ACC-2STR") as a standalone token and returns the UID of the longest tag
    that matches -- longer tags are more specific, so "CH-01VFD" wins over
    "CH-01".  Returns None when nothing matches; the caller lets the user
    correct it via the dropdown.
    """
    if not text or not facility_key:
        return None
    upper = text.upper()
    candidates = assets_for_facility(facility_key)
    # Direct UID hit first (rare but unambiguous)
    for a in candidates:
        if a["uid"].upper() in upper:
            return a["uid"]
    best_uid = None
    best_len = 0
    for a in candidates:
        tag = a["asset"].upper()
        # Standalone token: not glued to other letters/digits/hyphens
        if re.search(r"(?<![A-Z0-9-])" + re.escape(tag) + r"(?![A-Z0-9-])", upper):
            if len(tag) > best_len:
                best_len = len(tag)
                best_uid = a["uid"]
    return best_uid
