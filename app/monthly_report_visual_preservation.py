"""Conservative, section-bound preservation of native Word diagrams.

A recognized Word drawing is never equated with an absent picture. Complex
VML/SmartArt can be rendered through the existing passive, resource-capped
page converter. This module neither executes source content nor opens other
clients' report records; failure leaves the exact source available for a
section-specific replacement instead of silently excluding its art.
"""
from hashlib import sha256

from app.monthly_report_checks import placeholder_matches
from app.monthly_report_content_policy import page_status
from app.monthly_report_docx import ReportImage
from app.monthly_report_word_pages import preserve_word_pages


# Keep source geometry in its original logical section, not in whichever
# section happens to be currently active in the editor. Non-image block types
# may contain attached page-art assets in the native/document writer.
VISUAL_SLOTS = {
    "organization": "org_chart",
    "activity": "improvements",
    "scorecards": "utility_analysis",
    "mbcx": "mbcx_report",
    "maintenance": "vendor_reports",
    "subcontractors": "subcontractor_matrix",
    "water": "water_reports",
    "issues": "equipment_issues_evidence",
    "capital": "capital_renewal",
    "training": "training_summary",
    "rfi": "rfi_matrix",
}


class DiagramPreservationError(ValueError):
    """A diagram needs a specific recovery; never silently skip it."""


def diagram_source_sections(inspection, section):
    """Return self-contained physical Word sections for a logical section."""
    drawings = tuple(item for item in section.items
                     if item.kind == "unsupported"
                     and item.part == "word/document.xml"
                     and item.section == section.key)
    if not drawings:
        return ()
    if section.key not in VISUAL_SLOTS:
        raise DiagramPreservationError(
            f"The original {section.title} has artwork with no safe destination; "
            "choose its destination or provide a clear replacement.")
    sections = tuple(sorted({item.word_section for item in drawings}))
    if any(number < 1 for number in sections) or len(sections) > 8:
        raise DiagramPreservationError(
            f"The {section.title} drawings span too many source pages for automatic preservation. "
            "Use the existing chart/page preview or add the affected image here.")
    for number in sections:
        others = {item.section for item in inspection.items
                  if item.part == "word/document.xml" and item.word_section == number
                  and item.position and item.section not in ("", "cover", section.key)}
        if others:
            raise DiagramPreservationError(
                f"The {section.title} drawing shares a Word page with another report section. "
                "Its destination must be resolved before copying that page.")
    return sections


def preserve_section_diagrams(path, inspection, section):
    """Prepare only proved-current source page art and its immutable provenance.

    Word screenshots include full page context and can contain pricing
    invisible to plain text extraction. A page with unreadable text remains
    unresolved instead of receiving a forged 'price-free' certification.
    """
    word_sections = diagram_source_sections(inspection, section)
    if not word_sections:
        return None
    try:
        pages = preserve_word_pages(path, word_sections)
    except (ValueError, OSError) as exc:
        raise DiagramPreservationError(
            f"The original {section.title} diagram could not be safely rendered. "
            "The source is retained; retry its native page preview or upload a clear replacement "
            "in this section before continuing."
        ) from exc
    assets, records = [], []
    for page in pages:
        kind, _ = page_status(page.text, unreadable=not page.text.strip())
        if (page.blank or kind in ("pricing", "legal", "signature", "blank")
                or placeholder_matches(page.text)):
            raise DiagramPreservationError(
                f"Page {page.number} of the original {section.title} drawing needs "
                "a safe visual content check or clear replacement. It was not dropped or "
                "approved without proof.")
        # A diagram that has graphic pixels but no extractable Word text must
        # remain visible in the working report. Preserve it as an unapproved
        # image, not as nonexistent content. Later client-export privacy gates
        # can require a specific image review; this is not a price clearance.
        visual_review_required = kind == "review"
        digest = sha256(page.data).hexdigest()
        slot = VISUAL_SLOTS[section.key]
        assets.append((slot, ReportImage(page.data, "png", page.width, page.height)))
        records.append({
            "page": page.number, "slot": slot, "sections": word_sections,
            "sha256": digest, "text": page.text, "blank": page.blank,
            "source_sha256": inspection.sha256,
            "source_verified": True, "reviewed": False,
            "visual_review_required": visual_review_required,
        })
    if not assets:
        raise DiagramPreservationError(
            f"No usable {section.title} drawing was recovered. The original was retained.")
    return {"preserved_assets": assets, "word_page_records": records,
            "auto_native_diagrams": True, "captured_word_sections": word_sections}
