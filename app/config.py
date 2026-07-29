"""Business configuration plus host-neutral runtime compatibility constants."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.runtime import get_runtime_settings

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_RUNTIME = get_runtime_settings()
BASE_DIR = _RUNTIME.project_root
TEMPLATE_PATH = _RUNTIME.template_path
OUTPUT_DIR = _RUNTIME.output_dir

# Backward-compatible provider variables. New deployments should prefer the
# provider-neutral EPC_AI_* and EPC_PDF_CONVERTER names.
ANTHROPIC_API_KEY = os.getenv("EPC_AI_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
ANTHROPIC_MODEL = os.getenv(
    "EPC_AI_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
)
PDF_BACKEND = os.getenv("EPC_PDF_CONVERTER", os.getenv("PDF_BACKEND", "libreoffice"))
GOTENBERG_URL = os.getenv("GOTENBERG_URL", "http://localhost:3000")

FACILITIES = {
    "rochester_general": {
        "name": "Rochester General Hospital",
        "address": "1425 Portland Ave, Rochester, NY 14621",
        "aliases": ["rochester general", "rgh", "portland ave", "14621"],
    },
    "unity": {
        "name": "Unity Hospital",
        "address": "1555 Long Pond Rd, Rochester, NY 14626",
        "aliases": ["unity hospital", "long pond", "14626"],
    },
    "unity_specialty": {
        "name": "Unity Specialty Hospital",
        "address": "89 Genesee St, Rochester, NY 14611",
        "aliases": ["unity specialty"],
    },
    "st_marys": {
        "name": "St. Mary's Medical Campus",
        "address": "89 Genesee St, Rochester, NY 14611",
        "aliases": ["st. mary", "st mary", "st. mary's", "st marys"],
    },
    "united_memorial": {
        "name": "United Memorial Medical Center",
        "address": "127 North St, Batavia, NY 14020",
        "aliases": ["united memorial", "ummc", "batavia", "14020", "127 north"],
    },
    "newark_wayne": {
        "name": "Newark-Wayne Community Hospital",
        "address": "1200 Driving Park Ave, Newark, NY 14513",
        "aliases": ["newark-wayne", "newark wayne", "driving park", "14513"],
    },
    "canton_potsdam": {
        "name": "Canton-Potsdam Hospital",
        "address": "50 Leroy St, Potsdam, NY 13676",
        "aliases": ["canton-potsdam", "canton potsdam", "potsdam", "leroy st", "13676"],
    },
    "gouverneur": {
        "name": "Gouverneur Hospital",
        "address": "77 W Barney St, Gouverneur, NY 13642",
        "aliases": ["gouverneur", "barney st", "13642"],
    },
    "massena": {
        "name": "Massena Hospital",
        "address": "1 Hospital Dr, Massena, NY 13662",
        "aliases": ["massena", "13662"],
    },
    "clifton_springs": {
        "name": "Clifton Springs Hospital & Clinic",
        "address": "2 Coulter Rd, Clifton Springs, NY 14432",
        "aliases": ["clifton springs", "coulter rd", "14432"],
    },
}

SITE_COST_CODE_LETTERS: dict[str, str] = {
    "rochester_general": "B",
    "united_memorial": "C",
    "newark_wayne": "D",
    "clifton_springs": "E",
    "unity": "F",
    "st_marys": "G",
    "canton_potsdam": "H",
    "massena": "I",
    "gouverneur": "J",
}

WORK_CATEGORY_SUFFIXES: dict[str, str] = {
    "chemical_treatment": "CHEM",
    "building_automation": "EABA",
    "electrical_pm": "EAEPM",
    "preventive_maintenance": "EAPM",
    "repairs": "EAR",
    "repair_cap": "EARC",
    "steam_trap": "STSRC",
    "water_softener": "WS",
}

WORK_CATEGORY_DISPLAY: dict[str, str] = {
    "chemical_treatment": "Chemical Treatment",
    "building_automation": "Building Automation",
    "electrical_pm": "Electrical PM",
    "preventive_maintenance": "Preventive Maintenance",
    "repairs": "Repairs",
    "repair_cap": "Repair Cap",
    "steam_trap": "Steam Trap Survey & Repair",
    "water_softener": "Water Softener",
}

FACILITY_SHORT_NAMES: dict[str, str] = {
    "rochester_general": "RGH",
    "united_memorial": "UMMC",
    "newark_wayne": "Newark Wayne",
    "clifton_springs": "Clifton Springs",
    "unity": "Unity",
    "unity_specialty": "Unity Specialty",
    "st_marys": "St. Mary's",
    "canton_potsdam": "Canton Potsdam",
    "massena": "Massena",
    "gouverneur": "Gouverneur",
}

_FULL = [
    "chemical_treatment",
    "building_automation",
    "electrical_pm",
    "preventive_maintenance",
    "repairs",
    "steam_trap",
    "water_softener",
]
_NO_SOFTENER = [category for category in _FULL if category != "water_softener"]
SITE_VALID_CATEGORIES: dict[str, list[str]] = {
    "rochester_general": _FULL,
    "united_memorial": _FULL,
    "unity": _FULL,
    "unity_specialty": _NO_SOFTENER,
    "st_marys": _FULL,
    "newark_wayne": [
        "chemical_treatment",
        "building_automation",
        "electrical_pm",
        "preventive_maintenance",
        "repairs",
        "repair_cap",
        "steam_trap",
    ],
    "clifton_springs": _NO_SOFTENER,
    "canton_potsdam": _NO_SOFTENER,
    "massena": ["steam_trap"],
    "gouverneur": ["steam_trap"],
}


def facility_key_from_name(display_name: str) -> str | None:
    if not display_name:
        return None
    lower = display_name.lower()
    for key, facility in FACILITIES.items():
        if facility["name"].lower() == lower:
            return key
    for key, facility in FACILITIES.items():
        aliases = [alias.lower() for alias in facility.get("aliases", [])]
        if any(alias in lower for alias in aliases):
            return key
    return None


def lookup_cost_code(facility_key: str | None, work_category: str | None) -> str | None:
    if not facility_key or not work_category:
        return None
    site_letter = SITE_COST_CODE_LETTERS.get(facility_key)
    suffix = WORK_CATEGORY_SUFFIXES.get(work_category)
    if not site_letter or not suffix:
        return None
    return f"01{site_letter}{suffix}"


def valid_categories_for_site(facility_key: str | None) -> list[str]:
    return list(SITE_VALID_CATEGORIES.get(facility_key or "", []))
