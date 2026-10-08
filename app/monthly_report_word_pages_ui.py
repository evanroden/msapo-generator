"""Review complete chart pages instead of disconnected drawing fragments."""

import hashlib

import streamlit as st

from app.monthly_report_checks import placeholder_matches, stale_period_mentions
from app.monthly_report_content_policy import page_status
from app.monthly_report_docx import ReportImage, normalize_report_image
from app.monthly_report_sections import readable_label
from app.monthly_report_word_pages import preserve_word_pages


def chart_page_review(section, path, period, prefix, field, old, plan, blocking):
    if section.key != "organization":
        return False
    key = prefix + "_word_pages"
    with st.expander("Keep the original chart and contact page layouts", expanded=old.get("page_layout", False)):
        st.write("If a chart appears as separate pieces or is missing below, prepare its complete pages here. Check the preview against your original, then choose the pages to keep.")
        st.caption("These become reusable pictures. Names and boxes inside them are not individually editable. You can build an editable chart in Site information instead.")
        sections = tuple(sorted({i.word_section for i in section.items if i.part == "word/document.xml"}))
        if st.button("Prepare chart and contact pages", key=key + "_prepare"):
            try:
                with st.spinner("Preparing chart pages…"):
                    st.session_state[key] = preserve_word_pages(path, sections)
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        pages = st.session_state.get(key, ())
        if not pages:
            return False
        version = hashlib.sha256(b"".join(hashlib.sha256(p.data).digest() for p in pages)).hexdigest()[:16]
        use = st.checkbox("Use complete pages for this section", key=field(key + "_use_" + version, old.get("page_layout", False)))
        if not use:
            st.caption("Your existing choices below are still in use. Enable complete pages to replace those choices.")
            return False
        plan["page_layout"] = True
        plan["preserved_assets"], plan["word_page_records"] = [], []
        st.info("Only the pages you check here will appear in this section. Individual fragments below are replaced in this draft; the original file is retained.")
        slots = ("org_chart", "business_hours_workflow", "after_hours_workflow", "contact_matrix")
        choices = {entry["page"]: entry["slot"] for entry in old.get("word_page_records", ())}
        for page in pages:
            page_key = key + "_" + version + "_" + str(page.number)
            with st.expander(f"Page {page.number} · preview and choose", expanded=page.number == 1):
                preview = normalize_report_image(page.data, ".png", line_art=True, dpi=96)
                st.image(preview.data, width=min(preview.width, 700))
                status, reason = page_status(page.text, unreadable=not page.text.strip())
                forbidden = page.blank or status in ("pricing", "legal", "signature") or bool(placeholder_matches(page.text))
                if forbidden:
                    st.warning("Leave this page out: " + ("the page is blank." if page.blank else "template instructions were detected." if placeholder_matches(page.text) else reason))
                keep = st.checkbox(f"Include page {page.number}", disabled=forbidden,
                                   key=field(page_key + "_keep", page.number in choices and not forbidden))
                if not keep or forbidden:
                    continue
                slot = st.selectbox(f"Page {page.number} contains", slots, format_func=readable_label,
                                    key=field(page_key + "_slot", choices.get(page.number, "org_chart")))
                if stale_period_mentions(page.text, period.year, period.month):
                    st.warning("This page mentions another month. Check that it is still current before keeping it.")
                checked = st.checkbox(f"Page {page.number} matches the original and is current, complete and price-free",
                                      key=field(page_key + "_checked_" + slot, False))
                if not checked:
                    blocking.append(f"Check page {page.number} against the original before including it.")
                plan["preserved_assets"].append((slot, ReportImage(page.data, "png", page.width, page.height)))
                plan["word_page_records"].append({"page": page.number, "slot": slot, "sections": sections,
                                                  "sha256": hashlib.sha256(page.data).hexdigest(),
                                                  "text": page.text, "blank": page.blank, "reviewed": checked})
        if not plan["preserved_assets"]:
            blocking.append("Check at least one complete page, or turn off complete pages to use individual pictures and text.")
        plan["unsupported_reviewed"] = bool(plan["preserved_assets"]) and not blocking
        return True
