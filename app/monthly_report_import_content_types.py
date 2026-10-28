"""Read-only editing capabilities from the existing DOCX inspection inventory."""
from collections import Counter


def _location(item):
    return item.part, item.word_section, item.position


def content_type_summary(section):
    """Do not advertise text flattened from an unresolved drawing as editable.

    The inspector can report both extracted text and an unsupported drawing at
    one source location. Their labels are useful for review, not evidence that
    the original layout can be edited safely. Do not change source items here.
    """
    items = tuple(item for item in section.items if item.position > 0)
    unresolved = {_location(item) for item in items if item.kind == "unsupported"}
    counts = Counter()
    for item in items:
        if item.kind == "image":
            counts["Image-only pictures"] += 1
        elif item.kind in {"text", "table"} and _location(item) not in unresolved:
            # The cover editor deliberately ignores old cover prose and tables.
            if section.key == "cover" and item.suggested_slot != "footer_text":
                continue
            counts["Editable text" if item.kind == "text" else "Editable tables"] += 1
    counts["Layout review needed"] = len(unresolved)
    labels = ("Editable text", "Editable tables", "Image-only pictures", "Layout review needed")
    return " · ".join(f"{label}: {counts[label]}" for label in labels if counts[label])


def render_content_types(section):
    """One compact inventory before the existing import/replacement controls."""
    import streamlit as st

    summary = content_type_summary(section)
    if summary:
        st.caption("Content types: " + summary)
    if any(item.kind == "unsupported" and item.position > 0 for item in section.items):
        st.caption("Layout review is required; extracted labels do not make a drawing editable. "
                   "Check its original page or use the existing replacement controls.")


def image_review_caption(item, number, section):
    """Name the picture using source-supplied wording, never invented OCR text."""
    from app.monthly_report_model import known_sections
    from app.monthly_report_ui_text import literal

    title = next((s.title for s in known_sections() if s.key == section), "this section")
    description = " ".join(item.text.split())
    if len(description) > 180:
        description = description[:177] + "…"
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
