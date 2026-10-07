"""Monthly evidence review and explicit page/CMMS mapping controls."""

from dataclasses import asdict, replace
import hashlib
import json

import streamlit as st

from app import monthly_report_sources as sources
from app.monthly_report_cmms import CMMSMapping, map_cmms, month_window
from app.monthly_report_model import ReportPeriod, ReportProfile
from app.monthly_report_content_policy import page_status, page_fingerprint, page_allowed


def _signature(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _cmms(content, profile, period, prefix, field):
    source = content.source
    tables = [t for i, t in enumerate(content.tables, 1) if i in source.selected_pages]
    title_key = field(prefix + "_sheet", tables[0].name)
    if st.session_state[title_key] not in {t.name for t in tables}:
        st.session_state[title_key] = tables[0].name
    title = st.selectbox("CMMS worksheet", [t.name for t in tables], key=title_key)
    table = next(t for t in content.tables if t.name == title)
    prefix += "_" + _signature(title)[:12]
    st.dataframe([dict(zip(table.columns, row)) for row in table.rows[:20]], hide_index=True)
    st.caption(f"{len(table.rows):,} rows. Map actual columns; the preview shows the first 20.")
    names = ["", *table.columns]
    labels = {"finished": "Finish date column", "work_order": "Work-order identity column", "facility": "Facility column",
              "description": "Description column", "area": "Area column", "tag": "Equipment tag column",
              "category": "PM/CM category column", "status": "Completion status column"}
    values = {key: st.selectbox(label, names, format_func=lambda v: v or "Not mapped",
                              key=field(prefix + "_" + key, "")) for key, label in labels.items()}
    assigned = ""
    if not values["facility"]:
        assigned = st.selectbox("Assign this export to a facility", ["", *(f.key for f in profile.facilities)],
                                format_func=lambda v: next((f.title for f in profile.facilities if f.key == v), "Choose explicitly"),
                                key=field(prefix + "_assigned", ""))
    def choices(column):
        return sorted({r[table.columns.index(column)] for r in table.rows if column and r[table.columns.index(column)]}) if column else []
    def selected_values(label, options, suffix):
        key = field(prefix + suffix, [])
        st.session_state[key] = [v for v in st.session_state[key] if v in options]
        return st.multiselect(label, options, key=key)
    statuses = selected_values("Statuses that mean completed", choices(values["status"]), "_complete") if values["status"] else []
    if not values["status"]:
        st.caption("Without a status column, a valid finish date is treated as completed work.")
    pm = selected_values("Category values that mean PM", choices(values["category"]), "_pm") if values["category"] else []
    cm = selected_values("Category values that mean CM", choices(values["category"]), "_cm") if values["category"] else []
    date_format = st.selectbox("Date format", ["ISO", "MM/DD/YYYY", "DD/MM/YYYY"], key=field(prefix + "_date_format", "ISO"))
    st.caption("Only confirm complete coverage where the export contains all completed work. Unconfirmed months/facilities remain blank in the twelve-month grid.")
    months = st.multiselect("Months with complete export coverage", month_window(period), key=field(prefix + "_months", []))
    facilities = st.multiselect("Facilities covered completely in those months", [f.key for f in profile.facilities],
                                format_func=lambda v: next(f.title for f in profile.facilities if f.key == v), key=field(prefix + "_coverage", []))
    mapping = CMMSMapping(**values, assigned_facility=assigned, completed_statuses=tuple(statuses), pm_values=tuple(pm),
                          cm_values=tuple(cm), date_format=date_format, complete_months=tuple(months), complete_facilities=tuple(facilities))
    signature = _signature((source.fingerprint, asdict(mapping), period.key))
    confirmation = st.checkbox("I confirm this CMMS mapping and coverage", key=prefix + "_confirm_" + signature)
    result_key = prefix + "_result"
    result = st.session_state.get(result_key)
    if result and result[0] != signature:
        st.session_state.pop(result_key, None)
        result = None
    if st.button("Apply CMMS mapping", key=prefix + "_apply", disabled=not confirmation):
        try:
            index = content.tables.index(table) + 1
            mapped = map_cmms(table, mapping, profile, period, sources.source_reference(source, index))
            result = (signature, mapped)
            st.session_state[result_key] = result
        except ValueError as exc:
            st.error(str(exc))
    if result:
        for message in result[1].notices:
            st.warning(message)
        for block, spec in zip(result[1].blocks, result[1].specs):
            st.write(spec.key.replace("_", " ").capitalize())
            st.dataframe([dict(zip([c.title for c in spec.columns], row)) for row in block.rows], hide_index=True)
    return (signature, result[1]) if result else (signature, None)


def render_uploads(profile: ReportProfile, period: ReportPeriod, prefix: str, field):
    st.subheader("Add this month’s vendor reports, chemical reports and photos")
    st.write("Only relevant, price-free pages belong in the client report. Check the suggested pages below; originals are kept for reference.")
    st.caption("PDF, images including HEIC, DOCX, XLSX, CSV, EML and MSG. Files are stored with this profile on the persistent disk; emails are read only. No email drafts or sending.")
    st.caption("Limits: 50 sources / 180 MB per report including attachments; 30 MB per file (DOCX 128 MB); 800,000 extracted characters. Up to 150 image/PDF pages can be embedded. OCR/vision is limited separately to 20 pages per report.")
    key = prefix + "_evidence"
    contents = st.session_state.setdefault(key, ())
    upload = st.file_uploader("Monthly source files", type=sorted(s.lstrip(".") for s in sources.SUPPORTED),
                             accept_multiple_files=True, max_upload_size=128, key=prefix + "_source_upload")
    if st.button("Read monthly files", disabled=not upload, key=prefix + "_read_sources"):
        with st.spinner("Reading local files and checking duplicates…"):
            contents, messages = sources.ingest_batch(profile, tuple((u.name, u.getvalue()) for u in upload), contents)
        st.session_state[key] = contents
        st.session_state[key + "_messages"] = messages
    for message in st.session_state.get(key + "_messages", ()):
        st.warning(message)
    if not contents:
        st.info("Add source files when available, or continue with library content and entered text.")
        with st.expander("Synthetic CMMS column example"):
            st.code("Work order,Finish date,Facility,Type,Status,Description\nDEMO-001,2026-09-02,Demo North,PM,Closed,Inspected demonstration unit", language="text")
            st.caption("Map your export's actual columns and category/status values after reading it. This example is synthetic and does not establish any report counts.")
        return (), {}, {}
    by_id = {c.source.id: c for c in contents}
    selection_key = field(key + "_selected", contents[0].source.id)
    if st.session_state[selection_key] not in by_id:
        st.session_state[selection_key] = contents[0].source.id
    selected = st.selectbox("Review source", list(by_id), format_func=lambda v: by_id[v].source.filename, key=selection_key)
    content, source = by_id[selected], by_id[selected].source
    p = key + "_" + selected
    with st.expander("Source facts and page selection", expanded=True):
        st.caption("Suggestions come from readable labels and keywords. Review or correct them; blank means not established.")
        classification = st.selectbox("Classification", sources.CLASSIFICATIONS, key=field(p + "_classification", source.classification))
        confidence = st.selectbox("Classification confidence", ["low", "medium", "high"], key=field(p + "_confidence", source.confidence))
        changes = {"classification": classification, "confidence": confidence}
        for attr, label in (("vendor", "Vendor"), ("service_date", "Service/report date (YYYY-MM-DD)"),
                            ("facility", "Source facility"), ("work_order", "Job / work-order number")):
            changes[attr] = st.text_input(label, key=field(p + "_" + attr, getattr(source, attr)))
        st.caption("Profile facilities and aliases: " + "; ".join(f.title + (" (" + ", ".join(f.aliases) + ")" if f.aliases else "") for f in profile.facilities))
        tags = st.text_input("Equipment tags (comma-separated)", key=field(p + "_tags", ", ".join(source.tags)))
        changes["tags"] = tuple(v.strip() for v in tags.split(",") if v.strip())
        for attr, label in (("actions", "Actions"), ("findings", "Findings"), ("recommendations", "Recommendations"),
                            ("follow_ups", "Follow-ups"), ("out_of_limit", "Out-of-limit readings")):
            changes[attr] = st.text_area(label, key=field(p + "_" + attr, getattr(source, attr)), height=70)
        for notice in source.notices:
            st.warning(notice)
        pages = list(range(1, len(source.page_texts) + 1))
        selected_pages = st.multiselect("Included pages / extracted items", pages, key=field(p + "_pages", list(source.selected_pages)),
                                       help="Readable technical pages are suggested. Pages with prices, legal terms, no useful content or unreadable images are not automatically included. Inspect image pages to decide. Originals remain saved.")
        changes["selected_pages"] = tuple(selected_pages)
        captions = dict(source.captions)
        if pages:
            page = st.selectbox("Preview page / item", pages, key=field(p + "_page", pages[0]),
                                format_func=lambda n: f"Page / item {n} · " + page_status(source.page_texts[n-1], unreadable=n in source.needs_vision)[0].replace("technical", "check before including").replace("review", "needs visual review"))
            st.text(source.page_texts[page-1][:12000] or "No native text on this page/item.")
            if page in sources.image_numbers(content):
                try:
                    thumbnail = sources.page_image(profile, content, page, preview=True)
                    st.image(thumbnail.data, width="stretch")
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                captions[page] = st.text_input("Page caption", key=field(p + f"_caption_{page}", captions.get(page, f"{source.filename} · page/item {page}")))
        changes["captions"] = tuple(sorted(captions.items()))
        source = replace(source, **changes)
        if pages and page in sources.image_numbers(content):
            kind, reason = page_status(source.page_texts[page-1], unreadable=page in source.needs_vision)
            blocked = kind in ("pricing", "legal", "blank", "signature")
            (st.warning if blocked else st.caption)(reason)
            if blocked and page in selected_pages:
                st.error("Remove this page from Included pages above. A page containing prices cannot be included, even if it also describes useful work.")
            fingerprint = page_fingerprint(source, page)
            reviewed = st.checkbox("I checked this page: relevant work, no prices, no legal-only or blank/signature-only content",
                                   key=field(p + f"_client_page_{page}_" + fingerprint, page_allowed(source, page)), disabled=blocked)
            reviews = dict(source.client_page_reviews)
            if reviewed and not blocked:
                reviews[page] = fingerprint
            else:
                reviews.pop(page, None)
            source = replace(source, client_page_reviews=tuple(sorted(reviews.items())))
            left = [n for n in source.selected_pages if n in sources.image_numbers(content) and not page_allowed(source, n)]
            if left:
                st.info("Still to check before including: " + ", ".join(f"page {n}" for n in left))
        by_id[selected] = replace(content, source=source)
        contents = tuple(by_id.values())
        st.session_state[key] = contents
        if st.button("Remove source from this draft", key=p + "_remove"):
            st.session_state[key] = tuple(c for c in contents if c.source.id != selected)
            st.rerun()
    st.caption(f"{len(contents)} sources. {sum(len(c.source.selected_pages) for c in contents)} selected pages/items. "
               f"{sum(len(set(c.source.needs_vision) & set(c.source.selected_pages)) for c in contents)} selected pages need OCR/vision; no paid extraction runs automatically.")
    blocks, specs = {}, {}
    with st.expander("Embed selected report pages and photographs"):
        destinations = []
        defaults = {"Vendor service": "vendor_reports", "Water treatment": "water_reports", "MBCx": "mbcx_report", "Improvement / training photo": "improvements"}
        for item in contents:
            if not sources.image_numbers(item):
                continue
            slot = st.selectbox("Destination · " + item.source.filename, ["Do not embed", *sources.PAGE_DESTINATIONS],
                                key=field(key + "_destination_" + item.source.id + "_" + item.source.classification,
                                          defaults.get(item.source.classification, "Do not embed")))
            if slot != "Do not embed":
                destinations.append((item.source.id, slot))
        signature = _signature(([c.source.fingerprint for c in contents], destinations))
        prepared_key = key + "_prepared_pages"
        prepared = st.session_state.get(prepared_key)
        if prepared and prepared[0] != signature:
            st.session_state.pop(prepared_key, None)
            prepared = None
            st.info("Source details or selections changed. Prepare pages again to use this version.")
        if st.button("Prepare selected pages", disabled=not destinations, key=key + "_prepare_pages"):
            try:
                with st.spinner("Preparing selected pages one at a time…"):
                    prepared = (signature, sources.prepare_pages(profile, contents, tuple(destinations)))
                st.session_state[prepared_key] = prepared
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        if prepared:
            blocks.update((b.key, b) for b in prepared[1])
            st.success("Reviewed pages are ready. Add them to the draft below.")
    cmms_contents = [c for c in contents if c.tables and c.source.classification == "CMMS export"
                     and any(i in c.source.selected_pages for i in range(1, len(c.tables)+1))]
    if cmms_contents:
        with st.expander("Map CMMS columns and twelve-month coverage"):
            cmms_key = field(key + "_cmms_source", cmms_contents[0].source.id)
            if st.session_state[cmms_key] not in {c.source.id for c in cmms_contents}:
                st.session_state[cmms_key] = cmms_contents[0].source.id
            chosen = st.selectbox("CMMS source", [c.source.id for c in cmms_contents],
                                  format_func=lambda v: next(c.source.filename for c in cmms_contents if c.source.id == v),
                                  key=cmms_key)
            candidate = next(c for c in cmms_contents if c.source.id == chosen)
            _, mapped = _cmms(candidate, profile, period, key + "_cmms_" + chosen, field)
            if mapped:
                blocks.update((b.key, b) for b in mapped.blocks)
                specs.update((s.key, s) for s in mapped.specs)
                st.caption("Choose This month → Uploaded content for Work orders and Service calls to include these mapped tables.")
    return tuple(c.source for c in contents), blocks, specs
