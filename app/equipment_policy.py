"""The approved Group A equipment policy for no-labor PO routing.

The August 2026 process no longer decides Equipment versus Materials from the
delivery method.  If a vendor is not providing onsite labor or an onsite
rental, a purchase is Equipment only when the item is in the approved Group A
list supplied by Asset Management.  Everything else is Materials.

The full list is kept here so the AI prompt, deterministic fallback, tests,
and future integrations share one source of truth.  Keyword matching is only a
fallback when the analyzer did not return a usable route; it intentionally
avoids treating ordinary replacement parts as a complete equipment purchase.
"""

from __future__ import annotations

import re


GROUP_A_EQUIPMENT: dict[str, tuple[str, ...]] = {
    "Mechanical Equipment": (
        "Air Handling Units (AHUs)/Rooftop Units (RTUs)",
        "Chillers",
        "Boilers",
        "Cooling Towers",
        "Heat Exchangers",
        "Pumps (chilled water, condenser water, heating water)",
        "VFDs for major equipment",
        "Terminal Units",
    ),
    "Electrical Equipment": (
        "Generators",
        "Solar Panels",
        "Switchgear / Distribution Panels",
        "Transformers",
        "Uninterruptible Power Supply (UPS) Systems",
        "Automatic Transfer Switches (ATS)",
        "Motor Control Centers (MCCs)",
        "Power Monitoring or Load Shedding Equipment",
    ),
    "Building Automation / Controls": (
        "Building Management Systems (BMS) Central Servers and Control Panels",
        "Control Valve Assemblies (linked to major mechanical systems)",
        "Networked Sensors for performance monitoring",
    ),
    "EaaS-Specific and Energy Infrastructure Equipment": (
        "Battery Energy Storage Systems (BESS)",
        "Linear Generators",
        "Microgrid Control Systems",
        "Combined Heat and Power (CHP) Units",
        "Thermal Energy Storage Tanks",
        "Central Plant Optimization Controllers",
        "Inverter Systems (for solar/battery integration)",
        "Packaged Energy Systems / Modular Energy Plants",
    ),
    "Other Large or Custom Equipment": (
        "Custom Packaged Mechanical Skids (e.g., pre-piped pump or boiler skids)",
        "Pre-fabricated Pumping or Heating Stations",
        "Equipment requiring factory start-up or commissioning support",
        "Equipment subject to long-lead procurement timelines",
        "Owner-furnished, contractor-installed equipment",
    ),
}


GROUP_A_PROMPT_LIST = "\n".join(
    f"- {item}"
    for items in GROUP_A_EQUIPMENT.values()
    for item in items
)


_PARTS_ONLY_RE = re.compile(
    r"\b(?:parts?|repair kits?|gaskets?|belts?|filters?|bearings?|seals?|"
    r"consumables?|chemicals?|salt|lubricants?|refrigerant)\b",
    re.IGNORECASE,
)

_EXPLICIT_WHOLE_UNIT_RE = re.compile(
    r"\b(?:new|complete|packaged|modular|purchase|buy|furnish|supply|provide)\b"
    r".{0,60}\b(?:air handling unit|ahu|"
    r"rooftop unit|rtu|chiller|boiler|cooling tower|heat exchanger|pump|vfd|"
    r"generator|solar panel|switchgear|transformer|ups|automatic transfer "
    r"switch|motor control center|bms|battery energy storage|microgrid|chp|"
    r"thermal energy storage|inverter|skid|station)s?\b",
    re.IGNORECASE,
)

_PART_AFTER_UNIT_RE = re.compile(
    r"^\W+(?:(?:replacement|spare)\W+)?"
    r"(?:parts?|gaskets?|belts?|filters?|bearings?|seals?|kits?)\b",
    re.IGNORECASE,
)


def _has_explicit_whole_unit(source: str) -> bool:
    """Distinguish a complete unit from a part named after that unit.

    Evaluate each explicit purchase phrase independently.  A quote containing
    both chiller parts and one new boiler must still recognize the boiler; a
    global "any part phrase" check incorrectly downgraded that mixed quote.
    """
    for match in _EXPLICIT_WHOLE_UNIT_RE.finditer(source):
        tail = source[match.end() : match.end() + 40]
        if not _PART_AFTER_UNIT_RE.search(tail):
            return True
    return False

