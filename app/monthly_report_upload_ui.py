"""Monthly evidence review and explicit page/CMMS mapping controls."""

from dataclasses import asdict, replace
import hashlib
import json

import streamlit as st

from app import monthly_report_sources as sources
from app.monthly_report_cmms import CMMSMapping, map_cmms, month_window
from app.monthly_report_model import ReportPeriod, ReportProfile
from app.monthly_report_content_policy import page_status, page_fingerprint, page_allowed, contains_price


def _signature(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _undecided_pages(content, source):
    exclusions = dict(source.client_page_exclusions)
    return [n for n in sources.image_numbers(content)
            if not (n in source.selected_pages and page_allowed(source, n))
            and exclusions.get(n) != page_fingerprint(source, n)]


def _sync_source_fields(source, prefix, field):
    """Refresh stale widgets when another section edited the canonical source.

    Only external changes are copied. A widget's pending input on this rerun is
    preserved when the canonical source still matches this view's last render.
    """
    previous = st.session_state.get(prefix + "_canonical_view")
    if previous is None or previous == source:
        return
    attributes = ("classification", "vendor", "service_date", "facility", "work_order",
                  "actions", "findings", "recommendations", "follow_ups", "out_of_limit")
    for attr in attributes:
        if getattr(previous, attr) != getattr(source, attr):
            st.session_state[field(prefix + "_" + attr, getattr(source, attr))] = getattr(source, attr)
    if previous.tags != source.tags:
        value = ", ".join(source.tags)
        st.session_state[field(prefix + "_tags", value)] = value
    if previous.selected_pages != source.selected_pages:
        value = list(source.selected_pages)
        st.session_state[field(prefix + "_pages", value)] = value
    before, after = dict(previous.captions), dict(source.captions)
    for number in set(before) | set(after):
        if before.get(number) != after.get(number):
            value = after.get(number, f"{source.filename} · page/item {number}")
            st.session_state[field(prefix + f"_caption_{number}", value)] = value
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
    result_key = prefix + "_result"
    result = st.session_state.get(result_key)
    if result and result[0] != signature:
        st.session_state.pop(result_key, None)
        result = None
    st.caption("Applying uses the columns and complete-coverage selections shown above. Months without confirmed coverage stay blank.")
    if st.button("Apply CMMS mapping", key=prefix + "_apply"):
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
    st.subheader("Add this month’s report files and photos")
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
    if len(by_id) == 1:
        selected = next(iter(by_id))
        st.write("Reviewing " + by_id[selected].source.filename)
    else:
        selected = st.selectbox("File to review", list(by_id), format_func=lambda v: by_id[v].source.filename, key=selection_key)
    content, source = by_id[selected], by_id[selected].source
    p = key + "_" + selected
    _sync_source_fields(source, p, field)
    pending = st.session_state.pop(p + "_page_action", None)
    if pending:
        st.session_state[p + "_pages"] = pending[0]
        st.session_state[p + "_page"] = pending[1]
    with st.expander("Choose pages for the client report", expanded=True):
        with st.expander("Edit vendor, date and work details"):
            st.caption("Suggestions come from readable labels and keywords. Review or correct them; blank means not established.")
            classification = st.selectbox("Classification", sources.CLASSIFICATIONS, key=field(p + "_classification", source.classification))
            changes = {"classification": classification}
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
        preview_ok = False
        if pages:
            page = st.selectbox("Preview page / item", pages, key=field(p + "_page", pages[0]),
                                format_func=lambda n: f"Page / item {n} · " + page_status(source.page_texts[n-1], unreadable=n in source.needs_vision)[0].replace("technical", "check before including").replace("review", "needs visual review"))
            st.caption(f"Page {page} of {len(pages)}. Check the page itself before including it.")
            with st.expander("Read extracted text"):
                st.text(source.page_texts[page-1][:12000] or "No native text on this page/item.")
            if page in sources.image_numbers(content):
                try:
                    thumbnail = sources.page_image(profile, content, page, preview=True)
                    st.image(thumbnail.data, width=650)
                    preview_ok = True
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                captions[page] = st.text_input("Page caption", key=field(p + f"_caption_{page}", captions.get(page, f"{source.filename} · page/item {page}")))
        changes["captions"] = tuple(sorted(captions.items()))
        source = replace(source, **changes)
        if pages and page in sources.image_numbers(content):
            kind, reason = page_status(source.page_texts[page-1], unreadable=page in source.needs_vision)
            blocked_content = kind in ("pricing", "legal", "blank", "signature")
            priced_caption = contains_price(captions.get(page, ""))
            blocked = blocked_content or priced_caption
            if priced_caption:
                reason = "Remove pricing from the caption before including this page."
            (st.warning if blocked else st.caption)(reason)
            if blocked_content and page in selected_pages:
                st.error("Leave this page out. Pages with prices, legal-only, blank or signature-only content cannot be included.")
            fingerprint = page_fingerprint(source, page)
            reviews = dict(source.client_page_reviews)
            st.caption("Include confirms that you checked this page and caption: relevant work, no prices, and no legal-only, blank or signature-only content. That review is kept until the page or caption changes.")
            left = _undecided_pages(content, source)
            checked = sum(page_allowed(source, n) for n in source.selected_pages if n in sources.image_numbers(content))
            st.caption(f"{checked} pages ready to include · {len(left)} pages still need a decision")
            keep, omit, advance = st.columns(3)
            action = None
            if keep.button("Include page and continue", key=p + "_keep_page", disabled=blocked or not preview_ok):
                action = "keep"
            if omit.button("Leave page out and continue", key=p + "_omit_page"):
                action = "omit"
            if advance.button("Next page needing review", key=p + "_next_page", disabled=not any(n != page for n in left)):
                action = "next"
            if action:
                chosen = set(source.selected_pages)
                exclusions = dict(source.client_page_exclusions)
                if action == "keep":
                    chosen.add(page)
                    reviews[page] = fingerprint
                    exclusions.pop(page, None)
                elif action == "omit":
                    chosen.discard(page)
                    reviews.pop(page, None)
                    exclusions[page] = page_fingerprint(source, page)
                source = replace(source, selected_pages=tuple(sorted(chosen)),
                                 client_page_reviews=tuple(sorted(reviews.items())),
                                 client_page_exclusions=tuple(sorted(exclusions.items())))
                remaining = [n for n in _undecided_pages(content, source) if n != page]
                next_page = next((n for n in remaining if n > page), remaining[0] if remaining else page)
                by_id[selected] = replace(content, source=source)
                st.session_state[key] = tuple(by_id.values())
                st.session_state[p + "_canonical_view"] = source
                # Apply widget changes before instantiation on the next rerun.
                st.session_state[p + "_page_action"] = (list(source.selected_pages), next_page)
                st.rerun()
            if not left:
                st.success("Every page has been checked. Prepare the included pages below." if checked else "Every page has been checked and left out. The original file is still saved.")
            st.caption("Leaving a page out keeps the original file. Use the page selector to revisit any page.")
        by_id[selected] = replace(content, source=source)
        contents = tuple(by_id.values())
        st.session_state[key] = contents
        st.session_state[p + "_canonical_view"] = source
        if st.button("Remove source from this draft", key=p + "_remove"):
            st.session_state[key] = tuple(c for c in contents if c.source.id != selected)
            st.rerun()
    st.caption(f"{len(contents)} sources. {sum(len(c.source.selected_pages) for c in contents)} selected pages/items. "
               f"{sum(len(set(c.source.needs_vision) & set(c.source.selected_pages)) for c in contents)} selected pages need OCR/vision; no paid extraction runs automatically.")
    blocks, specs = {}, {}
    with st.expander("Embed selected report pages and photographs"):
        destinations = []
        defaults = {"Vendor service": "improvements", "Water treatment": "water_reports", "MBCx": "mbcx_report", "Utility results": "utility_analysis", "Improvement / training photo": "improvements"}
        for item in contents:
            if not sources.image_numbers(item):
                continue
            labels = {"Do not embed": "Keep as reference only", "vendor_reports": "Maintenance — vendor service pages",
                      "water_reports": "Water treatment — chemical/service pages", "mbcx_report": "MBCx — commissioning report pages",
                      "utility_analysis": "Monthly scorecards — utility results and charts",
                      "improvements": "Monthly activity — reviewed service pages and photos"}
            slot = st.selectbox("Add " + item.source.filename + " to", ["Do not embed", *sources.PAGE_DESTINATIONS], format_func=labels.get,
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
                st.caption("Use Add prepared pages and tables to this draft below to include these work-order totals and service calls.")
    return tuple(c.source for c in contents), blocks, specs


def _render_section_page_review(profile, content, prefix, field, blocks):
    """Review new page content once, with an explicit include/leave-out action."""
    from app.monthly_report_section_uploads import included_pages

    source = content.source
    p = prefix + "_" + source.id
    _sync_source_fields(source, p, field)
    image_pages = sources.image_numbers(content)
    existing = included_pages(blocks)
    if not image_pages:
        st.info("This file contains extracted text or tables. Its original is saved. Use the section's text/table editor, or the work-order spreadsheet tools, to include that content.")
        with st.expander("Read this file"):
            st.text("\n\n".join(source.page_texts)[:12000] or "No readable text was found.")
        return content
    with st.expander("File details (optional)"):
        st.caption("These are suggested facts from the file. Blank means not established; adding it here does not change its classification.")
        changes = {}
        st.caption("File classification: " + source.classification)
        for attr, label in (("vendor", "Vendor"), ("service_date", "Service/report date (YYYY-MM-DD)"),
                            ("facility", "Source facility"), ("work_order", "Job / work-order number")):
            changes[attr] = st.text_input(label, key=field(p + "_" + attr, getattr(source, attr)))
        source = replace(source, **changes)
    for notice in source.notices:
        st.warning(notice)
    undecided = [n for n in _undecided_pages(content, source) if (source.id, n) not in existing]
    page_key = field(p + "_page", undecided[0] if undecided else image_pages[0])
    pending = st.session_state.pop(p + "_next_page", None)
    if pending in image_pages:
        st.session_state[page_key] = pending
    if st.session_state[page_key] not in image_pages:
        st.session_state[page_key] = image_pages[0]
    page_labels = {n: f"Page {n}" + (" · already in report" if (source.id, n) in existing
                  else " · included" if n in source.selected_pages and page_allowed(source, n)
                  else " · left out" if dict(source.client_page_exclusions).get(n) == page_fingerprint(source, n)
                  else " · needs review") for n in image_pages}
    page = st.selectbox("Page to review", image_pages, key=page_key, format_func=page_labels.get)
    preview_ok = False
    try:
        thumbnail = sources.page_image(profile, content, page, preview=True)
        st.image(thumbnail.data, width=650)
        preview_ok = True
    except (ValueError, OSError) as exc:
        st.error(str(exc))
    with st.expander("Read extracted text"):
        st.text(source.page_texts[page - 1][:12000] or "No native text on this page. Review the image above.")
    if (source.id, page) in existing:
        st.caption("This page is already in the report. Edit its caption or remove it using the included pages below.")
    else:
        captions = dict(source.captions)
        caption_key = field(p + f"_caption_{page}", captions.get(page, f"{source.filename} · page/item {page}"))
        captions[page] = st.text_input("Page caption", key=caption_key)
        source = replace(source, captions=tuple(sorted(captions.items())))
        kind, reason = page_status(source.page_texts[page - 1], unreadable=page in source.needs_vision)
        blocked = kind in ("pricing", "legal", "blank", "signature") or contains_price(captions[page])
        if contains_price(captions[page]):
            reason = "Remove pricing from the caption before including this page."
        (st.warning if blocked else st.caption)(reason)
        st.caption("Include confirms that you checked this page and caption: relevant work, no prices, and no legal-only, blank or signature-only content.")
        keep, omit = st.columns(2)
        action = None
        if keep.button("Include page and continue", key=p + "_keep_page", disabled=blocked or not preview_ok):
            action = "keep"
        if omit.button("Leave page out and continue", key=p + "_omit_page"):
            action = "omit"
        if action:
            selected = set(source.selected_pages)
            reviews, exclusions = dict(source.client_page_reviews), dict(source.client_page_exclusions)
            if action == "keep":
                selected.add(page)
                reviews[page] = page_fingerprint(source, page)
                exclusions.pop(page, None)
            else:
                selected.discard(page)
                reviews.pop(page, None)
                exclusions[page] = page_fingerprint(source, page)
            source = replace(source, selected_pages=tuple(sorted(selected)),
                             client_page_reviews=tuple(sorted(reviews.items())),
                             client_page_exclusions=tuple(sorted(exclusions.items())))
            remaining = [n for n in _undecided_pages(content, source) if (source.id, n) not in existing]
            st.session_state[p + "_next_page"] = next((n for n in remaining if n > page), remaining[0] if remaining else page)
            # The caller persists this source before rerunning, retaining every
            # other section's canonical evidence object unchanged.
            st.session_state[prefix + "_review_rerun"] = True
    st.session_state[p + "_canonical_view"] = source
    return replace(content, source=source)


def render_section_uploads(profile: ReportProfile, period: ReportPeriod, prefix: str, field,
                           destination: str, *, blocks=None, assets=None):
    """Return an addition only on its apply click; callers merge it atomically.

    The existing canonical evidence cache is shared with the optional batch/CMMS
    workspace. Section routing never changes a saved source's classification.
    """
    from app.monthly_report_section_uploads import (
        SECTION_UPLOADS, pending_pages, prepare_section_pages, section_contents, source_destinations,
    )
    if destination not in SECTION_UPLOADS:
        raise ValueError("Unknown report section for uploaded pages.")
    blocks = blocks or {}
    title, upload_label = SECTION_UPLOADS[destination]
    key = prefix + "_evidence"
    local_key = key + "_section_" + destination
    contents = st.session_state.setdefault(key, ())
    bindings = dict(st.session_state.setdefault(key + "_section_routes", {}))
    st.markdown("**" + title + "**")
    st.caption("Choose a file, check its useful pages, then add them here. Existing report content is kept.")
    upload = st.file_uploader(upload_label, type=sorted(s.lstrip(".") for s in sources.SUPPORTED),
                             accept_multiple_files=True, max_upload_size=128, key=local_key + "_upload")
    picked = tuple((u.name, u.getvalue()) for u in (upload or ()))
    signature = _signature([(name, hashlib.sha256(raw).hexdigest()) for name, raw in picked])
    if picked and st.session_state.get(local_key + "_read") != signature:
        before = {c.source.id for c in contents}
        owners = source_destinations(contents, bindings, blocks)
        with st.spinner("Reading files and checking duplicates…"):
            contents, messages = sources.ingest_batch(profile, picked, contents)
        messages = list(messages)
        for content in contents:
            if content.source.id not in before:
                bindings[content.source.id] = destination
        for _, raw in picked:
            identity = hashlib.sha256(raw).hexdigest()
            assigned = owners.get(identity, set())
            if identity in before and not assigned:
                bindings[identity] = destination
            elif assigned and destination not in assigned:
                messages.append("This file already belongs to another report section. Its pages and saved classification were kept there.")
        st.session_state[key] = contents
        st.session_state[key + "_section_routes"] = bindings
        st.session_state[local_key + "_messages"] = tuple(messages)
        st.session_state[local_key + "_read"] = signature
    elif not picked:
        st.session_state.pop(local_key + "_read", None)
    for message in st.session_state.get(local_key + "_messages", ()):
        st.warning(message)
    owners = source_destinations(contents, bindings, blocks)
    unassigned = [c for c in contents if not owners[c.source.id]]
    if unassigned:
        with st.expander("Use a file already saved in this draft"):
            choices = {c.source.id: c for c in unassigned}
            choice_key = field(local_key + "_saved_choice", next(iter(choices)))
            if st.session_state[choice_key] not in choices:
                st.session_state[choice_key] = next(iter(choices))
            chosen = st.selectbox("Saved file", list(choices), format_func=lambda v: choices[v].source.filename, key=choice_key)
            if st.button("Review this file here", key=local_key + "_use_saved"):
                bindings[chosen] = destination
                st.session_state[key + "_section_routes"] = bindings
    scoped = section_contents(contents, destination, bindings, blocks)
    if not scoped:
        return tuple(c.source for c in contents), {}, {}
    choices = {c.source.id: c for c in scoped}
    selected_key = field(local_key + "_selected", next(iter(choices)))
    if st.session_state[selected_key] not in choices:
        st.session_state[selected_key] = next(iter(choices))
    if len(choices) == 1:
        selected = next(iter(choices))
        st.caption("Reviewing " + choices[selected].source.filename)
    else:
        selected = st.selectbox("File to review", list(choices), format_func=lambda v: choices[v].source.filename, key=selected_key)
    revised = _render_section_page_review(profile, choices[selected], local_key, field, blocks)
    contents = tuple(revised if c.source.id == selected else c for c in contents)
    st.session_state[key] = contents
    if st.session_state.pop(local_key + "_review_rerun", False):
        st.rerun()
    scoped = section_contents(contents, destination, bindings, blocks)
    pending = pending_pages(scoped, destination, blocks)
    by_id = {c.source.id: c for c in scoped}
    ready = bool(pending) and all(page_allowed(by_id[identity].source, number) for identity, number in pending)
    if pending:
        st.caption(f"{sum(page_allowed(by_id[identity].source, n) for identity, n in pending)} of {len(pending)} selected new pages checked.")
    else:
        st.caption("No new pages selected. Previously added pages remain in your report.")
    additions = {}
    if st.button("Add reviewed pages", key=local_key + "_apply", disabled=not ready, type="primary"):
        try:
            with st.spinner("Adding the reviewed pages…"):
                additions = prepare_section_pages(profile, scoped, destination, blocks, assets)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            st.caption("Your existing report is unchanged. The selected files and reviews are retained for another attempt.")
    return tuple(c.source for c in contents), additions, {}


@st.fragment(run_every=1)
def _section_read_progress(local_key):
    job = st.session_state.get(local_key + "_job")
    if job and job["future"].done():
        st.rerun()
    if job:
        st.info("Reading uploaded files and preparing this section…")


def render_structured_uploads(profile, period, prefix, field, destination, *, blocks=None, assets=None):
    """Automatically draft new evidence once; retain subsequent human edits on reruns."""
    from app import monthly_report_structured_uploads as structured
    from app import monthly_report_ai as ai
    from app.receipt_jobs import start_receipt

    if destination not in {"activity_summary", "capital_renewal", "proposals"}:
        raise ValueError("Unknown upload-first section.")
    blocks = blocks or {}
    evidence_key = prefix + "_evidence"
    local_key = evidence_key + "_structured_" + destination
    contents = st.session_state.setdefault(evidence_key, ())
    labels = {"activity_summary": "Upload activity reports and supporting files", "capital_renewal": "Upload capital renewal lists or contract documents", "proposals": "Upload pending and declined quotes"}
    st.caption("Upload your files first. Useful information is drafted below for you to edit. Original quotes and prices are excluded from the report.")
    uploaded = st.file_uploader(labels[destination], type=sorted(s.lstrip(".") for s in sources.SUPPORTED),
                                accept_multiple_files=True, max_upload_size=128, key=local_key + "_upload")
    additions = {}
    def remember(block, current_sources):
        # The async progress fragment may request a full rerun before this page
        # reaches its normal final draft commit. Persist the native first pass
        # *before* recording a processed-source flag or starting a reader.
        draft_key = prefix + "_draft"
        draft = st.session_state.get(draft_key)
        if draft is not None:
            current = {part.key: part for part in draft.blocks}
            current[block.key] = block
            st.session_state[draft_key] = replace(
                draft, blocks=tuple(current.values()),
                sources=tuple(content.source for content in current_sources))

    def complete_finished_job():
        nonlocal contents
        job = st.session_state.get(local_key + "_job")
        if not job or not job["future"].done():
            return
        st.session_state.pop(local_key + "_job", None)
        try:
            value = job["future"].result()
            current = additions.get(destination, blocks.get(destination))
            if current is not None and current.fingerprint != job.get("baseline"):
                st.session_state[local_key + "_pending"] = (job, value)
                raise ValueError("New source suggestions are ready. Your edits were kept; add the suggestions below when ready.")
            result, pages = structured.reader_update(job["contents"], destination, value, current)
            additions[destination] = result
            remember(result, contents)
            # Only a validated, successfully applied result may enter the
            # reusable cache; a malformed reply must not poison Retry.
            ai.save_cache(profile, "section_upload", job["digest"], value)
            st.session_state[local_key + "_messages"] = tuple(value.get("notices", ()))
            st.session_state[local_key + "_completed_ids"] = tuple(
                set(st.session_state.get(local_key + "_completed_ids", ()))
                | {content.source.id for content in job["contents"]})
            if destination == "activity_summary" and pages:
                selected = []
                for content in job["contents"]:
                    source = content.source
                    from app.monthly_report_section_uploads import included_pages
                    present = included_pages(blocks)
                    numbers = tuple(n for n in sorted(
                        set(pages.get(source.id, ())) & set(sources.image_numbers(content)))
                        if (source.id, n) not in present)
                    source = replace(source, selected_pages=numbers)
                    source = replace(source, client_page_reviews=tuple(
                        (n, page_fingerprint(source, n)) for n in numbers))
                    selected.append(replace(content, source=source))
                prepared = sources.prepare_pages(
                    profile, tuple(selected),
                    tuple((content.source.id, "improvements") for content in selected
                          if content.source.selected_pages))
                additions.update({block.key: block for block in prepared})
                changed = {content.source.id: content for content in selected}
                contents = tuple(changed.get(content.source.id, content) for content in contents)
                st.session_state[evidence_key] = contents
                remember(result, contents)
            st.session_state.pop(local_key + "_error", None)
        except ValueError as exc:
            st.session_state[local_key + "_error"] = str(exc)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Monthly section reader failed")
            st.session_state[local_key + "_error"] = (
                "The document reader could not finish. Your uploaded text is kept; "
                "retry reading or edit the section below.")

    complete_finished_job()
    picked = tuple((u.name, u.getvalue()) for u in (uploaded or ()))
    signature = _signature([(name, hashlib.sha256(raw).hexdigest()) for name, raw in picked])
    if picked and st.session_state.get(local_key + "_read") != signature and local_key + "_job" not in st.session_state:
        ids = {hashlib.sha256(raw).hexdigest() for _, raw in picked}
        contents, messages = sources.ingest_batch(profile, picked, contents)
        st.session_state[evidence_key] = contents
        scoped = tuple(c for c in contents if c.source.id in ids)
        st.session_state[local_key + "_messages"] = messages
        if ids <= set(st.session_state.get(local_key + "_completed_ids", ())):
            st.session_state[local_key + "_read"] = signature
            return tuple(c.source for c in contents), additions, {}
        processed = set(st.session_state.get(local_key + "_native_ids", ()))
        fresh = tuple(c for c in scoped if c.source.id not in processed)
        additions[destination] = structured.native_update(
            fresh, destination, additions.get(destination, blocks.get(destination)))
        remember(additions[destination], contents)
        st.session_state[local_key + "_native_ids"] = tuple(processed | {c.source.id for c in fresh})
        scoped = fresh or scoped
        digest = ai.digest(("section-upload-v3", destination, sorted(c.source.id for c in scoped)))
        try:
            if not ai.ANTHROPIC_API_KEY:
                # The built-in extractive pass requires no network, image
                # rendering or allowance. Keep it and allow normal editing.
                st.session_state.pop(local_key + "_error", None)
                st.session_state[local_key + "_read"] = signature
                st.caption("Automatic reading is off. Any readable text was added below for review; edit the summary directly or use Copilot.")
                return tuple(content.source for content in contents), additions, {}
            force = st.session_state.pop(local_key + "_force_network", False)
            cached = None if force else ai.cached(profile, "section_upload", digest)
            if cached is not None:
                # Keep one completion path, including page handling and validation.
                from concurrent.futures import Future
                future = Future()
                future.set_result(cached)
            else:
                def prepare():
                    payloads = structured.reader_batches(profile, scoped, destination)
                    for _ in payloads:
                        ai.reserve_call(profile, period)
                    return payloads
                future = start_receipt(prepare, structured.read_batches)
                if future is None:
                    raise ValueError("Other document readings are running. Your extracted text is kept; retry this upload when they finish.")
            st.session_state[local_key + "_job"] = {"future": future, "contents": scoped, "digest": digest, "baseline": additions[destination].fingerprint}
        except (ValueError, OSError, RuntimeError) as exc:
            st.session_state[local_key + "_error"] = str(exc)
        st.session_state[local_key + "_read"] = signature
    for message in st.session_state.get(local_key + "_messages", ()):
        st.warning(message)
    pending = st.session_state.get(local_key + "_pending")
    if pending and st.button("Add new source suggestions to my edits", key=local_key + "_accept_suggestions"):
        from concurrent.futures import Future
        pending_job, value = st.session_state.pop(local_key + "_pending")
        future = Future()
        future.set_result(value)
        current = blocks.get(destination)
        st.session_state[local_key + "_job"] = dict(pending_job, future=future, baseline=current.fingerprint if current else None)
        st.rerun()
    # Process immediately finished cached/failed jobs in this same full-page
    # pass. Calling st.rerun in an inline progress fragment here would abort
    # before guided.py commits the native extractive first pass.
    complete_finished_job()
    if local_key + "_error" in st.session_state:
        st.warning(st.session_state[local_key + "_error"])
        if st.button("Retry reading uploaded files", key=local_key + "_retry"):
            st.session_state.pop(local_key + "_read", None)
            st.session_state[local_key + "_force_network"] = True
            st.rerun()
    if local_key + "_job" in st.session_state:
        _section_read_progress(local_key)
    return tuple(c.source for c in contents), additions, {}
