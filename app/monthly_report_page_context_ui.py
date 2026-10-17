"""Source-page context that reopens the existing metadata owner."""
from html import escape

import streamlit as st


def open_report_page_task(prefix, source_id):
    """Open the existing native page task after capturing manager edits."""
    from uuid import uuid4
    local = prefix + "_evidence_section_water_reports"
    st.session_state[local + "_selected"] = source_id
    st.session_state[local + "_" + source_id + "_edit_page_reviews"] = True
    st.session_state[prefix + "_batch_files_open_close_request"] = True
    st.session_state[prefix + "_source_page_open_target"] = (source_id, uuid4().hex)


def render_page_source_context(source, profile, prefix, page):
    from app.monthly_report_source_details import facility_choice, KEEP_FACILITY
    from app.monthly_report_source_scope import source_review, MULTIPLE_FACILITIES, CONTRACT_ARTWORK
    selected = facility_choice(source, profile)
    titles = {site.key: site.title for site in profile.facilities}
    if selected == MULTIPLE_FACILITIES:
        sites = ", ".join(titles.get(key, key) for key in source_review(source).get("facilities", ()))
    elif selected == CONTRACT_ARTWORK:
        sites = "Shared contract artwork"
    elif selected == KEEP_FACILITY:
        sites = source.facility or "Not established"
    else:
        sites = titles.get(selected, source.facility) or "Not established"
    with st.container(key="monthly_source_page_correction_" + source.id):
        st.markdown('<span class="enfra-source-page-correction" id="source-page-context-' +
                    escape(source.id, quote=True) + '" data-source-id="' + escape(source.id, quote=True) +
                    '" data-return-target="report-section-water"></span>', unsafe_allow_html=True)
        request = st.session_state.get(prefix + "_source_page_open_target")
        if request and request[0] == source.id:
            st.markdown('<span class="enfra-report-page-target" data-source-id="' +
                        escape(source.id, quote=True) + '" data-token="' +
                        escape(request[1], quote=True) + '"></span>', unsafe_allow_html=True)
        st.caption("Source date: " + (source.service_date or "Not established") + " · Site: " + sites)
        from app.monthly_report_source_manager_ui import open_source_review
        st.button("Correct source details", key=prefix + "_source_details_action_" + source.id,
                  help="Open the saved source date and site beside this page. Original file bytes stay unchanged.",
                  on_click=open_source_review, args=(prefix, source.id, "date", page))


def render_correction_page(profile, content, page):
    """One deliberately opened source page; never external reading."""
    from app import monthly_report_sources as sources
    source = content.source
    if page not in range(1, len(source.page_texts) + 1):
        return None
    st.caption(f"Source page {page} of {len(source.page_texts)}")
    if page not in sources.image_numbers(content):
        st.text(source.page_texts[page - 1][:12000] or "No readable source text on this item.")
        return None
    try:
        image = sources.page_image(profile, content, page, preview=True)
        st.image(image.data, width="stretch")
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return None
    return source.id, source.sha256, page
