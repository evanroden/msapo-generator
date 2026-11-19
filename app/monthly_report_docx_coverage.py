"""Read-only, source-addressed coverage ledger for Starting Report DOCX inspection.

"Imported" here means text/cells were *captured as mapping candidates*, not
approved, written to a report, or proven visually complete. Images and native
drawings stay review-needed even when their source bytes are retained.
Physical Word pages cannot be inferred from Word section boundaries.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageEntry:
    item_id: str
    source_part: str
    source_position: int
    relationship_id: str
    word_region: str
    review_location: str
    section: str
    kind: str
    status: str
    confidence: str
    text: str = ""
    cells: tuple[tuple[str, ...], ...] = ()
    media_part: str = ""
    reason: str = ""


def coverage_inventory(inspection):
    """Account for every inspector occurrence and explicit excluded-review class.

    No source file or report is opened or changed. An exclusion aggregate
    describes normalized-away review markup whose original individual XML
    positions are intentionally not claimed to be known.
    """
    from app.monthly_report_sections import section_reviews

    review = {item.id: group.key
              for group in section_reviews(inspection) for item in group.items}
    entries = []
    for item in inspection.items:
        if item.kind in ("text", "table"):
            status, confidence, reason = "imported", "direct-XML", ""
        elif item.position == 0 and ("macro" in item.note.lower() or "embedded object" in item.note.lower()):
            status, confidence, reason = "excluded-with-reason", "not-extracted", item.note
        else:
            status, confidence = "review-needed", "layout-or-media"
            reason = item.note or ("Image bytes are retained, but their depicted content is not extracted."
                                   if item.kind == "image" else
                                   "Source object needs section/page review before approval.")
        region = (f"Word section {item.word_section}; physical page unknown"
                  if item.position else "Package part; no proved Word page")
        entries.append(CoverageEntry(
            item.id, item.part, item.position,
            getattr(item, "relationship_id", ""),
            region, review.get(item.id, "other"),
            item.section, item.kind, status, confidence,
            item.text, item.rows, item.image_part, reason))
    for label, marker in (
        ("tracked-deletions", "Tracked changes use their final accepted view."),
        ("word-comments", "Word comments are excluded"),
    ):
        notice = next((n for n in inspection.notices if marker in n), "")
        if notice:
            entries.append(CoverageEntry(
                f"excluded:{label}", "Word review markup (part positions unavailable)",
                0, "", "Original preserved; physical page unknown", "other", "",
                label, "excluded-with-reason", "not-extracted", reason=notice))
    return tuple(entries)


def coverage_totals(entries):
    """A deterministic coverage ledger, never a claim of saved report rows."""
    return {status: sum(entry.status == status for entry in entries)
            for status in ("imported", "review-needed", "excluded-with-reason")}
