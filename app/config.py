"""
Configuration module for Purchase Order Process Control.
Loads settings from environment variables and .env file.
"""

import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "templates" / "Master_MSAPO_Template.docx"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Anthropic ──────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# When a new Sonnet version is released, update this default or set the
# ANTHROPIC_MODEL environment variable (e.g. in .env or Render dashboard).
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# The zone the OPERATOR files in, not the container's.
#
# Nothing sets TZ in the Dockerfile, render.yaml or docker-compose.yml, so the
# container runs UTC -- which is 4-5 hours ahead of every US contract this tool
# serves. date.today() therefore rolled over at 8pm Eastern, and an employee
# filing in the evening got TOMORROW'S DATE defaulted onto the expense form the
# approver signs. Mileage travel dates inherit it through the track-the-default
# protocol, so one wrong default propagated down the whole report.
#
# America/New_York is the default because it is ENFRA's and RRH's zone -- the
# highest-volume account -- and because no US zone is worse served by it than by
# UTC. Central-time accounts are still an hour off between 11pm and midnight
# local; set EPC_TIMEZONE per deployment if that matters. Any IANA name works.
#
# Deliberately NOT browser-detected. The browser's zone is available (the
# device-identity iframe could carry it) but it is attacker-controlled input
# deciding a date on a financial document, and a laptop with a wrong clock would
# silently misdate a report. A deployment setting is auditable.
EPC_TIMEZONE = os.getenv("EPC_TIMEZONE", "America/New_York").strip() or "America/New_York"


def operator_today() -> "date":
    """Today's date in the operator's configured zone.

    Use this instead of date.today() for any value an operator SEES or signs.
    date.today() reads the container clock, which is UTC in every deployment of
    this app.

    Falls back to the container's date if the zone name is unknown rather than
    raising: a typo in a dashboard variable must not take the expense workflow
    down, and a wrong-by-hours default is still recoverable by the operator,
    who can edit the field.
    """
    try:
        return datetime.now(ZoneInfo(EPC_TIMEZONE)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return date.today()


# Contract administrators are deployment data, not source-code constants.
RRH_APPROVER_NAME = os.getenv("RRH_APPROVER_NAME", "").strip()
RRH_APPROVER_EMAIL = os.getenv("RRH_APPROVER_EMAIL", "").strip()

# ── PDF Conversion Backend ────────────────────────────────────────────
# Options: "libreoffice", "gotenberg", "docx2pdf"
PDF_BACKEND = os.getenv("PDF_BACKEND", "libreoffice")
GOTENBERG_URL = os.getenv("GOTENBERG_URL", "http://localhost:3000")

# ── Hardcoded Facilities (RRH Network) ────────────────────────────────
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

# ── Cost Code Mappings ─────────────────────────────────────────────
# Format: "01" + site letter + work suffix  →  e.g. "01CEABA"

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

# Appendix A has not supplied a cost-code letter for these configured sites.
# They remain selectable, but the operator must enter a code and generation is
# blocked while it is blank. Do not invent or infer a letter here.
MANUAL_COST_CODE_SITES: frozenset[str] = frozenset({"unity_specialty"})

WORK_CATEGORY_SUFFIXES: dict[str, str] = {
    "chemical_treatment": "CHEM",
    "building_automation": "EABA",
    "electrical_pm": "EAEPM",
    "preventive_maintenance": "EAPM",
    "repairs": "EAR",
    "repair_cap": "EARC",       # Newark Wayne only
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

# Which work categories actually have a cost-code line at each site (Appendix A).
# Water softener exists only where budgeted; repair_cap only at Newark Wayne;
# Massena & Gouverneur carry steam-trap work only.
_FULL = [
    "chemical_treatment", "building_automation", "electrical_pm",
    "preventive_maintenance", "repairs", "steam_trap", "water_softener",
]
_NO_SOFTENER = [c for c in _FULL if c != "water_softener"]
SITE_VALID_CATEGORIES: dict[str, list[str]] = {
    "rochester_general": _FULL,
    "united_memorial": _FULL,
    "unity": _FULL,
    # The facility is real and selectable, but no automatic cost-code letter is
    # configured. The UI therefore requires a manual cost code for this site.
    "unity_specialty": _NO_SOFTENER,
    "st_marys": _FULL,
    "newark_wayne": [
        "chemical_treatment", "building_automation", "electrical_pm",
        "preventive_maintenance", "repairs", "repair_cap", "steam_trap",
    ],
    "clifton_springs": _NO_SOFTENER,
    "canton_potsdam": _NO_SOFTENER,
    "massena": ["steam_trap"],
    "gouverneur": ["steam_trap"],
}


def alias_matches(alias: str, haystack: str) -> bool:
    """Whether ``alias`` occurs in ``haystack`` as WHOLE WORDS.

    A bare substring test is not safe here, and the failure is not hypothetical:
    the alias "unity hospital" is a substring of "Community Hospital", so
    Newark-Wayne Community Hospital matched Unity Hospital and was silently
    rewritten to Unity's name and address -- which then produced Unity's
    cost-code letter (01F... instead of 01D...) and dropped repair_cap, a
    category that exists ONLY at Newark-Wayne.

    Lookarounds rather than ``\\b`` because several aliases carry punctuation
    ("st. mary", "canton-potsdam", "127 north"); ``\\b`` after a "." asserts the
    wrong thing, while ``(?!\\w)`` means "not followed by another word character"
    for every alias shape.
    """
    if not alias or not haystack:
        return False
    return re.search(
        rf"(?<!\w){re.escape(alias.lower())}(?!\w)", haystack.lower()
    ) is not None


def facility_key_from_name(display_name: str) -> str | None:
    """Reverse-lookup: given a display name like 'United Memorial Medical Center',
    return the config key like 'united_memorial'. Returns None if no match.

    Two passes, and the order matters. The exact-name pass must run over ALL
    facilities before any alias is tried, because two sites share a name stem
    ("Unity Hospital" / "Unity Specialty Hospital") and dict order would
    otherwise decide which one wins.
    """
    if not display_name:
        return None
    lower = display_name.lower()
    # Pass 1: exact full-name match (avoids substring false positives)
    for key, fac in FACILITIES.items():
        if fac["name"].lower() == lower:
            return key
    # Pass 2: whole-word alias match. NOT a substring test -- see alias_matches.
    for key, fac in FACILITIES.items():
        if any(alias_matches(a, lower) for a in fac.get("aliases", [])):
            return key
    return None


def lookup_cost_code(facility_key: str | None, work_category: str | None) -> str | None:
    """Build a code such as '01CEABA' from facility + work category.
    Returns None if either piece is missing, invalid, or deliberately unmapped."""
    if not facility_key or not work_category:
        return None
    letter = SITE_COST_CODE_LETTERS.get(facility_key)
    suffix = WORK_CATEGORY_SUFFIXES.get(work_category)
    if not letter or not suffix:
        return None
    # Only build a code for categories that actually exist at this site
    if work_category not in SITE_VALID_CATEGORIES.get(facility_key, []):
        return None
    return f"01{letter}{suffix}"


def valid_categories_for_site(facility_key: str | None) -> list[str]:
    """Return the work-category keys valid for a facility (Appendix A)."""
    if not facility_key:
        return list(WORK_CATEGORY_SUFFIXES.keys())
    return SITE_VALID_CATEGORIES.get(facility_key, _NO_SOFTENER)
