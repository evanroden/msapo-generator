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
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

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
