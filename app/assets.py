"""
ENFRA asset registry (Appendix B), transcribed from the asset-management export.

246 assets across 7 sites. Each row keeps the ENFRA Unique Identifier plus
a human-readable asset tag, equipment type, and what it serves, so the UI can show
a friendly name next to the ID and take a best guess at the asset a quote names.
Sites not listed here (Massena, Gouverneur, Unity Specialty) have no assets on file.
"""

from __future__ import annotations

import re

# Asset-list site codes -> facility keys used in config.FACILITIES
ASSET_SITE_TO_FACILITY: dict[str, str] = {
    "CPH": "canton_potsdam",
    "CSHC": "clifton_springs",
    "NWCH": "newark_wayne",
    "RGH": "rochester_general",
    "SMMC": "st_marys",
    "UMMC": "united_memorial",
    "UNITY": "unity",
}

# uid, site_code, facility_key, asset tag, equipment type, serves
ASSETS: list[dict[str, str]] = [
    {"uid": "EEA-ACC-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-1", "equipment": "AC Recip Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-2-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-2", "equipment": "AC Recip Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-3-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-3", "equipment": "AC Recip Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-4-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-4", "equipment": "AC Recip Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-AS-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "AS-1", "equipment": "Air Separator", "serves": "Cool Air"},
    {"uid": "EEA-ACC-1STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-1STR", "equipment": "BAS VFD Integration Control", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-2STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-2STR", "equipment": "BAS VFD Integration Control", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-3STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-3STR", "equipment": "BAS VFD Integration Control", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-4STR-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "ACC-4STR", "equipment": "BAS VFD Integration Control", "serves": "Chilled Water"},
    {"uid": "EEA-CHWP-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "CHWP-1", "equipment": "Chilled Water Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHWP-2-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "CHWP-2", "equipment": "Chilled Water Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHWP-3-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "CHWP-3", "equipment": "Chilled Water Pump", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-1-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "SCHWP-1", "equipment": "Chilled Water Pump", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-2-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "SCHWP-2", "equipment": "Chilled Water Pump", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-3-CPH", "site_code": "CPH", "facility_key": "canton_potsdam", "asset": "SCHWP-3", "equipment": "Chilled Water Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-1", "equipment": "Absorption Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-5-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-5", "equipment": "Absorption Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-2", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1STR-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-1STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-CH-5STR-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-5STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2VFD-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CH-2VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-1BP-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-1BP", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-2BP-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-2BP", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-13-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-13", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-14-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-14", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-15-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-15", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-3A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-3A", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-3B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-3B", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-1A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-1A", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-1B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-1B", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-2A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-2A", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-2B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CWP-2B", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-45-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-45", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-46-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CHP-46", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-TP-69-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TP-69", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-TP-70-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TP-70", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-CRU-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CRU-1", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-4-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CRU-4", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-DA-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "DA-1", "equipment": "Deaerator Tank", "serves": "Steam"},
    {"uid": "EEA-B-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "B-1", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "B-2", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-SGT-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "SGT-1", "equipment": "Surge Tank", "serves": "Steam"},
    {"uid": "EEA-CT-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-1", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-2", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-4-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-4", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-5-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CT-5", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CTF-1-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-1", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-2", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-4-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-4", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-5-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CTF-5", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-TWP-6A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-6A", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-6B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-6B", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-7A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-7A", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-7B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-7B", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-8A-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-8A", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-8B-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "TWP-8B", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-FWP-71-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "FWP-71", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-72-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "FWP-72", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-73-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "FWP-73", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-CRU-2-CSHC", "site_code": "CSHC", "facility_key": "clifton_springs", "asset": "CRU-2", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CH-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1", "equipment": "Absorption Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1A-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1A", "equipment": "Absorption Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "ACC-1", "equipment": "Air Cooled Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1STR-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1ASTR-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CH-1ASTR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-ACC-1STR-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "ACC-1STR", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CHP-1", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CHP-2", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-FWP-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FWP-1", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FWP-2", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-3-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FWP-3", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-CS-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CS-2", "equipment": "Chemical Station", "serves": "Steam"},
    {"uid": "EEA-CRU-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CRU-1", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-21-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CRU-21", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-DA-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "DA-1", "equipment": "Deaerator Tank", "serves": "Steam"},
    {"uid": "EEA-FT-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FT-1", "equipment": "Flash Tank", "serves": "Steam"},
    {"uid": "EEA-FT-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "FT-2", "equipment": "Flash Tank", "serves": "Steam"},
    {"uid": "EEA-B-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "B-1", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "B-2", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-CT-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CT-1", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CT-2", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CTF-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CTF-1", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-2-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "CTF-2", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-TWP-3-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "TWP-3", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-4-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "TWP-4", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-1-NWCH", "site_code": "NWCH", "facility_key": "newark_wayne", "asset": "TWP-1", "equipment": "Hori. Split Pump", "serves": "Tower Water"},
    {"uid": "EEA-CH-01-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-01", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-02-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-02", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-03-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-03", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CS-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CS-2", "equipment": "Chemical Station", "serves": "Chilled Water"},
    {"uid": "EEA-CH-01VFD-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-01VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CH-02VFD-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-02VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CH-03VFD-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CH-03VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-22-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CHP-22", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-24-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CHP-24", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-ET-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "ET-1", "equipment": "Expansion Tank", "serves": "Chilled Water"},
    {"uid": "EEA-ET-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "ET-2", "equipment": "Expansion Tank", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-07-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-07", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-08-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-08", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-01-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-01", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-02-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-02", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-03-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-03", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-04-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-04", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-05-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-05", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CWP-06-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CWP-06", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-PFHX-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "PFHX-1", "equipment": "Plate and Frame Heat Exchanger", "serves": "Chilled Water"},
    {"uid": "EEA-RMS-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "RMS-1", "equipment": "Refrigerant Monitoring System", "serves": "Chilled Water"},
    {"uid": "EEA-TP-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "TP-1", "equipment": "End Suction Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-TP-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "TP-2", "equipment": "End Suction Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "FWP-1", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "FWP-2", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-3-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "FWP-3", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-4-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "FWP-4", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-BS-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "BS-1", "equipment": "Blowdown Separator", "serves": "Steam"},
    {"uid": "EEA-CRU-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CRU-1", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CRU-2", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-DA-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "DA-1", "equipment": "Deaerator Tank", "serves": "Steam"},
    {"uid": "EEA-PRS-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "PRS-1", "equipment": "Pressure Reducing Station", "serves": "Steam"},
    {"uid": "EEA-B-01-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "B-01", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-02-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "B-02", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-03-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "B-03", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-04-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "B-04", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-SGT-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "SGT-1", "equipment": "Surge Tank", "serves": "Steam"},
    {"uid": "EEA-CS-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CS-1", "equipment": "Water Softener", "serves": "Steam"},
    {"uid": "EEA-CT-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CT-1", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CT-2", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-3-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CT-3", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CTF-1-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CTF-1", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-2-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CTF-2", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-3-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CTF-3", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CP-01-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CP-01", "equipment": "Hori. Split Pump", "serves": "Tower Water"},
    {"uid": "EEA-CP-02-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CP-02", "equipment": "Hori. Split Pump", "serves": "Tower Water"},
    {"uid": "EEA-CP-03-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CP-03", "equipment": "Hori. Split Pump", "serves": "Tower Water"},
    {"uid": "EEA-CRU-1A-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CRU-1A", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CS-1A-RGH", "site_code": "RGH", "facility_key": "rochester_general", "asset": "CS-1A", "equipment": "Chemical Station", "serves": "Tower Water"},
    {"uid": "EEA-AS-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "AS-1", "equipment": "Air Separator", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CH-1", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CH-2", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1VFD-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CH-1VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2VFD-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CH-2VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CHWP-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CHWP-1", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHWP-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CHWP-2", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-FWP-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "FWP-1", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "FWP-2", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-3-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "FWP-3", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-TP-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "TP-1", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-TP-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "TP-2", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-CS-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CS-1", "equipment": "Chemical Station", "serves": "Steam"},
    {"uid": "EEA-DA-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "DA-1", "equipment": "Deaerator Tank", "serves": "Steam"},
    {"uid": "EEA-PRS-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "PRS-1", "equipment": "Pressure Reducing Station", "serves": "Steam"},
    {"uid": "EEA-B-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "B-1", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "B-2", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-3-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "B-3", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-SGT-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "SGT-1", "equipment": "Surge Tank", "serves": "Steam"},
    {"uid": "EEA-CT-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CT-1", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CT-2", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CTF-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CTF-1", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CTF-2", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-SP-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "SP-1", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-SP-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "SP-2", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "TWP-1", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-2-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "TWP-2", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-WS-1-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "WS-1", "equipment": "Water Softener", "serves": "Tower Water"},
    {"uid": "EEA-CS-1A-SMMC", "site_code": "SMMC", "facility_key": "st_marys", "asset": "CS-1A", "equipment": "Chemical Station", "serves": "Tower Water"},
    {"uid": "EEA-AS-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "AS-1", "equipment": "Air Separator", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CH-2", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-3-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CH-3", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CS-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CS-1", "equipment": "Chemical Station", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2VFD-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CH-2VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CH-3VFD-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CH-3VFD", "equipment": "Chiller VFD", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-4-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CHP-4", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-5-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CHP-5", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-CHP-6-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CHP-6", "equipment": "End Suction Pump", "serves": "Chilled Water"},
    {"uid": "EEA-FWP-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "FWP-1", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-2-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "FWP-2", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-3-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "FWP-3", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-BS-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "BS-1", "equipment": "Blowdown Separator", "serves": "Steam"},
    {"uid": "EEA-DA-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "DA-1", "equipment": "Deaerator Tank", "serves": "Steam"},
    {"uid": "EEA-B-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "B-1", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-2-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "B-2", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-3676-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "B-3676", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-WS-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "WS-1", "equipment": "Water Softener", "serves": "Steam"},
    {"uid": "EEA-CT-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CT-1", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-2-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CT-2", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CTF-1-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CTF-1", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-2-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CTF-2", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CWP-10-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CWP-10", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-CWP-11-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CWP-11", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-CWP-12-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CWP-12", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-CWP-7-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CWP-7", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-CWP-8-UMMC", "site_code": "UMMC", "facility_key": "united_memorial", "asset": "CWP-8", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-AS-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "AS-1", "equipment": "Air Separator", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-1", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-2", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-3-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-3", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-4", "equipment": "Centrifugal Chiller", "serves": "Chilled Water"},
    {"uid": "EEA-CH-1STR-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-1STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-CH-2STR-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-2STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-CH-3STR-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-3STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-CH-4STR-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CH-4STR", "equipment": "Chiller Starter", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "SCHWP-1", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "SCHWP-2", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "SCHWP-4", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
    {"uid": "EEA-RMS-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "RMS-1", "equipment": "Refrigerant Monitoring System", "serves": "Chilled Water"},
    {"uid": "EEA-P-31-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "P-31", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-P-32-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "P-32", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-PCHWP-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "PCHWP-1", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-PCHWP-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "PCHWP-2", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-PCHWP-3-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "PCHWP-3", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-PCHWP-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "PCHWP-4", "equipment": "Vert. In-Line Pump", "serves": "Chilled Water"},
    {"uid": "EEA-TP-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "TP-1", "equipment": "End Suction Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-TP-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "TP-2", "equipment": "End Suction Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "FWP-1", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "FWP-2", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-3-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "FWP-3", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-FWP-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "FWP-4", "equipment": "Vert. In-Line Pump", "serves": "Feedwater (Steam)"},
    {"uid": "EEA-CRU-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CRU-2", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-DA-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "DA-1", "equipment": "Deaerator Tank", "serves": "Steam"},
    {"uid": "EEA-FT-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "FT-1", "equipment": "Flash Tank", "serves": "Steam"},
    {"uid": "EEA-PRS-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "PRS-1", "equipment": "Pressure Reducing Station", "serves": "Steam"},
    {"uid": "EEA-B-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "B-2", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-5-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "B-5", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-B-6-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "B-6", "equipment": "Steam Boiler", "serves": "Steam"},
    {"uid": "EEA-SGT-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "SGT-1", "equipment": "Surge Tank", "serves": "Steam"},
    {"uid": "EEA-WS-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "WS-1", "equipment": "Water Softener", "serves": "Steam"},
    {"uid": "EEA-WS-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "WS-2", "equipment": "Water Softener", "serves": "Steam"},
    {"uid": "EEA-CS-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CS-1", "equipment": "Chemical Station", "serves": "Tower Water"},
    {"uid": "EEA-CT-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CT-1", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CT-2", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-3-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CT-3", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CT-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CT-4", "equipment": "Cooling Tower", "serves": "Tower Water"},
    {"uid": "EEA-CTF-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CTF-1", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CTF-2", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-3-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CTF-3", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-CTF-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CTF-4", "equipment": "Cooling Tower Fill", "serves": "Tower Water"},
    {"uid": "EEA-TWP-1-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "TWP-1", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-2-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "TWP-2", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-3-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "TWP-3", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-TWP-4-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "TWP-4", "equipment": "End Suction Pump", "serves": "Tower Water"},
    {"uid": "EEA-CRU-1A-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CRU-1A", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-1B-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CRU-1B", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-1C-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CRU-1C", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-1D-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CRU-1D", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-CRU-2A-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "CRU-2A", "equipment": "Condensate Return Unit", "serves": "Steam"},
    {"uid": "EEA-RMS-1A-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "RMS-1A", "equipment": "Refrigerant Monitoring System", "serves": "Chilled Water"},
    {"uid": "EEA-SCHWP-2A-UNITY", "site_code": "UNITY", "facility_key": "unity", "asset": "SCHWP-2A", "equipment": "Hori. Split Pump", "serves": "Chilled Water"},
]


def asset_label(a: dict[str, str]) -> str:
    """Human-readable name for an asset, e.g. 'CH-1 · Absorption Chiller (Chilled Water)'."""
    label = f"{a['asset']} · {a['equipment']}"
    if a.get("serves"):
        label += f" ({a['serves']})"
    return label


def assets_for_facility(facility_key: str | None) -> list[dict[str, str]]:
    """All assets at a facility, ordered by their tag as TEXT.

    KNOWN ORDERING DEFECT, reported not fixed: this is a string sort, so a
    double-digit unit sorts before a single-digit one. Real, and visible in the
    operator's dropdown today:

        UMMC        CWP-10, CWP-11, CWP-12, CWP-7, CWP-8
        Clifton     CHP-13, CHP-14, CHP-15, CHP-3A, CHP-3B, CHP-45

    Someone scanning for CWP-7 finds it below CWP-12. app.asset_guess._tag_sort_key
    already sorts on the trailing integer and is the helper to reuse if this is
    changed -- but the change is user-visible ordering, so it was left for the
    product owner rather than altered during a review.

    NOT a correctness problem for asset SELECTION. lowest_numbered_of_type
    re-sorts these rows with _tag_sort_key before choosing, precisely because it
    cannot rely on this order.
    """
    if not facility_key:
        return []
    rows = [a for a in ASSETS if a["facility_key"] == facility_key]
    return sorted(rows, key=lambda a: a["asset"])


def asset_uids_for_facility(facility_key: str | None) -> list[str]:
    """Just the ENFRA Unique Identifiers at a facility (for a dropdown)."""
    return [a["uid"] for a in assets_for_facility(facility_key)]


def asset_by_uid(uid: str | None) -> dict[str, str] | None:
    if not uid:
        return None
    for a in ASSETS:
        if a["uid"] == uid:
            return a
    return None


def _norm_tag(t: str | None) -> str:
    """Normalize an asset tag for comparison: upper-case, and drop leading
    zeros in numeric runs so 'CWP-7' == 'CWP-07' and 'CH-01' == 'CH-1'."""
    return re.sub(r"0*(\d+)", r"\1", (t or "").upper().strip())


def match_asset_hint(hint: str | None, candidates: list[dict[str, str]]) -> str | None:
    """Resolve an AI-extracted asset tag/UID to a real asset at the site.
    Returns None if the hint doesn't correspond to an actual asset — a wrong
    or hallucinated tag is ignored rather than mis-selected."""
    if not hint:
        return None
    hn = _norm_tag(hint)
    if not hn:
        return None
    for a in candidates:
        if _norm_tag(a["asset"]) == hn or hint.strip().upper() == a["uid"].upper():
            return a["uid"]
    return None


def guess_asset_id(text: str | None, facility_key: str | None,
                   hint: str | None = None) -> str | None:
    """Best-guess the ENFRA Unique Identifier a quote refers to.

    Order of confidence: (1) the AI-extracted asset tag ("hint") if it resolves
    to a real asset here, then (2) a standalone asset-tag/UID token found in the
    quote text (longest, most-specific tag wins). Returns None when nothing is
    confidently identified — the caller then defaults to "No asset applicable"
    rather than guessing.
    """
    if not facility_key:
        return None
    candidates = assets_for_facility(facility_key)
    hinted = match_asset_hint(hint, candidates)
    if hinted:
        return hinted
    if not text:
        return None
    upper = text.upper()
    # A bare substring test, unlike the word-bounded tag search below. It is safe
    # ONLY because no UID in this registry is a substring of another one -- UIDs
    # carry both a site suffix and a tag, so "EEA-CH-1-CSHC" cannot sit inside
    # "EEA-CH-1STR-CSHC". tests/test_asset_guess.py pins that property, because a
    # future export that breaks it would silently select the wrong asset here
    # rather than raise: the shorter UID would match inside the longer one and
    # win, since this loop returns on FIRST hit.
    #
    # First hit in tag order, not the longest match -- deliberately different
    # from the loop below. Two UIDs in one quote is not a case this can resolve,
    # and picking one arbitrarily is no worse than picking the longer string;
    # the operator reviews the asset either way.
    for a in candidates:
        if a["uid"].upper() in upper:
            return a["uid"]
    best_uid = None
    best_len = 0
    for a in candidates:
        tag = a["asset"].upper()
        if re.search(r"(?<![A-Z0-9-])" + re.escape(tag) + r"(?![A-Z0-9-])", upper):
            if len(tag) > best_len:
                best_len = len(tag)
                best_uid = a["uid"]
    return best_uid
