"""Provider-neutral vendor quote analysis."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from app.ai_provider import AIProvider, AIRequest, CAP_TEXT, get_ai_provider, require_capability
from app.analysis_schema import normalize_analysis_response
from app.config import FACILITIES


SYSTEM_PROMPT = """\
You are an expert construction and facilities project analyst supporting \
multiple facilities-management contracts. Your job is to read a vendor quote and extract structured \
data so that a Scope of Work (MSAPO agreement) can be generated.

STRICT RULES:

1. **NEVER include any dollar amounts, hourly rates, unit prices, line-item \
   costs, totals, or any financial figures in scope_of_work, inclusions, \
   exclusions, or project_description.** Strip every price from those fields. \
   HOWEVER, you MUST extract the pricing summary into "subtotal_amount", \
   "tax_amount", and "total_amount" — keep those dollar figures intact.

   PRICING SUMMARY RULES:
   - "total_amount": the final grand total the customer pays (after tax/fees).
   - "subtotal_amount": the pre-tax subtotal, but ONLY if the quote breaks \
     pricing into a separate subtotal line AND a separate tax line. If the \
     quote shows just one all-in amount (tax already baked in, no separate \
     subtotal + tax lines), set subtotal_amount to null.
   - "tax_amount": the sales-tax dollar figure, ONLY if it is stated as its \
     own line item. If there is no separate tax line, set tax_amount to null.
   Only populate subtotal_amount and tax_amount together when the quote genuinely \
   itemizes subtotal + tax. Otherwise leave both null and provide only total_amount.

2. If standard inclusions or exclusions are missing from the quote, infer \
   reasonable ones based on the work. Wrap every inferred item with \
   [AI ESTIMATE: <item>] so the user can review it. Never flag explicit quote text.

3. **TAX STATUS:** Search the entire quote for tax lines or wording. Use:
   - "included" for an explicit tax line or statement that tax is included;
   - "excluded" for excluded, extra, or plus-applicable-tax wording;
   - "unclear" only when there is no tax reference anywhere.
   Set tax_warning only when unclear. Preserve estimated-versus-actual tax notes.

4. Match the facility to a known RRH site when explicitly supported:
   - Rochester General Hospital, 1425 Portland Ave, Rochester, NY 14621 (RGH)
   - United Memorial Medical Center, 127 North St, Batavia, NY 14020 (UMMC)
   - Newark-Wayne Community Hospital, 1200 Driving Park Ave, Newark, NY 14513
   - Clifton Springs Hospital & Clinic, 2 Coulter Rd, Clifton Springs, NY 14432
   - Unity Hospital, 1555 Long Pond Rd, Rochester, NY 14626
   - Unity Specialty Hospital, 89 Genesee St, Rochester, NY 14611
   - St. Mary's Medical Campus, 89 Genesee St, Rochester, NY 14611
   - Canton-Potsdam Hospital, 50 Leroy St, Potsdam, NY 13676
   - Gouverneur Hospital, 77 W Barney St, Gouverneur, NY 13642
   - Massena Hospital, 1 Hospital Dr, Massena, NY 13662
   Otherwise preserve the quote's facility/location. If absent, use null.

5. scope_of_work must be thorough and detailed, organized by numbered task where \
appropriate, with technical details, equipment references, and deliverables.

6. ai_assumptions entries must be objects with "text" and a "section" of \
"inclusion", "exclusion", or "scope".

7. contact_name and contact_email are the vendor contact/representative, or null.

8. short_description is 20 characters or fewer, including spaces.

9. work_category must be exactly one key:
   chemical_treatment, building_automation, electrical_pm,
   preventive_maintenance, repairs, repair_cap, steam_trap, water_softener.
   Use repairs only when genuinely ambiguous.

10. asset_reference is a specific equipment tag only. Normalize toward TAG-NUMBER \
form. Return null for equipment types without a specific unit. A wrong tag is \
worse than no tag.

