"""Display-only descriptions of inspected Word content; never infer OCR."""

from collections import Counter


def content_kind_description(item):
    return {
        "text": "Extracted Word text · review wording before including it.",
        "table": "Native Word table · extracted cells can be reviewed and mapped.",
        "image": "Picture · its text and cells are not directly editable. Image reading is a separate, optional step.",
        "unsupported": "Word layout requiring review · drawings or embedded content are not an editable table here.",
        "native_layout": "Native Word layout · design content, not an editable table here.",
    }.get(item.kind, "Content type not recognized · review the original.")


def section_content_description(items, *, section_key=None):
    # A drawing may also produce flattened text at the same source location.
    # Those labels are review evidence, not another editable source paragraph.
    items = tuple(item for item in items if section_key is None or item.position > 0)
    location = lambda item: (item.part, item.word_section, item.position)
    unresolved = {location(item) for item in items if item.kind == "unsupported"}
    counts = Counter()
    for item in items:
        if item.kind in {"text", "table"}:
            if location(item) in unresolved:
                continue
            # Cover prose/tables do not enter its editor; only its footer does.
            if section_key == "cover" and item.suggested_slot != "footer_text":
                continue
        counts[item.kind] += 1
    counts["unsupported"] = len(unresolved)
    labels = (("text", "text item", "text items"),
              ("table", "native table", "native tables"),
              ("image", "picture", "pictures"),
              ("native_layout", "native layout", "native layouts"),
              ("unsupported", "layout needing review", "layouts needing review"))
    parts = [f"{counts[kind]} {singular if counts[kind] == 1 else plural}"
             for kind, singular, plural in labels if counts[kind]]
    return "Imported content: " + " · ".join(parts) if parts else ""


def image_review_caption(item, number, section):
    """Use bounded source wording or a known purpose, never invented OCR text."""
    from app.monthly_report_model import known_sections
    from app.monthly_report_ui_text import literal

    title = next((s.title for s in known_sections() if s.key == section), "this section")
    description = " ".join(item.text.split())
    if len(description) > 180:
        description = description[:177] + "…"
    if not description:
        roles = {"brand_logo": "ENFRA logo", "client_logo": "Client logo",
                 "cover_photo": "Cover photograph", "org_chart": "Organization chart",
                 "business_hours_workflow": "Daytime outage procedure",
                 "after_hours_workflow": "After-hours outage procedure"}
        description = roles.get(item.suggested_slot, "")
        if not description:
            description = "Imported picture in " + ("Cover" if section == "cover" else title)
    return f"Picture {number} · {literal(description)} · Image-only"


def image_replacement_guidance(section):
    from app.monthly_report_section_help import section_help

    if section == "other":
        return ("Image-only: text and cells inside pictures are not editable here. "
                "Choose a destination above, then use that section's picture controls after setup.")
    action = section_help(section).edit
    if section == "organization":
        return ("Image-only: names and cells inside pictures are not editable here. "
                f"Choose ‘{action}’ above, then upload only the chart or contact page being replaced.")
    return ("Image-only: text and cells inside pictures are not editable here. "
            f"Choose ‘{action}’ above to upload a replacement; choose ‘Leave out’ on the old picture. "
            "The original stays saved.")
