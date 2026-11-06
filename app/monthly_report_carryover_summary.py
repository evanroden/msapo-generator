"""Describe current intake selections without changing or approving the plan."""

from app.monthly_report_model import known_sections, layout_blocks
from app.monthly_report_sections import default_slot, table_without_prices


_SINGLE_PICTURE_SLOTS = {
    "cover_photo", "brand_logo", "client_logo", "org_chart",
    "business_hours_workflow", "after_hours_workflow", "contact_matrix",
}


def carryover_summary(section, plan):
    # This is the section approval used by Continue, not another approval gate.
    status = "ready" if plan.get("approved") else "needs review"
    if plan.get("omit"):
        return status + " · source contribution deliberately excluded · original retained"

    items = {item.id: item for item in section.items}
    selected = set() if plan.get("page_layout") else set(plan.get("selected", ()))
    texts = plan.get("texts", {})
    text_count = sum(bool(texts.get(identity, item.text).strip())
                     for identity, item in items.items()
                     if identity in selected and item.kind == "text")
    tables = plan.get("tables", {})
    table_count = sum(bool(tables[identity] if identity in tables else table_without_prices(item)[0])
                      for identity, item in items.items()
                      if identity in selected and item.kind == "table")
    replacements = [(slot, image) for slot, image in plan.get("new_assets", ())
                    if not (slot == "cover_photo" and plan.get("cover_photo_omitted"))]
    replaced_slots = {slot for slot, _ in replacements if slot in _SINGLE_PICTURE_SLOTS}
    specs = known_sections()
    section_keys = {spec.key for spec in specs}
    known = {block.key for spec in specs for block in spec.blocks} | {block.key for block in layout_blocks()}

    def destination(item):
        target = plan.get("target", section.key)
        if plan.get("destinations", {}).get(item.id):
            return plan["destinations"][item.id]
        if target == item.section and item.suggested_slot in known:
            return item.suggested_slot
        # An unfinished Other/Cover review has no default report section yet.
        return default_slot(target) if target in section_keys else ""

    pictures = [item for identity, item in items.items()
                if identity in selected and item.kind == "image"
                and destination(item) not in replaced_slots]
    pages = [(slot, image) for slot, image in plan.get("preserved_assets", ())
             if (plan.get("page_layout") or plan.get("auto_native_diagrams"))
             and slot not in replaced_slots]
    # Named single-picture replacements overwrite earlier pictures in that
    # slot. Other slots keep their separate selected additions.
    replacement_count = len(replaced_slots) + sum(slot not in _SINGLE_PICTURE_SLOTS for slot, _ in replacements)
    unresolved = sum(item.kind == "unsupported" for item in items.values()) if not plan.get("unsupported_reviewed") else 0
    pieces = [status]

    def count(value, singular, plural=None):
        if value:
            pieces.append(str(value) + " " + (singular if value == 1 else plural or singular + "s"))

    count(text_count, "editable text selection")
    count(table_count, "editable table")
    count(len(pictures), "source picture selected", "source pictures selected")
    count(len(pages), "complete page selected as an image", "complete pages selected as images")
    count(replacement_count, "replacement picture selected", "replacement pictures selected")
    count(unresolved, "unsupported item unresolved", "unsupported items unresolved")
    if plan.get("cover_photo_omitted"):
        pieces.append("cover photograph deliberately omitted")
    if plan.get("native_art_review"):
        pieces.append("native artwork preservation selected")
    if len(pieces) == 1:
        pieces.append("no source content selected" if items else "source content not found")
    return " · ".join(pieces)


def render_carryover_summary(sections, plans):
    import streamlit as st

    for section in sections:
        st.caption(section.title + " · " + carryover_summary(section, plans.get(section.key, {})))
