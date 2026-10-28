"""Describe the current import plan, separately from the source inventory."""
from app.monthly_report_sections import default_slot, table_without_prices
from app.monthly_report_model import known_sections, layout_blocks


def carryover_summary(section, plan):
    status = "ready" if plan.get("approved") else "needs review"
    if plan.get("omit"):
        return status + " · source contribution deliberately excluded · original retained"
    items = {item.id: item for item in section.items}
    selected = set() if plan.get("page_layout") else set(plan.get("selected", ()))
    editable_text = sum(bool(plan.get("texts", {}).get(identity, item.text).strip())
                        for identity, item in items.items() if identity in selected and item.kind == "text")
    tables = plan.get("tables", {})
    editable_tables = sum(bool(tables[identity] if identity in tables else table_without_prices(item)[0])
                          for identity, item in items.items() if identity in selected and item.kind == "table")
    pictures = [item for identity, item in items.items() if identity in selected and item.kind == "image"]
    replacements = [(slot, image) for slot, image in plan.get("new_assets", ())
                    if not (slot == "cover_photo" and plan.get("cover_photo_omitted"))]
    replaced_slots = {slot for slot, _ in replacements if slot in {
        "cover_photo", "brand_logo", "client_logo", "org_chart", "business_hours_workflow",
        "after_hours_workflow", "contact_matrix"}}
    known = {b.key for s in known_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
    def slot(item):
        target = plan.get("target", section.key)
        return plan.get("destinations", {}).get(item.id) or (
            item.suggested_slot if target == item.section and item.suggested_slot in known else default_slot(target))
    pictures = [item for item in pictures if slot(item) not in replaced_slots]
    pages = [(slot, image) for slot, image in plan.get("preserved_assets", ()) if slot not in replaced_slots]
    excluded = {identity for name in ("content_role_reviews", "table_role_reviews")
                for identity, receipt in plan.get(name, {}).items() if receipt.get("action") == "exclude"}
    if plan.get("cover_photo_omitted"):
        excluded.update(plan.get("cover_photo_source_ids", ()))
    included = selected | set(plan.get("combined_text_ids", ()))
    # Page review has no reliable paragraph-to-page mapping. Describe those
    # selections using its actual page records, not a guessed per-item loss.
    page_sections = set(plan.get("captured_word_sections", ()))
    if plan.get("page_layout"):
        page_sections.update(number for record in plan.get("word_page_records", ()) for number in record.get("sections", ()))
    included.update(item.id for item in items.values() if item.word_section in page_sections and item.part == "word/document.xml")
    unresolved = {item.id for item in items.values() if item.kind == "unsupported"
                  and not plan.get("unsupported_reviewed") and item.id not in included}
    other = set(items) - included - excluded - unresolved
    pieces = [status]
    def count(value, singular, plural=None):
        if value:
            pieces.append(str(value) + " " + (singular if value == 1 else plural or singular + "s"))
    count(editable_text, "editable text selection")
    count(editable_tables, "editable table")
    count(len(pictures), "source picture selected", "source pictures selected")
    count(len(pages), "complete page retained as an image", "complete pages retained as images")
    count(len(replacements), "replacement picture selected", "replacement pictures selected")
    count(len(excluded.intersection(items)), "source item deliberately excluded", "source items deliberately excluded")
    count(len(unresolved), "unsupported item unresolved", "unsupported items unresolved")
    count(len(other), "other source item not selected", "other source items not selected")
    if plan.get("cover_photo_omitted"):
        pieces.append("cover photograph deliberately omitted")
    if plan.get("native_art_review"):
        pieces.append("native artwork preservation selected")
    if not items and not replacements and not pages:
        pieces.append("source content not found")
    elif len(pieces) == 1:
        pieces.append("no editable content or pictures selected")
    return " · ".join(pieces)


def render_carryover_summary(sections, plans):
    import streamlit as st
    for section in sections:
        st.caption(section.title + " · " + carryover_summary(section, plans.get(section.key, {})))
