"""
Quote analysis via the Anthropic API.

Sends quote text to Claude and receives structured extraction with:
- Vendor name
- Project description
- Facility match
- Inclusions / Exclusions (with AI-estimated flags)
- Tax status
- All pricing stripped
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, FACILITIES

SYSTEM_PROMPT = """\
You are an expert construction and facilities project analyst working for a \
healthcare system. Your job is to read a vendor quote and extract structured \
data so that a Scope of Work (MSAPO agreement) can be generated.

STRICT RULES:

1. **NEVER include any dollar amounts, hourly rates, unit prices, line-item \
   costs, totals, or any financial figures in your output.** Strip every \
   price completely. Do not mention specific costs or totals anywhere.

2. If standard inclusions or exclusions are missing from the quote, infer \
   the most reasonable ones based on the type of work described. Wrap every \
   AI-inferred item with the marker [AI ESTIMATE: <item>] so the user can \
   review it. Only use this marker for items YOU inferred — never flag items \
   that are explicitly stated in the quote.

3. **TAX STATUS — READ CAREFULLY:**
   Search the ENTIRE quote for ANY mention of tax. Look specifically for:
   - Lines labeled "SALES TAX", "TAX", or "Sales Tax"
   - Phrases like "tax included", "tax excluded", "plus tax", "tax exempt"
   - Clarification notes about tax (e.g., "Estimated sales taxes is noted above")
   - Line items showing a tax amount (even if you strip the dollar value)

   Based on what you find:
   - "included" — if there is an explicit SALES TAX line item in the pricing \
     section OR the quote says tax is included in the price. A separate \
     "SALES TAX" line item with a dollar amount means tax IS included in \
     the total. Also note any clarifications (like "Estimated sales taxes \
     is noted above. What is added to the invoice may be different.")
   - "excluded" — if the quote explicitly says tax is excluded, extra, or \
     "plus applicable tax"
   - "unclear" — ONLY if there is truly zero mention of tax anywhere in the \
     document. If you see ANY tax reference, it is NOT unclear.

   Set tax_warning to null if status is "included" or "excluded".
   Set tax_warning to a clear warning message if status is "unclear".
   If status is "included" but there's a clarification about estimated vs \
   actual tax, include that note in tax_note.

4. Match the facility location to one of these known sites if mentioned:
   - "RRH St. Mary's Medical Center, 89 Genesee St, Rochester, NY 14611"
   - "United Memorial Medical Center, 127 North Street, Batavia, NY 14020"
   Also look for abbreviations like "UMMC" (United Memorial Medical Center) \
   or "St. Mary's". If neither matches, use whatever facility/location the \
   quote references. If no location is given, set facility to null.

5. For scope_of_work, write a thorough and detailed description of ALL work \
   items. Organize by numbered task if the quote has numbered sections. \
   Include technical details, equipment references, and specific deliverables. \
   Do NOT summarize — be comprehensive.

6. For ai_assumptions: each entry must be an object (not a string) with:
   - "text": the assumption text (e.g., "Structural modifications")
   - "section": which document section this applies to. Must be one of:
     "inclusion", "exclusion", or "scope"
   This tells the user exactly WHERE each assumption would appear in the \
   final document.

Return your answer as a JSON object with exactly these keys:
{
  "vendor_name": "string",
  "project_description": "string — a concise 1-2 sentence summary",
  "facility_name": "string or null",
  "facility_address": "string or null",
  "scope_of_work": "string — detailed multi-paragraph scope, NO prices",
  "inclusions": ["string", ...],
  "exclusions": ["string", ...],
  "tax_status": "included | excluded | unclear",
  "tax_warning": "string or null",
  "tax_note": "string or null — any clarifications about tax from the quote",
  "ai_assumptions": [{"text": "string", "section": "inclusion|exclusion|scope"}, ...]
}

Return ONLY the JSON object, no markdown fences, no extra text.
"""


@dataclass
class AIAssumption:
    """A single AI-inferred assumption with its target section."""
    text: str
    section: str  # "inclusion", "exclusion", or "scope"


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


def _match_facility(name: Optional[str], address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Cross-reference extracted facility against known RRH sites using aliases."""
    if not name and not address:
        return None, None

    combined = f"{name or ''} {address or ''}".lower()

    for _key, fac in FACILITIES.items():
        aliases = fac.get("aliases", [])
        if any(alias in combined for alias in aliases):
            return fac["name"], fac["address"]

    return name, address


def _strip_prices(text: str) -> str:
    """Remove any residual dollar amounts the AI might have missed."""
    # $1,234.56 or $1234
    text = re.sub(r"\$[\d,]+(?:\.\d{2})?(?:\s*USD)?", "", text)
    # 1,234.56 USD or 1234 dollars
    text = re.sub(
        r"\b\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:dollars|USD)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Clean up leftover artifacts like double spaces or orphaned colons
    text = re.sub(r"  +", " ", text)
    return text.strip()


def _call_api_with_retry(client, quote_text: str, max_retries: int = 3) -> str:
    """Call the Anthropic API with automatic retry for transient errors."""
    last_error = None
    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Analyze the following vendor quote and return the JSON "
                            "extraction. Remember: absolutely NO prices in any field.\n\n"
                            "PAY SPECIAL ATTENTION to any SALES TAX line items in the "
                            "pricing section — if a 'SALES TAX' line exists with a dollar "
                            "amount, tax IS included in the quoted total.\n\n"
                            f"--- BEGIN QUOTE ---\n{quote_text}\n--- END QUOTE ---"
                        ),
                    }
                ],
            )
            return message.content[0].text.strip()
        except anthropic.APIStatusError as e:
            last_error = e
            # Retry on overloaded (529), rate limit (429), or server errors (5xx)
            if e.status_code in (429, 529) or e.status_code >= 500:
                wait = (attempt + 1) * 5  # 5s, 10s, 15s
                time.sleep(wait)
                continue
            raise  # Non-retryable error
    raise last_error  # All retries exhausted


def analyze_quote(quote_text: str) -> QuoteAnalysis:
    """Send quote text to the Anthropic API and return structured analysis."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    raw = _call_api_with_retry(client, quote_text)

    # Handle possible markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)

    # Post-process: strip any residual pricing from every string field
    for key in ("project_description", "scope_of_work"):
        if key in data and data[key]:
            data[key] = _strip_prices(data[key])

    data["inclusions"] = [_strip_prices(i) for i in data.get("inclusions", []) if _strip_prices(i)]
    data["exclusions"] = [_strip_prices(e) for e in data.get("exclusions", []) if _strip_prices(e)]

    # Cross-reference facility
    fac_name, fac_addr = _match_facility(
        data.get("facility_name"), data.get("facility_address")
    )
    data["facility_name"] = fac_name
    data["facility_address"] = fac_addr

    # Ensure tax warning exists when status is unclear
    if data.get("tax_status") == "unclear" and not data.get("tax_warning"):
        data["tax_warning"] = (
            "WARNING: The vendor quote does not clearly state whether tax is "
            "included. Please confirm tax status with the vendor before "
            "finalizing this agreement."
        )

    # Default tax_note if not provided
    if "tax_note" not in data:
        data["tax_note"] = None

    # Convert raw JSON dicts to AIAssumption objects
    raw_assumptions = data.get("ai_assumptions", [])
    data["ai_assumptions"] = [
        AIAssumption(text=a["text"], section=a.get("section", "exclusion"))
        if isinstance(a, dict) else AIAssumption(text=str(a), section="exclusion")
        for a in raw_assumptions
    ]

    return QuoteAnalysis(**data)