_GROUP_A_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Air Handling Unit / Rooftop Unit", re.compile(r"\b(?:air handling unit|ahu|rooftop unit|rtu)s?\b", re.I)),
    ("Chiller", re.compile(r"\bchillers?\b", re.I)),
    ("Boiler", re.compile(r"\bboilers?\b", re.I)),
    ("Cooling Tower", re.compile(r"\bcooling towers?\b", re.I)),
    ("Heat Exchanger", re.compile(r"\bheat exchangers?\b", re.I)),
    ("Pump", re.compile(r"\b(?:chilled water|condenser water|heating water)?\s*pumps?\b", re.I)),
    ("VFD", re.compile(r"\b(?:vfd|variable frequency drive)s?\b", re.I)),
    ("Terminal Unit", re.compile(r"\bterminal units?\b", re.I)),
    ("Generator", re.compile(r"\b(?:linear )?generators?\b", re.I)),
    ("Solar Panel", re.compile(r"\bsolar (?:panels?|modules?)\b", re.I)),
    ("Switchgear / Distribution Panel", re.compile(r"\b(?:switchgear|distribution panels?|switchboards?)\b", re.I)),
    ("Transformer", re.compile(r"\btransformers?\b", re.I)),
    ("UPS", re.compile(r"\b(?:uninterruptible power suppl(?:y|ies)|ups systems?)\b", re.I)),
    ("Automatic Transfer Switch", re.compile(r"\b(?:automatic transfer switches?|ats)\b", re.I)),
    ("Motor Control Center", re.compile(r"\b(?:motor control centers?|mccs?)\b", re.I)),
    ("Power Monitoring / Load Shedding", re.compile(r"\b(?:power monitoring|load shedding) (?:equipment|systems?)\b", re.I)),
    ("Building Management System", re.compile(r"\b(?:building management systems?|bms)\b", re.I)),
    ("Control Valve Assembly", re.compile(r"\bcontrol valve assembl(?:y|ies)\b", re.I)),
    ("Networked Sensor", re.compile(r"\bnetworked sensors?\b", re.I)),
    ("Battery Energy Storage System", re.compile(r"\b(?:battery energy storage systems?|bess)\b", re.I)),
    ("Microgrid Control System", re.compile(r"\bmicrogrid control systems?\b", re.I)),
    ("Combined Heat and Power Unit", re.compile(r"\b(?:combined heat and power|chp) units?\b", re.I)),
    ("Thermal Energy Storage Tank", re.compile(r"\bthermal energy storage tanks?\b", re.I)),
    ("Central Plant Optimization Controller", re.compile(r"\bcentral plant optimization controllers?\b", re.I)),
    ("Inverter System", re.compile(r"\b(?:solar |battery )?inverter systems?\b", re.I)),
    ("Packaged / Modular Energy System", re.compile(r"\b(?:packaged energy systems?|modular energy plants?)\b", re.I)),
    ("Custom Mechanical Skid", re.compile(r"\b(?:custom packaged mechanical|pre-piped (?:pump|boiler)) skids?\b", re.I)),
    ("Pre-fabricated Station", re.compile(r"\bpre-?fabricated (?:pumping|heating) stations?\b", re.I)),
    ("Factory Startup / Commissioning Equipment", re.compile(r"\bequipment\b.{0,60}\b(?:factory start-?up|commissioning support)\b", re.I)),
    ("Long-lead Equipment", re.compile(r"\blong-?lead (?:procurement )?equipment\b", re.I)),
    ("Owner-furnished Equipment", re.compile(r"\bowner-?furnished,? contractor-?installed equipment\b", re.I)),
)


def group_a_equipment_match(text: object) -> str | None:
    """Return the matched Group A category, or ``None`` for Materials.

    A quote for loose parts remains Materials even if those parts happen to be
    used on a chiller or boiler.  A complete replacement unit still qualifies.
    The analyzer's explicit route guess takes precedence over this fallback.
    """
    source = " ".join(str(text or "").split())
    if not source:
        return None
    explicit_whole_unit = _has_explicit_whole_unit(source)
    if _PARTS_ONLY_RE.search(source) and not explicit_whole_unit:
        return None
    for label, pattern in _GROUP_A_PATTERNS:
        if pattern.search(source):
            return label
    return None
