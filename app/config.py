"""
Configuration module for MSAPO Generator.
Loads settings from environment variables and .env file.
"""

import os
from pathlib import Path
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

# ── Email (SendGrid / SMTP) ───────────────────────────────────────────
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "msapo@yourdomain.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "")

# ── PDF Conversion Backend ────────────────────────────────────────────
# Options: "libreoffice", "gotenberg", "docx2pdf"
PDF_BACKEND = os.getenv("PDF_BACKEND", "libreoffice")
GOTENBERG_URL = os.getenv("GOTENBERG_URL", "http://localhost:3000")

# ── Webhook Auth ──────────────────────────────────────────────────────
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

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
    "st_marys": "St. Mary's",
    "canton_potsdam": "Canton Potsdam",
    "massena": "Massena",
    "gouverneur": "Gouverneur",
}


def facility_key_from_name(display_name: str) -> str | None:
    """Reverse-lookup: given a display name like 'United Memorial Medical Center',
    return the config key like 'united_memorial'.  Returns None if no match."""
    if not display_name:
        return None
    lower = display_name.lower()
    # Pass 1: exact full-name match (avoids substring false positives)
    for key, fac in FACILITIES.items():
        if fac["name"].lower() == lower:
            return key
    # Pass 2: alias substring match
    for key, fac in FACILITIES.items():
        aliases = [a.lower() for a in fac.get("aliases", [])]
        if any(a in lower for a in aliases):
            return key
    return None


def lookup_cost_code(facility_key: str | None, work_category: str | None) -> str | None:
    """Build a cost code like '01CEABA' from facility key + work category.
    Returns None if either piece is missing or invalid."""
    if not facility_key or not work_category:
        return None
    letter = SITE_COST_CODE_LETTERS.get(facility_key)
    suffix = WORK_CATEGORY_SUFFIXES.get(work_category)
    if not letter or not suffix:
        return None
    # repair_cap is only valid for Newark Wayne
    if work_category == "repair_cap" and facility_key != "newark_wayne":
        return None
    return f"01{letter}{suffix}"


def valid_categories_for_site(facility_key: str | None) -> list[str]:
    """Return the list of work-category keys valid for a given site."""
    if not facility_key or facility_key not in SITE_COST_CODE_LETTERS:
        return list(WORK_CATEGORY_SUFFIXES.keys())
    cats = [k for k in WORK_CATEGORY_SUFFIXES if k != "repair_cap"]
    if facility_key == "newark_wayne":
        cats.append("repair_cap")
    return cats