Return ONLY a JSON object with exactly these keys:
{
  "vendor_name": "string",
  "project_description": "string",
  "facility_name": "string or null",
  "facility_address": "string or null",
  "scope_of_work": "string",
  "inclusions": ["string"],
  "exclusions": ["string"],
  "tax_status": "included | excluded | unclear",
  "tax_warning": "string or null",
  "tax_note": "string or null",
  "ai_assumptions": [{"text": "string", "section": "inclusion|exclusion|scope"}],
  "contact_name": "string or null",
  "contact_email": "string or null",
  "subtotal_amount": "string or null",
  "tax_amount": "string or null",
  "total_amount": "string or null",
  "short_description": "string or null",
  "work_category": "string",
  "asset_reference": "string or null"
}
"""


@dataclass
class AIAssumption:
    text: str
    section: str


@dataclass
class QuoteAnalysis:
    vendor_name: str = ""
    project_description: str = ""
    facility_name: Optional[str] = None
    facility_address: Optional[str] = None
    scope_of_work: str = ""
    inclusions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    tax_status: str = "unclear"
    tax_warning: Optional[str] = None
    tax_note: Optional[str] = None
    ai_assumptions: list[AIAssumption] = field(default_factory=list)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    subtotal_amount: Optional[str] = None
    tax_amount: Optional[str] = None
    total_amount: Optional[str] = None
    short_description: Optional[str] = None
    work_category: Optional[str] = None
    asset_reference: Optional[str] = None


def _match_facility(name: Optional[str], address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not name and not address:
        return None, None
    combined = f"{name or ''} {address or ''}".lower()
    for fac in FACILITIES.values():
        aliases = [str(alias).lower() for alias in fac.get("aliases", [])]
        if any(alias in combined for alias in aliases):
            return fac["name"], fac["address"]
    return name, address


def _strip_prices(text: str) -> str:
    text = re.sub(r"\$[\d,]+(?:\.\d{2})?(?:\s*USD)?", "", text)
    text = re.sub(
        r"\b\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:dollars|USD)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"  +", " ", text).strip()


def _analysis_request(quote_text: str) -> AIRequest:
    return AIRequest(
        operation="quote_analysis",
        system=SYSTEM_PROMPT,
        max_tokens=4096,
        prompt=(
            "Analyze the vendor quote and return the JSON extraction. Do not place "
            "prices in descriptive fields. Pay special attention to tax line items.\n\n"
            f"--- BEGIN QUOTE ---\n{quote_text}\n--- END QUOTE ---"
        ),
    )


def analyze_quote(
    quote_text: str,
    *,
    provider: AIProvider | None = None,
    env: Mapping[str, str] | None = None,
) -> QuoteAnalysis:
    """Analyze quote text through the configured provider adapter."""
    source = os.environ if env is None else env
    if not quote_text or not quote_text.strip():
        raise ValueError("Quote text is empty.")
    try:
        max_chars = int(source.get("EPC_AI_MAX_INPUT_CHARS", "250000"))
    except ValueError as exc:
        raise ValueError("EPC_AI_MAX_INPUT_CHARS must be an integer.") from exc
    if max_chars < 1000:
        raise ValueError("EPC_AI_MAX_INPUT_CHARS must be at least 1,000.")
    if len(quote_text) > max_chars:
        raise ValueError(
            f"Quote text contains {len(quote_text):,} characters, above the configured "
            f"AI input limit of {max_chars:,}. Split or reduce the source document."
        )
    active_provider = provider or get_ai_provider(source)
    require_capability(active_provider, CAP_TEXT)
    raw = active_provider.complete(_analysis_request(quote_text.strip()))
    data = normalize_analysis_response(raw)

    for key in ("project_description", "scope_of_work"):
        if data.get(key):
            data[key] = _strip_prices(data[key])
    data["inclusions"] = [
        clean for item in data.get("inclusions", []) if (clean := _strip_prices(item))
    ]
    data["exclusions"] = [
        clean for item in data.get("exclusions", []) if (clean := _strip_prices(item))
    ]

    data["facility_name"], data["facility_address"] = _match_facility(
        data.get("facility_name"), data.get("facility_address")
    )
    if data.get("tax_status") == "unclear" and not data.get("tax_warning"):
        data["tax_warning"] = (
            "WARNING: The vendor quote does not clearly state whether tax is included. "
            "Confirm tax status with the vendor before finalizing this agreement."
        )
    data.setdefault("tax_note", None)
    for key in (
        "contact_name",
        "contact_email",
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "short_description",
        "work_category",
        "asset_reference",
    ):
        data.setdefault(key, None)

    data["ai_assumptions"] = [
        AIAssumption(text=item["text"], section=item.get("section", "exclusion"))
        if isinstance(item, dict)
        else AIAssumption(text=str(item), section="exclusion")
        for item in data.get("ai_assumptions", [])
    ]
    return QuoteAnalysis(**data)
