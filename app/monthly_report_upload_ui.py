"""Monthly evidence review and explicit page/CMMS mapping controls."""

from dataclasses import asdict, replace
import hashlib
import json

import streamlit as st

from app import monthly_report_sources as sources
from app.monthly_report_cmms import CMMSMapping, map_cmms, month_window
from app.monthly_report_model import ReportPeriod, ReportProfile
from app.monthly_report_content_policy import page_status, page_fingerprint, page_allowed, contains_price
from app.monthly_report_upload_guidance import evidence_limits_summary, evidence_upload_options


def _remember_manual_page_route(key, identity, control):
    """Only a native operator change records a durable route override."""
    routes = dict(st.session_state.get(key, {}))
    routes[identity] = st.session_state[control]
    st.session_state[key] = routes


# Exact, explicit page-review receipts permit single-action append only for
# supported technical-page sections. Other evidence keeps its existing route.
AUTO_INCLUDE_PAGE_DESTINATIONS = frozenset({"water_reports", "mbcx_report", "utility_analysis"})


def _signature(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _retry_section_upload(local_key, signature):
    """Retire only the selection that displayed this retry action."""
    if st.session_state.get(local_key + "_read") == signature:
        st.session_state.pop(local_key + "_read", None)


def _undecided_pages(content, source):
    exclusions = dict(source.client_page_exclusions)
    return [n for n in sources.image_numbers(content)
            if not (n in source.selected_pages and page_allowed(source, n))
            and exclusions.get(n) != page_fingerprint(source, n)]


def _sync_source_fields(source, prefix, field, *, caption_defaults=None):
    """Refresh stale widgets when another section edited the canonical source.

    Only external changes are copied. A widget's pending input on this rerun is
    preserved when the canonical source still matches this view's last render.
    """
    if caption_defaults is not None:
        defaults_key = prefix + "_inherited_caption_view"
        previous_defaults = st.session_state.get(defaults_key, {})
        explicit_captions = dict(source.captions)
        for number, caption in caption_defaults.items():
            if (number not in explicit_captions and number in previous_defaults
                    and previous_defaults[number] != caption):
                key = field(prefix + f"_caption_{number}", caption)
                # An unchanged displayed default follows the actual attached
                # page. A different native value is a delivered operator edit,
                # including a deliberate blank, and must be consumed normally.
                if st.session_state.get(key) == previous_defaults[number]:
                    st.session_state[key] = caption
        st.session_state[defaults_key] = dict(caption_defaults)
    previous = st.session_state.get(prefix + "_canonical_view")
    if previous is None or previous == source:
        return
    attributes = ("classification", "vendor", "work_order",
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
            value = after.get(number, (caption_defaults or {}).get(number, f"{source.filename} · page/item {number}"))
            st.session_state[field(prefix + f"_caption_{number}", value)] = value
            active = st.session_state.get(prefix + "_caption_widget_keys", {}).get(number)
            if active is not None:
                st.session_state[active] = value

def _remember_delivered_source_edit(prefix, before, after):
    """Record only an edit captured by this full render, never a saved waiver."""
    if before == after or not st.session_state.get("_monthly_source_details_managed"):
        return
    changes = st.session_state.setdefault(prefix + "_source_native_changes", {})
    previous = changes.get(before.id)
    changes[before.id] = (previous[0] if previous and previous[1] == before else before, after)


def _page_widget_source(source, page_prefix, editor_prefix):
    """Keep delivered widget identity for one exact same-render metadata edit."""
    change = st.session_state.get(editor_prefix + "_source_native_changes", {}).get(source.id)
    previous = st.session_state.get(page_prefix + "_canonical_view")
    if change and change[1] == source and change[0] == previous:
        return change[0]
    return source


def _acknowledge_managed_page_edit(before, after, editor_prefix):
    """Acknowledge only this render's exact caption/page-decision mutation."""
    if not st.session_state.get("_monthly_source_details_managed") or before == after:
        return
    allowed = replace(before, captions=after.captions, selected_pages=after.selected_pages,
                      client_page_reviews=after.client_page_reviews,
                      client_page_exclusions=after.client_page_exclusions)
    forms = st.session_state.get("_monthly_source_detail_forms")
    rendered = forms.get(before.id) if isinstance(forms, dict) else None
    key = editor_prefix + "_evidence_" + before.id + "_source_details_baseline"
    if (allowed == after and rendered is not None and rendered.fingerprint == before.fingerprint
            and st.session_state.get(key) == before.fingerprint):
        st.session_state[key] = after.fingerprint
        forms[before.id] = after


def render_source_details(source, profile, prefix, field, *, applied_caption="Corrected details applied to this draft.",
                          compact_problems=(), artwork_keys=(), manager_owner=False, source_preview=None):
    """One explicit date/site correction form for native text and image sources.

    Pending form values are separate from canonical evidence. Opening the form
    or editing a field cannot approve or silently change source metadata.
    """
    from app.monthly_report_source_details import (
        KEEP_FACILITY, correct_source_details, facility_choice, source_date,
    )
    from app.monthly_report_source_scope import (
        CONTRACT_ARTWORK, MULTIPLE_FACILITIES, reviewed_scope, source_review,
    )
    p = prefix + "_source_details"
    # A restored source can be reviewed both by its section and by the saved-
    # source panel. One canonical form per source prevents duplicate widget keys
    # and conflicting submissions within a single guided render. Standalone
    # review widgets do not install this optional page-scoped registry.
    rendered = st.session_state.get("_monthly_source_detail_forms")
    if st.session_state.get("_monthly_source_details_managed") and not manager_owner:
        return rendered.get(source.id, source) if isinstance(rendered, dict) else source
    if isinstance(rendered, dict) and source.id in rendered:
        return rendered[source.id]
    with st.container(key="source_detail_editor_" + p):
        # The guided renderer resets this set once per full page render. A source
        # can be reachable through both writing and page review; give its first
        # resolver one unique local anchor rather than duplicate heading IDs.
        anchors = st.session_state.setdefault("_monthly_source_detail_anchors", set())
        if source.id not in anchors:
            from html import escape
            anchor = "source-details-" + escape(source.id, quote=True)
            st.markdown(''.join('<span id="' + anchor + suffix + '"></span>'
                                for suffix in ("", "--site", "--date")), unsafe_allow_html=True)
            anchors.add(source.id)
        baseline = source.fingerprint
        previous = st.session_state.get(p + "_baseline")
        changed_elsewhere = previous is not None and previous != baseline
        initial_date = source_date(source.service_date)
        initial_facility = facility_choice(source, profile)
        date_key = field(p + "_date", initial_date)
        site_key = field(p + "_site", initial_facility)
        stored_scope = source_review(source)
        initial_sites = (list(stored_scope.get("facilities", ())) if initial_facility == MULTIPLE_FACILITIES
                         else [initial_facility] if initial_facility else [])
        # Let the native widget own its first initialization. Pre-seeding
        # its state as well as its default produces a duplicate-default warning.
        sites_key = p + "_sites"
        mirrored_sites = st.session_state.get("report_draft_mirror", {}).get(sites_key, initial_sites)
        pending_sites = st.session_state.get(sites_key, mirrored_sites)
        if changed_elsewhere:
            # Never apply a stale form over another source view's newer correction.
            st.session_state[date_key] = initial_date
            st.session_state[site_key] = initial_facility
            st.session_state[sites_key] = initial_sites
            pending_sites = initial_sites
        # Native calendar limits extend ten years on either side. Extreme
        # years overflow; early years also produce non-four-digit wire dates.
        # Keep the exact value editable without guessing or clamping a date.
        pending_date = st.session_state[date_key]
        text_date = pending_date is not None and not 1010 <= pending_date.year <= 9989
        text_date_key = date_key + "_text"
        text_date_default = (source.service_date if pending_date == initial_date
                             else pending_date.isoformat() if pending_date else "")
        if text_date and changed_elsewhere:
            st.session_state[text_date_key] = text_date_default
        st.session_state[p + "_baseline"] = baseline
        missing = (initial_date is None or initial_facility in ("", KEEP_FACILITY)
                   or bool(source.scope_review and reviewed_scope(source, profile) is None))
        label = ("Correct source details · " + source.filename + " · " + "; ".join(compact_problems)
                 if compact_problems else "Date and facility · " + source.filename)
        with st.expander(label, expanded=missing and not compact_problems):
            # Reserve the preview subtree even while closed; revealing an
            # exact source page must not relocate buffered form inputs.
            with st.container(key=p + "_correction_page"):
                if source_preview is not None:
                    source_preview()
            if changed_elsewhere:
                st.info("This source was corrected elsewhere. Check the updated details before saving.")
            if source.service_date and initial_date is None:
                st.warning("The source date could not be read: " + source.service_date)
            st.caption("Use the date and site shown in the source. Leave unknown details blank; the filename does not establish them.")
            if source.selected_pages:
                st.caption("Selected source pages/items: " + ", ".join(map(str, source.selected_pages)))
            sites = {site.key: site.title for site in profile.facilities}
            options = ["", *sites]
            if initial_facility == KEEP_FACILITY:
                options.insert(1, KEEP_FACILITY)
            if initial_facility == MULTIPLE_FACILITIES and len(sites) == 1:
                options.append(MULTIPLE_FACILITIES)
            if artwork_keys:
                options.append(CONTRACT_ARTWORK)
            elif initial_facility == CONTRACT_ARTWORK:
                # A source moved into operational content cannot retain the shared
                # artwork exception; show its current choice but reject resubmission.
                options.append(CONTRACT_ARTWORK)
            if st.session_state[site_key] not in options:
                st.session_state[site_key] = initial_facility
            labels = {"": "Not established", KEEP_FACILITY: "Keep unresolved: " + source.facility,
                      MULTIPLE_FACILITIES: "Review previously selected sites",
                      CONTRACT_ARTWORK: "Shared contract artwork — no site activity", **sites}
            with st.form(p + "_form"):
                # Match the native first-mount default to the current form value.
                # Python session state alone leaves saved dates visibly blank in
                # the browser; a delivered deliberate clear remains None here.
                if text_date:
                    chosen_date_text = st.text_input("Source date (YYYY-MM-DD)",
                        value=text_date_default, key=field(text_date_key, text_date_default),
                        help="Enter a date as YYYY-MM-DD, or clear it if unknown.")
                else:
                    chosen_date = st.date_input("Source date", value=st.session_state[date_key], key=date_key,
                                                format="YYYY-MM-DD")
                chosen_sites = ()
                if len(sites) > 1:
                    multi_options = [v for v in options if v]
                    # Keep unresolved prior site choices visible without silently
                    # converting them to the report's first selected facility.
                    multi_options.extend(v for v in pending_sites if v not in multi_options)
                    # The native first/late mount must receive the current pending
                    # value as its default, including a deliberately cleared list.
                    # An external correction instead uses native set_value for
                    # this render; the following render retains its new default.
                    chosen_sites = st.multiselect("Source sites", multi_options,
                                                  default=None if changed_elsewhere else pending_sites, key=sites_key,
                                                  format_func=lambda v: labels.get(v, "Outside this report: " + v))
                    # Register ownership after native initialization; field()'s
                    # setdefault must not overwrite delivered or cleared values.
                    field(sites_key, chosen_sites)
                    chosen_facility = (chosen_sites[0] if len(chosen_sites) == 1
                                       else MULTIPLE_FACILITIES if chosen_sites else "")
                else:
                    chosen_facility = st.selectbox("Source facility", options, key=site_key,
                                                  format_func=labels.get)
                submitted = st.form_submit_button("Use these source details")
            if submitted and not changed_elsewhere:
                try:
                    if text_date:
                        chosen_date = source_date(chosen_date_text.strip())
                        if chosen_date_text.strip() and chosen_date is None:
                            raise ValueError("Enter a valid source date as YYYY-MM-DD, or leave it blank.")
                    source = correct_source_details(source, profile, chosen_date, chosen_facility,
                        chosen_facilities=chosen_sites if chosen_facility == MULTIPLE_FACILITIES else (),
                        artwork_keys=artwork_keys)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    if text_date:
                        # The calendar was not mounted in this render. Seed its
                        # next mount from this explicit correction, not old input.
                        st.session_state[date_key] = chosen_date
                    st.session_state[p + "_baseline"] = source.fingerprint
                    st.caption(applied_caption)
    if isinstance(rendered, dict):
        rendered[source.id] = source
    return source


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
    finish_date_means_completed = False
    if not values["status"]:
        st.caption("No completion status column is mapped. Choose the rule supported by this export.")
        rule_key = prefix + "_finish_rule_" + _signature((source.fingerprint, values["finished"]))[:16]
        finish_date_means_completed = st.checkbox(
            "A valid finish date means completed work in this export",
            key=field(rule_key, False))
    pm = selected_values("Category values that mean PM", choices(values["category"]), "_pm") if values["category"] else []
    cm = selected_values("Category values that mean CM", choices(values["category"]), "_cm") if values["category"] else []
    date_format = st.selectbox("Date format", ["ISO", "MM/DD/YYYY", "DD/MM/YYYY"], key=field(prefix + "_date_format", "ISO"))
    st.caption("Only confirm complete coverage where the export contains all completed work. Unconfirmed months/facilities remain blank in the twelve-month grid.")
    months = st.multiselect("Months with complete export coverage", month_window(period), key=field(prefix + "_months", []))
    facilities = st.multiselect("Facilities covered completely in those months", [f.key for f in profile.facilities],
                                format_func=lambda v: next(f.title for f in profile.facilities if f.key == v), key=field(prefix + "_coverage", []))
    mapping = CMMSMapping(**values, assigned_facility=assigned, completed_statuses=tuple(statuses), pm_values=tuple(pm),
                          cm_values=tuple(cm), date_format=date_format, complete_months=tuple(months), complete_facilities=tuple(facilities),
                          finish_date_means_completed=finish_date_means_completed)
    signature = _signature((source.fingerprint, asdict(mapping), period.key))
    result_key = prefix + "_result"
    result = st.session_state.get(result_key)
    if result and result[0] != signature:
        st.session_state.pop(result_key, None)
        result = None
    st.caption("Applying uses the columns and complete-coverage selections shown above. Months without confirmed coverage stay blank.")
    if st.button("Use these spreadsheet columns", key=prefix + "_apply"):
        try:
            index = content.tables.index(table) + 1
            mapped = map_cmms(table, mapping, profile, period, sources.source_reference(source, index),
                              scope_source=source)
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


def render_uploads(profile: ReportProfile, period: ReportPeriod, prefix: str, field, *, retain_accepted=False,
                   attached_blocks=None, included_source_ids=(), show_intake=True, selected_source_id=None,
                   visible=True, scope_draft=None, shown_source_page=None, section_page_owners=()):
    st.caption("Read source files, check their pages, or match spreadsheet columns.")
    st.caption("PDF, Word, Excel, photos and email files. Uploaded emails are read, not sent.")
    with st.expander("File formats and limits"):
        st.caption("Supported: PDF, DOCX, XLSX, CSV, EML, MSG, TXT, and image files including HEIC.")
        st.caption(evidence_limits_summary())
    key = prefix + "_evidence"
    decision_key = key + "_page_decision"
    # Only this render's submitted native action can review an attached page.
    st.session_state.pop(decision_key, None)
    contents = st.session_state.setdefault(key, ())
    accepted_key = key + "_accepted_batch"
    pending_key = key + "_pending_acceptance"
    failure_key = key + "_accepted_failure"
    retired_key = key + "_retired_contributions"
    accepted = st.session_state.get(accepted_key) if retain_accepted else None
    if show_intake:
        upload = st.file_uploader("Monthly source files", type=sorted(s.lstrip(".") for s in sources.SUPPORTED),
                                 accept_multiple_files=True, key=prefix + "_source_upload", **evidence_upload_options())
        picked = tuple((u.name, u.getvalue()) for u in (upload or ()))
        selection = _signature([(name, hashlib.sha256(raw).hexdigest()) for name, raw in picked])
        if st.button("Read monthly files", disabled=not upload, key=prefix + "_read_sources"):
            with st.spinner("Reading local files and checking duplicates…"):
                contents, messages = sources.ingest_batch(profile, picked, contents)
            st.session_state[key] = contents
            st.session_state[key + "_messages"] = messages
            st.session_state[key + "_attempted_selection"] = selection
        if picked and st.session_state.get(key + "_attempted_selection") == selection:
            from app.monthly_report_source_recovery_ui import render_failed_file_retries
            retried = render_failed_file_retries(profile, period,
                st.session_state.get(prefix + "_revision", 0), key, picked, contents,
                messages=st.session_state.get(key + "_messages", ()))
            if retried is not None:
                contents, messages, _ = retried
                st.session_state[key] = contents
                st.session_state[key + "_messages"] = messages
    for message in st.session_state.get(key + "_messages", ()):
        st.warning(message)
    if not contents:
        if accepted:
            st.session_state[pending_key] = True
            st.info("No source files are selected. This report keeps its last added selection until you explicitly remove it.")
            if st.button("Remove last added pages and tables from this report",
                         key=key + "_remove_accepted_" + accepted[0][:16]):
                from app.monthly_report_source_retirement import record_retired_contributions
                st.session_state[retired_key] = record_retired_contributions(
                    st.session_state.get(retired_key, {}), accepted[1], {})
                for marker in (accepted_key, pending_key, failure_key):
                    st.session_state.pop(marker, None)
                return (), {}, {}
            return tuple(accepted[3]), dict(accepted[1]), dict(accepted[2])
        for marker in (accepted_key, pending_key, failure_key):
            st.session_state.pop(marker, None)
        st.info("Add source files when available, or continue with library content and entered text.")
        with st.expander("Synthetic CMMS column example"):
            st.code("Work order,Finish date,Facility,Type,Status,Description\nDEMO-001,2026-09-02,Demo North,PM,Closed,Inspected demonstration unit", language="text")
            st.caption("Map your export's actual columns and category/status values after reading it. This example is synthetic and does not establish any report counts.")
        return (), {}, {}
    by_id = {c.source.id: c for c in contents}
    selection_key = field(key + "_selected", contents[0].source.id)
    if st.session_state[selection_key] not in by_id:
        st.session_state[selection_key] = contents[0].source.id
    if selected_source_id is not None:
        if selected_source_id not in by_id:
            return tuple(content.source for content in contents), {}, {}
        selected = selected_source_id
    elif len(by_id) == 1:
        selected = next(iter(by_id))
        st.write("Reviewing " + by_id[selected].source.filename)
    else:
        selected = st.selectbox("File to review", list(by_id), format_func=lambda v: by_id[v].source.filename, key=selection_key)
    content, source = by_id[selected], by_id[selected].source
    p = key + "_" + selected
    # An absent source caption inherits the already attached page's caption.
    # Opening Change must not materialize a new source caption or invalidate
    # its existing page review merely to display an editable default.
    caption_defaults = {}
    if attached_blocks is not None:
        from app.monthly_report_page_controls import page_asset_index
        for number in sources.image_numbers(content):
            candidates = []
            for block in attached_blocks.values():
                index = page_asset_index(block, source.id, number) if block.source != "Omit" else None
                if index is not None:
                    candidates.append(block.asset_captions[index] if index < len(block.asset_captions) else "")
            if len(candidates) == 1:
                caption_defaults[number] = candidates[0]
    _sync_source_fields(source, p, field, caption_defaults=caption_defaults)
    from app.monthly_report_source_scope import artwork_scope_keys, preserve_descriptive_scope
    artwork_keys = (artwork_scope_keys(scope_draft, source.id)
                    if scope_draft is not None and scope_draft.profile == profile
                    and scope_draft.period == period else ())
    source = render_source_details(source, profile, p, field, artwork_keys=artwork_keys,
        applied_caption=("Corrected details are kept in this file selection. Add the selection below to update the report."
                         if retain_accepted else "Corrected details applied to this draft."))
    pending = st.session_state.pop(p + "_page_action", None)
    if pending:
        st.session_state[p + "_pages"] = pending[0]
        st.session_state[p + "_page"] = pending[1]
    with st.expander("Choose pages for the client report", expanded=True):
        with st.expander("Edit vendor, date and work details"):
            st.caption("Suggestions come from readable labels and keywords. Review or correct them; blank means not established.")
            classification = st.selectbox("Classification", sources.CLASSIFICATIONS, key=field(p + "_classification", source.classification))
            changes = {"classification": classification}
            for attr, label in (("vendor", "Vendor"), ("work_order", "Job / work-order number")):
                changes[attr] = st.text_input(label, key=field(p + "_" + attr, getattr(source, attr)))
            st.caption("Profile facilities and aliases: " + "; ".join(f.title + (" (" + ", ".join(f.aliases) + ")" if f.aliases else "") for f in profile.facilities))
            tags = st.text_input("Equipment tags (comma-separated)", key=field(p + "_tags", ", ".join(source.tags)))
            changes["tags"] = tuple(v.strip() for v in tags.split(",") if v.strip())
            for attr, label in (("actions", "Actions"), ("findings", "Findings"), ("recommendations", "Recommendations"),
                                ("follow_ups", "Follow-ups"), ("out_of_limit", "Out-of-limit readings")):
                changes[attr] = st.text_area(label, key=field(p + "_" + attr, getattr(source, attr)), height=70)
        for notice in source.notices:
            st.warning(notice)
        delegated_pages = selected in section_page_owners
        if delegated_pages:
            from app.monthly_report_page_context_ui import open_report_page_task
            st.caption("Include, exclude, caption and order this file's pages in Water treatment.")
            st.button("Open report pages", key=p + "_open_section_pages",
                      on_click=open_report_page_task, args=(prefix, source.id))
            pages, selected_pages = [], source.selected_pages
        else:
            pages = list(range(1, len(source.page_texts) + 1))
            selected_pages = st.multiselect("Included pages / extracted items", pages, key=field(p + "_pages", list(source.selected_pages)),
                                           help="Readable technical pages are suggested. Pages with prices, legal terms, no useful content or unreadable images are not automatically included. Inspect image pages to decide. Originals remain saved.")
        changes["selected_pages"] = tuple(selected_pages)
        captions = dict(source.captions)
        preview_ok = False
        if pages:
            page = st.selectbox("Preview page / item", pages, key=field(p + "_page", pages[0]),
                                format_func=lambda n: f"Page / item {n} · " + page_status(source.page_texts[n-1], unreadable=n in source.needs_vision)[0].replace("technical", "check before including").replace("review", "needs visual review"))
            if scope_draft is not None:
                from app.monthly_report_manager_page_navigation import page_markup
                from app.monthly_report_guided import _rich_text_scope
                st.markdown(page_markup(st.session_state,prefix,source,page,p + "_page",
                    _rich_text_scope(prefix),source_review=True), unsafe_allow_html=True)
            st.caption(f"Page {page} of {len(pages)}. Check the page itself before including it.")
            with st.expander("Read extracted text"):
                st.text(source.page_texts[page-1][:12000] or "No native text on this page/item.")
            if page in sources.image_numbers(content):
                with st.container(key=p + "_source_image"):
                    if shown_source_page == (source.id, source.sha256, page):
                        preview_ok = True
                    elif visible:
                        try:
                            thumbnail = sources.page_image(profile, content, page, preview=True)
                            from app.monthly_report_source_preview import source_thumbnail_uri
                            st.image(source_thumbnail_uri(thumbnail), width=650)
                            preview_ok = True
                        except (ValueError, OSError) as exc:
                            st.error(str(exc))
                default_caption = captions.get(page, caption_defaults.get(page, f"{source.filename} · page/item {page}"))
                caption = st.text_input("Page caption", key=field(p + f"_caption_{page}", default_caption))
                if scope_draft is not None:
                    from app.monthly_report_manager_page_navigation import page_markup
                    from app.monthly_report_guided import _rich_text_scope
                    st.markdown(page_markup(st.session_state, prefix, source, page,
                        p + f"_caption_{page}", _rich_text_scope(prefix)), unsafe_allow_html=True)
                # Viewing a generated/inherited default is not a caption edit.
                if page in captions or caption != default_caption:
                    captions[page] = caption
        changes["captions"] = tuple(sorted(captions.items()))
        updated_source = preserve_descriptive_scope(source, replace(source, **changes), profile)
        _remember_delivered_source_edit(prefix, source, updated_source)
        source = updated_source
        if pages and page in sources.image_numbers(content):
            kind, reason = page_status(source.page_texts[page-1], unreadable=page in source.needs_vision)
            blocked_content = kind in ("pricing", "legal", "blank", "signature")
            priced_caption = contains_price(caption)
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
            if len(sources.image_numbers(content)) > 1:
                st.caption("After each decision, the next unreviewed page opens.")
            keep, omit, advance = st.columns(3)
            action = None
            occurrence_scope = tuple((block.key, tuple(item.key for item in block.asset_instances))
                for block in (attached_blocks or {}).values())
            action_scope = _signature((source.id, source.sha256, page, occurrence_scope))[:16]
            if keep.button("Include page", key=p + "_keep_page_" + action_scope, disabled=blocked or not preview_ok):
                action = "keep"
            if omit.button("Exclude page", key=p + "_omit_page_" + action_scope):
                action = "omit"
            if advance.button("Next page needing review", key=p + "_next_page", disabled=not any(n != page for n in left)):
                action = "next"
            if action:
                chosen = set(source.selected_pages)
                exclusions = dict(source.client_page_exclusions)
                if action == "keep":
                    if page not in dict(source.captions):
                        # Include confirms the caption shown, including one
                        # inherited from the attached page; record it so the
                        # page review and its attached occurrence agree.
                        source = replace(source, captions=tuple(sorted({**dict(source.captions), page: caption}.items())))
                        fingerprint = page_fingerprint(source, page)
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
                if not retain_accepted and action in {"keep", "omit"}:
                    st.session_state[decision_key] = {
                        "source": source.id, "fingerprint": source.fingerprint, "page": page,
                        "action": action,
                        "blocks": tuple((block.key, block.fingerprint)
                                        for block in (attached_blocks or {}).values()),
                    }
                remaining = [n for n in _undecided_pages(content, source) if n != page]
                next_page = next((n for n in remaining if n > page), remaining[0] if remaining else page)
                by_id[selected] = replace(content, source=source)
                st.session_state[key] = tuple(by_id.values())
                st.session_state[p + "_canonical_view"] = source
                st.session_state[p + "_source_details_baseline"] = source.fingerprint
                forms = st.session_state.get("_monthly_source_detail_forms")
                if isinstance(forms, dict):
                    forms[source.id] = source
                # Apply widget changes before instantiation on the next rerun.
                st.session_state[p + "_page_action"] = (list(source.selected_pages), next_page)
                if retain_accepted:
                    st.rerun()
                # The guided caller commits delivered fields and these source
                # changes into one draft before retiring the page controls.
                st.session_state[prefix + "_period_editor_refresh"] = True
            if not left:
                st.success("Every page has been checked. Choose its destination below, then add it to the report." if checked else "Every page has been checked and left out. The original file is still saved.")
            st.caption("Leaving a page out keeps the original file. Use the page selector to revisit any page.")
        by_id[selected] = replace(content, source=source)
        contents = tuple(by_id.values())
        st.session_state[key] = contents
        st.session_state[p + "_canonical_view"] = source
        # These changes were delivered through this same source editor after
        # its details form was rendered. Its next form submit compares against
        # this committed view; a separate source edit still fails the guard.
        st.session_state[p + "_source_details_baseline"] = source.fingerprint
        # Later section views reuse this render's one metadata form. They must
        # receive the source after native captions/selections were captured,
        # rather than restore the form's earlier pre-edit source snapshot.
        forms = st.session_state.get("_monthly_source_detail_forms")
        if isinstance(forms, dict):
            forms[source.id] = source
        source_in_use = not retain_accepted and selected in included_source_ids
        if st.button("Remove source from this selection" if retain_accepted else "Remove source from this draft", key=p + "_remove",
                     disabled=source_in_use,
                     help="Remove the linked report content first. Its original source is still needed." if source_in_use else None):
            st.session_state[key] = tuple(c for c in contents if c.source.id != selected)
            for marker in tuple(st.session_state):
                if marker.startswith(key + "_structured_") and marker.endswith("_context"):
                    removed_key = marker.removesuffix("_context") + "_removed_selection_ids"
                    st.session_state[removed_key] = tuple(set(st.session_state.get(removed_key, ())) | {selected})
            for marker in tuple(st.session_state):
                if marker.startswith(key + "_structured_") and marker.endswith(("_native_ids", "_completed_ids")):
                    st.session_state[marker] = tuple(identity for identity in st.session_state[marker]
                                                     if identity != selected)
            st.rerun()
    st.caption(f"{len(contents)} sources. {sum(len(c.source.selected_pages) for c in contents)} selected pages/items. "
               f"{sum(len(set(c.source.needs_vision) & set(c.source.selected_pages)) for c in contents)} selected pages need OCR/vision; no paid extraction runs automatically.")
    blocks, specs = {}, {}
    # Keep the existing optional, source-level override. Without an explicit
    # override the *individual page heading* may route a mixed PDF to more than
    # one section; review, omissions and actual existing ownership still win.
    from app.monthly_report_auto_page_routing import batch_destinations, route_pages
    from app.monthly_report_section_uploads import included_pages
    from collections import defaultdict
    destinations = []
    defaults = {"Vendor service": "improvements", "Water treatment": "water_reports",
                "MBCx": "mbcx_report", "Utility results": "utility_analysis",
                "Improvement / training photo": "improvements"}
    labels = {"Do not embed": "Keep as reference only",
              "vendor_reports": "Maintenance — ENFRA onsite work only",
              "water_reports": "Water treatment — chemical/service pages",
              "mbcx_report": "MBCx — commissioning report pages",
              "utility_analysis": "Monthly scorecards — utility results and charts",
              "improvements": "Monthly activity — vendor service reports and photos"}
    manual_key = key + "_manual_page_routes"
    manual = dict(st.session_state.get(manual_key, {}))
    route_controls = []
    # A source's destination is delivered outside any form. Keep the last
    # delivered value in ordinary session state when its selectbox is unmounted,
    # otherwise Streamlit widget cleanup drops a previous explicit route.
    routes_key = key + "_destination_route_values"
    rendered_key = key + "_destination_route_rendered"
    route_values = st.session_state.get(routes_key, {})
    previously_rendered = set(st.session_state.get(rendered_key, ()))
    rendered_routes = []
    for item in contents:
        if not sources.image_numbers(item):
            continue
        control_key = key + "_destination_" + item.source.id + "_" + item.source.classification
        visible = selected_source_id is None or item.source.id == selected
        # Once a selectbox is unmounted Streamlit drops its widget value, and
        # reading the key can fall back to the default first seeded for it.
        # Only a selectbox shown on the previous render can carry a newer
        # choice; otherwise the last delivered route is authoritative.
        if control_key in route_values and (control_key not in st.session_state or not (
                visible and control_key in previously_rendered)):
            st.session_state[control_key] = route_values[control_key]
        if visible:
            rendered_routes.append(control_key)
        control = field(control_key, defaults.get(item.source.classification, "Do not embed"))
        options = ("Do not embed", *sources.PAGE_DESTINATIONS)
        if st.session_state[control] not in options:
            st.session_state[control] = defaults.get(item.source.classification, "Do not embed")
        # Old sessions may have a source-level correction but no explicit
        # callback receipt. A nondefault saved choice remains a human override.
        if item.source.id not in manual and st.session_state[control] != defaults.get(item.source.classification, "Do not embed"):
            manual[item.source.id] = st.session_state[control]
        route_controls.append((item.source.filename, item.source.id, control))
    if route_controls:
        with st.container(key=key + "_destination_review"):
            st.text("Automatic destinations for reviewed pages")
            with st.expander("Change destination (optional)"):
                # Only the current file needs an editable route widget. Other
                # delivered routes still participate in bulk Add unchanged.
                for filename, identity, control in route_controls:
                    if selected_source_id is None or identity == selected:
                        st.selectbox("Report section for " + filename,
                                     ("Do not embed", *sources.PAGE_DESTINATIONS),
                                     format_func=labels.get, key=control,
                                     on_change=_remember_manual_page_route,
                                     args=(manual_key, identity, control))
    st.session_state[routes_key] = {control: st.session_state[control]
                                  for _, _, control in route_controls}
    st.session_state[rendered_key] = tuple(rendered_routes)
    manual.update(st.session_state.get(manual_key, {}))
    # A genuinely removed page retains its exclusion receipt. Previously
    # attached images keep their precise owner and are never cloned.
    owners = included_pages(attached_blocks or {})
    try:
        choices = route_pages(contents, profile, period=period, overrides=manual, owned=owners)
    except ValueError as exc:
        st.warning("Source routing needs correction: " + str(exc))
        choices = ()
    by_source = defaultdict(list)
    for choice in choices:
        by_source[choice.source_id].append(choice)
    # A retained page of a deliberately omitted section is never prepared
    # again: merging it would switch that section back on.
    omitted = {name for name, block in (attached_blocks or {}).items() if block.source == "Omit"}
    destinations.extend(batch_destinations(choices, section_page_owners, omitted))
    for filename, identity, _ in route_controls:
        decisions = by_source[identity]
        grouped = defaultdict(list)
        for decision in decisions:
            grouped[decision.destination or decision.section].append(decision.page)
        if grouped:
            st.text(filename + " · " + "; ".join(
                f"{labels.get(slot, slot)}: {', '.join(map(str, pages))}"
                for slot, pages in grouped.items()))
        corrections = [decision for decision in decisions if decision.action in {"blocked", "review"}]
        if corrections:
            first = corrections[0]
            st.warning(f"{filename} · page/item {first.page}: {first.reason}"
                       + (f" ({len(corrections)-1} other pages need review in this file.)"
                          if len(corrections) > 1 else ""))
    cmms_contents = [c for c in contents if (selected_source_id is None or c.source.id == selected_source_id)
                     and c.tables and c.source.classification == "CMMS export"
                     and any(i in c.source.selected_pages for i in range(1, len(c.tables)+1))]
    if cmms_contents:
        with st.expander("Match spreadsheet columns"):
            st.caption("CMMS means computerized maintenance management system. Confirm only the months and facilities fully covered by this export.")
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
                st.caption("The selected spreadsheet totals and service calls will be added with the reviewed pages below.")
    signature = _signature((profile.contract, profile.key, period.key,
        [content.source.fingerprint for content in contents], destinations,
        {name: asdict(block) for name, block in blocks.items()},
        {name: asdict(spec) for name, spec in specs.items()}))
    pending = bool((accepted and accepted[0] != signature) or st.session_state.get(failure_key))
    if retain_accepted:
        st.session_state[pending_key] = pending
    if pending:
        st.info("Review and add the pending file selection before creating files."
                + (" This report keeps its last added selection." if accepted else
                   " No pages or tables from this selection have been added."))
        if accepted:
            st.caption("Adding replaces the last added pages and tables in this detailed layout. Other report content and original files stay unchanged.")
    # The guided editor commits additions into its canonical draft once. The
    # retained detailed editor reconstructs its draft on every native action,
    # so it keeps a source/mapping-bound accepted selection for that consumer.
    if st.button("Add selected pages and tables to report", key=key + "_add_selection_" + signature[:16],
                 disabled=not destinations and not blocks):
        try:
            with st.spinner("Adding reviewed pages and tables…"):
                prepared = sources.prepare_pages(profile, contents, tuple(destinations)) if destinations else ()
            if retain_accepted and accepted and accepted[0] == signature:
                # Retrying the exact accepted selection keeps its occurrences.
                # A real remove/re-add clears that batch and allocates new IDs.
                prepared = tuple(accepted[1].get(block.key, block) for block in prepared)
            blocks.update((block.key, block) for block in prepared)
            if retain_accepted:
                # The accepted report uses the exact source facts that bound
                # these pages/tables, while the intake UI may stage new facts.
                from app.monthly_report_source_retirement import record_retired_contributions
                st.session_state[retired_key] = record_retired_contributions(
                    st.session_state.get(retired_key, {}), accepted[1] if accepted else {}, blocks)
                st.session_state[accepted_key] = (signature, dict(blocks), dict(specs),
                                                 tuple(content.source for content in contents))
                st.session_state[pending_key] = False
                st.session_state.pop(failure_key, None)
            return tuple(c.source for c in contents), blocks, specs
        except (ValueError, OSError) as exc:
            if retain_accepted:
                st.session_state[failure_key] = signature
                st.session_state[pending_key] = True
            st.error(str(exc))
            st.caption("Nothing was added. Correct the selected source pages and try again.")
    if accepted:
        return tuple(accepted[3]), dict(accepted[1]), dict(accepted[2])
    return tuple(c.source for c in contents), {}, {}


def set_source_manager_open(key, opened):
    st.session_state[key] = opened


def _select_review_file(key, identity):
    st.session_state[key] = identity


def _queue_page_action(key, source, block, number, action, caption_key=None, scope=None):
    st.session_state[key] = {
        "source_id": source.id, "source_fingerprint": source.fingerprint,
        "block_key": block.key, "block_fingerprint": block.fingerprint,
        "number": number, "action": action, "scope": scope,
    }
    # Streamlit installs submitted widget values before invoking callbacks.
    # Capture the delivered caption, not the prior render's source object.
    # Absence is not an intentional clear; invalid payloads fail validation.
    if caption_key is not None and caption_key in st.session_state:
        st.session_state[key]["caption"] = st.session_state[caption_key]


def _queue_section_inclusion(key, request):
    st.session_state[key] = request


def _omitted_water_recovery(contents, blocks, local_key, prefix):
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_page_controls import (
        apply_omitted_section_request, omitted_section_ready, omitted_section_request, retained_water_omission,
    )
    scope = _rich_text_scope(prefix)
    request_key = local_key + "_reinclude_omitted"
    request = st.session_state.pop(request_key, None)
    if request is not None:
        try:
            changes = apply_omitted_section_request(contents, blocks, request, scope=scope)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            blocks.update(changes)
            # Refresh controls only after the caller commits the complete draft
            # and attempts durable recovery, just like automatic page inclusion.
            st.session_state[prefix + "_period_editor_refresh"] = True
    block = blocks.get("water_reports")
    if not retained_water_omission(block):
        return
    st.info("Water treatment is left out of this report. Its retained content is unchanged.")
    page_label = "page" if len(block.asset_hashes) == 1 else "pages"
    scope_copy = (f"all {len(block.asset_hashes)} retained {page_label} and any retained wording or tables"
                  if block.asset_hashes else "the retained wording and tables")
    st.caption(f"This action includes {scope_copy} in Water treatment. Other sections and original files stay unchanged.")
    ready = omitted_section_ready(block, contents)
    if not ready:
        st.caption("Review every retained page before including this section. For unmapped artwork, use the attached-page replacement below to provide a clear included copy.")
    request = omitted_section_request(block, contents, scope=scope)
    stamp = _signature(request)[:16]
    st.button("Include Water treatment section in this report", key=local_key + "_include_section_" + stamp,
              disabled=not ready, on_click=_queue_section_inclusion, args=(request_key, request))


def _included_page_controls(source, page, prefix, field, blocks, preview_ok, contents, *,
                            destination="water_reports", scope="", caption_source=None, navigation_prefix=None):
    """Edit the attached page beside its source, not in a second picture panel."""
    from app.monthly_report_page_controls import included_page_caption, page_asset_index, revise_included_page
    block = blocks.get(destination)
    index = page_asset_index(block, source.id, page)
    if index is None:
        return source, False
    p = prefix + "_" + source.id
    current_caption = included_page_caption(block, source, page)
    # Ordinary caption/review edits keep the native field. A replaced
    # source, image set or report incarnation cannot receive an older packet.
    context_source = replace(caption_source or source, captions=(), selected_pages=(),
                             client_page_reviews=(), client_page_exclusions=())
    from app.monthly_report_section_uploads import page_identity
    identity = lambda ref: page_identity(ref) or ref
    provenance = tuple((asset, tuple(identity(ref) for ref in refs
                                    if not ref.startswith("asset-source-context:v1:")))
                       for asset, refs in block.asset_provenance)
    context = _signature((scope, context_source.fingerprint, block.asset_hashes,
                          tuple(identity(ref) for ref in block.references), provenance,
                          block.source == "Omit"))[:20]
    caption_key = field(p + f"_caption_{page}_" + context, current_caption)
    st.session_state.setdefault(p + "_caption_widget_keys", {})[page] = caption_key
    caption = st.text_input("Page caption", key=caption_key)
    if caption != current_caption:
        block, source = revise_included_page(block, source, page, "caption", caption=caption,
                                            all_sources=tuple(c.source for c in contents))
        blocks[block.key] = block
    if navigation_prefix:
        st.session_state[navigation_prefix + "_page_navigation_origin"] = {
            "source_id": source.id, "source_fingerprint": source.fingerprint,
            "block_key": block.key, "block_fingerprint": block.fingerprint,
            "number": page, "scope": scope, "caption_key": caption_key, "caption": caption,
        }
        from app.monthly_report_page_navigation import ready_page_markup
        marker = ready_page_markup(st.session_state, navigation_prefix, source, block,
                                  page, caption_key, scope)
        if marker:
            st.markdown(marker, unsafe_allow_html=True)
    if not page_allowed(source, page):
        st.warning("This retained page changed since its review. Check the page and caption before including the section."
                   if block.source == "Omit" else
                   "This included page changed since its review. Check the page and caption, then include it again or leave it out.")
    elif block.source == "Omit":
        st.caption("Retained page — left out of this report. Reviewing it does not include the section.")
    else:
        st.caption("Included in this report. Changes here do not alter the original file.")
    kind, reason = page_status(source.page_texts[page - 1], unreadable=page in source.needs_vision)
    blocked = kind in ("pricing", "legal", "blank", "signature") or contains_price(caption)
    if blocked:
        st.warning("Remove pricing from the caption before including this page." if contains_price(caption) else reason)
    stamp = _signature((scope, block.fingerprint, source.fingerprint, page))[:16]
    request_key = prefix + "_page_edit"
    keep, omit = st.columns(2)
    keep.button("Review retained page" if block.source == "Omit" else "Include page", key=p + "_included_keep_" + stamp,
                disabled=blocked or not preview_ok, on_click=_queue_page_action,
                args=(request_key, source, block, page, "review", caption_key, scope))
    omit.button("Remove retained page from this section" if block.source == "Omit" else "Exclude page", key=p + "_included_omit_" + stamp,
                on_click=_queue_page_action, args=(request_key, source, block, page, "omit", caption_key, scope))
    if len(block.asset_hashes) > 1:
        earlier, later = st.columns(2)
        earlier.button("Move page earlier", key=p + "_earlier_" + stamp, disabled=index == 0,
                       on_click=_queue_page_action, args=(request_key, source, block, page, "earlier", caption_key, scope))
        later.button("Move page later", key=p + "_later_" + stamp, disabled=index == len(block.asset_hashes) - 1,
                     on_click=_queue_page_action, args=(request_key, source, block, page, "later", caption_key, scope))
    return source, True


def _render_section_page_review(profile, content, prefix, field, blocks, *, period, auto_include=False, contents=(),
                                editor_prefix=None, destination="water_reports"):
    """Review pages once; only an exact completed technical review adds pages."""
    from app.monthly_report_section_uploads import included_pages
    from app.monthly_report_page_controls import retained_page_section_omission

    source = content.source
    canonical_source = source
    close_reviews = False
    refresh_prefix = editor_prefix or prefix
    from app.monthly_report_guided import _rich_text_scope
    scope = _rich_text_scope(refresh_prefix)

    def finish(updated):
        _acknowledge_managed_page_edit(canonical_source, updated.source, refresh_prefix)
        st.session_state[p + "_source_details_baseline"] = updated.source.fingerprint
        if close_reviews:
            st.session_state[p + "_edit_page_reviews"] = False
            # The caller must keep every delivered editor value and attempt
            # durable recovery before the one-shot controls refresh.
            st.session_state[refresh_prefix + "_period_editor_refresh"] = True
        return updated

    section_omitted = auto_include and retained_page_section_omission(blocks.get(destination))
    p = prefix + "_" + source.id
    widget_source = _page_widget_source(source, p, refresh_prefix)
    _sync_source_fields(source, p, field)
    image_pages = sources.image_numbers(content)
    existing = included_pages(blocks)
    included_here = tuple(n for n in image_pages if (source.id, n) in existing)
    native_auto_screen = any(
        notice.startswith("Automatic native-text screen included eligible Water pages")
        for notice in source.notices)
    compact = (auto_include and included_here
               and (not _undecided_pages(content, source) or native_auto_screen)
               and all(page_allowed(source, n) for n in included_here)
               and not st.session_state.get(p + "_edit_page_reviews", False))
    from app.monthly_report_source_details import detail_problems
    problems = detail_problems(source, profile, period) if compact else ()
    if not compact or problems:
        source = render_source_details(source, profile, p, field, compact_problems=problems)
    # A submitted correction can invalidate page review in this same event.
    compact = compact and source == canonical_source
    content = replace(content, source=source)
    if not image_pages:
        st.info("This file contains extracted text or tables. Its original is saved. Use the section's text/table editor, or the work-order spreadsheet tools, to include that content.")
        with st.expander("Read this file"):
            st.text("\n\n".join(source.page_texts)[:12000] or "No readable text was found.")
        return finish(content)
    if not compact and not st.session_state.get("_monthly_source_details_managed"):
        with st.expander("File details (optional)"):
            st.caption("These are suggested facts from the file. Blank means not established; adding it here does not change its classification.")
            changes = {}
            st.caption("File classification: " + source.classification)
            for attr, label in (("vendor", "Vendor"), ("work_order", "Job / work-order number")):
                changes[attr] = st.text_input(label, key=field(p + "_" + attr, getattr(source, attr)))
            from app.monthly_report_source_scope import preserve_descriptive_scope
            source = preserve_descriptive_scope(source, replace(source, **changes), profile)
    for notice in source.notices:
        st.warning(notice)
    undecided = [n for n in _undecided_pages(content, source) if (source.id, n) not in existing]
    if auto_include:
        # Once all this source's decisions are complete, an included PDF is
        # already usable. Reopen full page review only when deliberately asked,
        # or immediately when a changed/new source page needs attention.
        included_here = tuple(n for n in image_pages if (source.id, n) in existing)
        expanded_key = p + "_edit_page_reviews"
        if (included_here and (not undecided or native_auto_screen)
                and all(page_allowed(source, n) for n in included_here)):
            if not st.session_state.get(expanded_key, False):
                if undecided:
                    st.caption(f"{len(undecided)} page(s) need separate review or exclusion; "
                               "the screened technical attachments are already in this report.")
                if st.button(
                    "Report pages", key=p + "_open_page_reviews",
                    help="Review, caption, reorder or leave out pages here. Saved originals are unchanged.",
                ):
                    st.session_state[expanded_key] = True
                    st.rerun()
                st.session_state[p + "_canonical_view"] = source
                return finish(replace(content, source=source))
            stamp = _signature((scope, widget_source.fingerprint,
                                blocks.get(destination)))[:20]
            close_reviews = st.button("Close report pages", key=p + "_close_page_reviews_" + stamp)
    page_key = field(p + "_page", undecided[0] if undecided else image_pages[0])
    pending = st.session_state.pop(p + "_next_page", None)
    if pending in image_pages:
        st.session_state[page_key] = pending
    if st.session_state[page_key] not in image_pages:
        st.session_state[page_key] = image_pages[0]
    page_labels = {n: f"Page {n}" + (" · retained, left out" if section_omitted and (source.id, n) in existing
                  else " · already in report" if (source.id, n) in existing
                  else " · reviewed, not in report" if n in source.selected_pages and page_allowed(source, n)
                  else " · left out" if dict(source.client_page_exclusions).get(n) == page_fingerprint(source, n)
                  else " · needs review") for n in image_pages}
    page = st.selectbox("Page to review", image_pages, key=page_key, format_func=page_labels.get)
    preview_ok = False
    try:
        thumbnail = sources.page_image(profile, content, page, preview=True)
        from app.monthly_report_source_preview import source_thumbnail_uri
        st.image(source_thumbnail_uri(thumbnail), width=650)
        preview_ok = True
    except (ValueError, OSError) as exc:
        st.error(str(exc))
    if st.session_state.get("_monthly_source_details_managed"):
        from app.monthly_report_page_context_ui import render_page_source_context
        render_page_source_context(source, profile, refresh_prefix, page)
    with st.expander("Text read from this page"):
        st.text(source.page_texts[page - 1][:12000] or "No native text on this page. Review the image above.")
    if (source.id, page) in existing:
        if auto_include:
            source, handled = _included_page_controls(source, page, prefix, field, blocks, preview_ok, contents,
                                                       destination=destination, scope=scope,
                                                       caption_source=widget_source, navigation_prefix=refresh_prefix)
            if handled:
                st.session_state[p + "_canonical_view"] = source
                return finish(replace(content, source=source))
        if not page_allowed(source, page):
            st.warning("This included page changed since its review. Correct or remove it below, then review the current source before export.")
        else:
            st.caption("This page is already included. Remove it using the report pictures below, if needed.")
    else:
        captions = dict(source.captions)
        default_caption = captions.get(page, f"{source.filename} · page/item {page}")
        caption_key = field(p + f"_caption_{page}", default_caption)
        caption = st.text_input("Page caption", key=caption_key)
        # Showing an unvisited page must not change a saved report. Keep the
        # generated suggestion local until an edit or explicit page decision.
        if page in captions or caption != default_caption:
            captions[page] = caption
            source = replace(source, captions=tuple(sorted(captions.items())))
        kind, reason = page_status(source.page_texts[page - 1], unreadable=page in source.needs_vision)
        blocked = kind in ("pricing", "legal", "blank", "signature") or contains_price(caption)
        if contains_price(caption):
            reason = "Remove pricing from the caption before including this page."
        (st.warning if blocked else st.caption)(reason)
        st.caption("Include confirms that you checked this page and caption: relevant work, no prices, and no legal-only, blank or signature-only content.")
        if section_omitted:
            st.caption("This section is left out. Restore its retained content before adding pages.")
        if len(image_pages) > 1:
            st.caption("After each decision, the next unreviewed page opens.")
        keep, omit = st.columns(2)
        action = None
        if keep.button("Include page", key=p + "_keep_page", disabled=blocked or not preview_ok or section_omitted):
            action = "keep"
        if omit.button("Exclude page", key=p + "_omit_page"):
            action = "omit"
        if action:
            # Bind the exact displayed caption before calculating either
            # decision receipt; a navigation-only visit does not do this.
            if page not in dict(source.captions):
                source = replace(source, captions=tuple(sorted({**dict(source.captions), page: caption}.items())))
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
            if auto_include:
                # Track actual Include clicks in the current review sequence.
                # A page removed from the report may still be selected in its
                # immutable source record; that is NOT consent to restore it
                # when a different page is newly reviewed.
                clicked_key = p + "_explicit_keeps"
                clicked = set(st.session_state.get(clicked_key, ()))
                if action == "keep":
                    clicked.add(page)
                else:
                    clicked.discard(page)
                st.session_state[clicked_key] = tuple(sorted(clicked))
            remaining = [n for n in _undecided_pages(content, source) if (source.id, n) not in existing]
            if auto_include and not remaining:
                # An exact user-initiated completion receipt is consumed only
                # after the corresponding pages merge into the report.
                new_pages = tuple(n for n in st.session_state.pop(
                    p + "_explicit_keeps", ())
                    if n in image_pages and n in source.selected_pages
                    and (source.id, n) not in existing)
                request_key = prefix + "_auto_include"
                if new_pages and all(page_allowed(source, n) for n in new_pages):
                    st.session_state[request_key] = {
                        "source_id": source.id, "fingerprint": source.fingerprint,
                        "pages": new_pages,
                    }
                else:
                    st.session_state.pop(request_key, None)
            st.session_state[p + "_next_page"] = next((n for n in remaining if n > page), remaining[0] if remaining else page)
            # The caller persists this source before rerunning, retaining every
            # other section's canonical evidence object unchanged.
            st.session_state[prefix + "_review_rerun"] = True
    st.session_state[p + "_canonical_view"] = source
    return finish(replace(content, source=source))


def render_section_uploads(profile: ReportProfile, period: ReportPeriod, prefix: str, field,
                           destination: str, *, blocks=None, assets=None, sections=None):
    """Return reviewed page additions; Water adds when its final review is done.

    The caller merges additions atomically. The source cache is canonical and
    shared with the optional batch/CMMS workspace; classification is unchanged.
    """
    from app.monthly_report_section_uploads import (
        SECTION_UPLOADS, pending_pages, prepare_section_pages, section_contents, source_destinations,
    )
    from app.monthly_report_page_controls import retained_water_omission
    if destination not in SECTION_UPLOADS:
        raise ValueError("Unknown report section for uploaded pages.")
    blocks = {} if blocks is None else blocks
    title, upload_label = SECTION_UPLOADS[destination]
    key = prefix + "_evidence"
    local_key = key + "_section_" + destination
    contents = st.session_state.setdefault(key, ())
    bindings = dict(st.session_state.setdefault(key + "_section_routes", {}))
    fresh_ids = ()
    from app.monthly_report_page_controls import retained_page_section_omission
    if (destination in AUTO_INCLUDE_PAGE_DESTINATIONS
            and retained_page_section_omission(blocks.get(destination))
            and st.session_state.pop(local_key + "_auto_include", None) is not None):
        # A previous review cannot reverse a deliberate omitted section,
        # including after a stale browser request or report reload.
        st.session_state.pop(local_key + "_auto_include_failure", None)
        st.warning("This section is left out. Restore its retained content before adding pages.")
    pending_edit = st.session_state.pop(local_key + "_page_edit", None)
    if pending_edit:
        from app.monthly_report_page_controls import apply_page_request
        try:
            from app.monthly_report_guided import _rich_text_scope
            if not isinstance(pending_edit, dict) or pending_edit.get("scope") != _rich_text_scope(prefix):
                raise ValueError("This report changed after the page action was opened. Your current report is unchanged; review the page again.")
            before_page_edit = {content.source.id: content.source for content in contents}
            contents, changes = apply_page_request(contents, blocks, pending_edit)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            blocks.update(changes)
            st.session_state[key] = contents
            forms = st.session_state.get("_monthly_source_detail_forms")
            if isinstance(forms, dict):
                for content in contents:
                    if content.source.id == pending_edit["source_id"]:
                        # This exact accepted page action happened after the
                        # source form was drawn. Carry its narrow revision
                        # forward, without waiving an unrelated source edit.
                        _acknowledge_managed_page_edit(
                            before_page_edit[content.source.id], content.source, prefix)
                        forms[content.source.id] = content.source
            request = st.session_state.get(local_key + "_auto_include")
            if request and request["source_id"] == pending_edit["source_id"]:
                st.session_state.pop(local_key + "_auto_include", None)
                st.session_state.pop(local_key + "_auto_include_failure", None)
    if destination not in {"water_reports", "utility_analysis", "mbcx_report"}:
        st.markdown("**" + title + "**")
        st.caption("Choose a file, check its useful pages, then add them here. Existing report content is kept.")
    # Water, Scorecards and MBCx already have section-level instructions. Keep one
    # labeled uploader without a duplicate title, while retaining the complete
    # canonical page-review flow and its safety checks.
    if destination in {"mbcx_report", "utility_analysis"}:
        st.caption("Upload a PDF to include its complete report. Supporting files and existing page choices remain available.")
    # One directly visible section source task. Preserve the existing uploader
    # and saved-source widget identities across ordinary report reruns.
    with st.container(key=local_key + "_add_files"):
        st.text("Upload new")
        from app.monthly_report_native_loading import reserve_empty_uploader
        reserve_empty_uploader(local_key + "_upload", upload_label)
        upload = st.file_uploader(upload_label, type=sorted(s.lstrip(".") for s in sources.SUPPORTED),
                                 accept_multiple_files=True, key=local_key + "_upload", **evidence_upload_options())
        picked = tuple((u.name, u.getvalue()) for u in (upload or ()))
        signature = _signature([(name, hashlib.sha256(raw).hexdigest()) for name, raw in picked])
        if picked and st.session_state.get(local_key + "_read") != signature:
            before = {c.source.id for c in contents}
            owners = source_destinations(contents, bindings, blocks)
            with st.spinner("Reading files and checking duplicates…"):
                contents, messages = sources.ingest_batch(profile, picked, contents)
            messages = list(messages)
            fresh_ids = tuple(c.source.id for c in contents if c.source.id not in before)
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
        from app.monthly_report_source_recovery_ui import render_failed_file_retries
        retried = render_failed_file_retries(profile, period,
            st.session_state.get(prefix + "_revision", 0), local_key, picked, contents,
            messages=st.session_state.get(local_key + "_messages", ()))
        if retried is not None:
            old_ids = {content.source.id for content in contents}
            contents, messages, _ = retried
            for content in contents:
                if content.source.id not in old_ids:
                    bindings[content.source.id] = destination
            st.session_state[key] = contents
            st.session_state[key + "_section_routes"] = bindings
            st.session_state[local_key + "_messages"] = tuple(messages)
        owners = source_destinations(contents, bindings, blocks)
        unassigned = [c for c in contents if not owners[c.source.id]]
        if unassigned:
            st.text("Already uploaded")
            choices = {c.source.id: c for c in unassigned}
            choice_key = field(local_key + "_saved_choice", next(iter(choices)))
            if st.session_state[choice_key] not in choices:
                st.session_state[choice_key] = next(iter(choices))
            # Exact source identities, never filenames, select reusable originals.
            # Showing this chooser is not approval or an automatic route.
            filenames = {identity: item.source.filename for identity, item in choices.items()}
            chosen = st.selectbox("Saved file", list(choices), format_func=filenames.get, key=choice_key)
            if st.button("Use in " + title, key=local_key + "_use_saved"):
                bindings[chosen] = destination
                st.session_state[key + "_section_routes"] = bindings
    for message in st.session_state.get(local_key + "_messages", ()):
        st.warning(message)
    scoped = section_contents(contents, destination, bindings, blocks)
    if not scoped:
        # Retained native wording/tables can outlive their source workspace.
        # Their explicit section choice must remain reachable without a file.
        if destination == "water_reports":
            _omitted_water_recovery(contents, blocks, local_key, prefix)
        return tuple(c.source for c in contents), {}, {}
    if destination == "water_reports":
        # A new, native-text Water PDF is the section's one-action path. Never
        # replay this for an existing source, even after a report-only removal.
        # The normal page manager remains available for visual exceptions.
        from app.monthly_report_section_uploads import automatic_water_upload, source_route
        from app.monthly_report_setup import merge_blocks
        exceptions_key = local_key + "_automatic_exceptions"
        if fresh_ids:
            all_exceptions, combined, shadow = [], {}, dict(blocks)
            refreshed = {c.source.id: c for c in contents}
            water_is_open = sections is None or any(
                s.key == "water" and s.included for s in sections)
            for item in scoped:
                source = item.source
                if source.id not in fresh_ids or source.suffix != ".pdf":
                    continue
                if not water_is_open:
                    all_exceptions.append(f"{source.filename}: Water treatment is excluded from this report.")
                    continue
                from app.monthly_report_section_uploads import included_pages
                if (any(identity == source.id for identity, _ in included_pages(blocks))
                        or any(source_route(ref) == ("water_reports", source.id, source.sha256)
                               for block in blocks.values() for ref in block.references)):
                    # The saved routing receipt can outlive a deliberately
                    # omitted last page; absence of an image is not consent.
                    continue
                plan = automatic_water_upload(profile, period, item, shadow)
                all_exceptions.extend(f"{source.filename}: {reason}" for reason in plan.exceptions)
                if not plan.pages:
                    continue
                pairs = frozenset((source.id, page) for page in plan.pages)
                try:
                    prepared = prepare_section_pages(
                        profile, (plan.content,), destination, shadow, assets, only_pages=pairs)
                except (ValueError, OSError) as exc:
                    all_exceptions.append(
                        f"{source.filename}: Could not include screened pages: {exc}")
                    continue
                refreshed[source.id] = plan.content
                for slot, block in prepared.items():
                    combined[slot] = merge_blocks(combined.get(slot), block)
                    shadow[slot] = merge_blocks(shadow.get(slot), block)
            contents = tuple(refreshed[c.source.id] for c in contents)
            st.session_state[key] = contents
            st.session_state[exceptions_key] = tuple(all_exceptions)
            if combined:
                included_count = len(combined["water_reports"].asset_hashes)
                notice = (f"Included {included_count} native-text Water pages automatically. "
                          "Open Report pages to review captions or remove an attachment.")
                st.caption(notice)
                for warning in all_exceptions:
                    st.warning(warning)
                # The caller commits these pages; then one rerun shows them in
                # the page manager (file name and Report pages) with this notice.
                st.session_state[local_key + "_automatic_included"] = notice
                st.session_state[prefix + "_period_editor_refresh"] = True
                return tuple(c.source for c in contents), combined, {}
        included_notice = st.session_state.pop(local_key + "_automatic_included", None)
        if included_notice:
            st.caption(included_notice)
        for notice in st.session_state.get(exceptions_key, ()):
            st.warning(notice)
        st.caption("Clear native-text Water pages attach on upload. "
                   "Priced, scanned and visually uncertain pages stay out for review.")
        included = (len(blocks["water_reports"].asset_hashes)
                    if "water_reports" in blocks and blocks["water_reports"].source != "Omit" else 0)
        st.markdown(f"**Report pages ({included})**")
    choices = {c.source.id: c for c in scoped}
    selected_key = field(local_key + "_selected", next(iter(choices)))
    if st.session_state[selected_key] not in choices:
        st.session_state[selected_key] = next(iter(choices))
    if len(choices) == 1:
        selected = next(iter(choices))
        st.caption(choices[selected].source.filename)
    else:
        selected = st.selectbox("File to review", list(choices), format_func=lambda v: choices[v].source.filename, key=selected_key)
    if choices[selected].source.suffix == ".pdf":
        from app.monthly_report_section_uploads import preflight_whole_pdf
        try:
            budget = preflight_whole_pdf(profile, choices[selected], destination, blocks)
        except (ValueError, OSError) as exc:
            st.warning(str(exc))
        else:
            st.caption(f"Whole PDF: {budget.new_pages} new pages · "
                       f"{budget.available_pages} report page slots available"
                       + (f" · {budget.already_included} already included" if budget.already_included else ""))
            if not budget.pages_fit:
                st.warning(f"The whole PDF cannot fit: {budget.new_pages} new pages need "
                           f"{budget.available_pages} available slots. Include fewer pages "
                           "or remove existing report pages before reviewing this file.")
            elif budget.new_pages and st.button("Check whole-PDF image size", key=local_key + "_pdf_preflight_" + selected,
                                                help="Optional: measure print-size pages against the remaining 60 MiB image budget before reviewing them."):
                try:
                    measured = preflight_whole_pdf(
                        profile, choices[selected], destination, blocks, assets, measure_bytes=True)
                except (ValueError, OSError) as exc:
                    st.warning("Whole-PDF size check could not finish: " + str(exc))
                else:
                    needed = measured.new_image_bytes / (1024 * 1024)
                    available = measured.remaining_bytes / (1024 * 1024)
                    if measured.images_fit:
                        st.success(f"All {measured.new_pages} new pages fit the current image budget "
                                   f"({needed:.1f} of {available:.1f} MiB available). "
                                   "Page-content review is still required.")
                    else:
                        st.warning(f"The whole PDF cannot fit the image budget: its checked pages "
                                   f"need at least {needed:.1f} MiB, with {available:.1f} MiB available. "
                                   "Reduce selected pages or remove existing evidence before reviewing.")
    if destination == "mbcx_report":
        from app.monthly_report_mbcx_financial_pages import render_reviewed_batch
        from app.monthly_report_guided import _rich_text_scope
        handled, revised, financial_batch = render_reviewed_batch(
            profile, choices[selected], blocks, assets, local_key, period=period, editor_scope=_rich_text_scope(prefix), sections=sections)
        if handled:
            # The guided caller validates and commits the whole prepared draft;
            # do not approve sources or renew old pictures ahead of that merge.
            return tuple(c.source for c in contents), {}, (
                {"financial_batch": financial_batch, "financial_evidence_key": key} if financial_batch else {})
    if destination in {"mbcx_report", "utility_analysis"} and choices[selected].source.suffix == ".pdf":
        from app.monthly_report_mbcx_pdf import render_whole_pdf
        batch = render_whole_pdf(profile, choices[selected], blocks, assets,
                                 local_key, prefix, field, period=period, destination=destination)
        if batch is not None:
            revised, additions = batch
            contents = tuple(revised if c.source.id == selected else c for c in contents)
            st.session_state[key] = contents
            forms = st.session_state.get("_monthly_source_detail_forms")
            if isinstance(forms, dict) and selected in forms:
                forms[selected] = revised.source
            return tuple(c.source for c in contents), additions, {}
    revised = _render_section_page_review(
        profile, choices[selected], local_key, field, blocks,
        period=period,
        auto_include=(destination in AUTO_INCLUDE_PAGE_DESTINATIONS), contents=contents,
        editor_prefix=prefix, destination=destination,
    )
    contents = tuple(revised if c.source.id == selected else c for c in contents)
    st.session_state[key] = contents
    forms = st.session_state.get("_monthly_source_detail_forms")
    if isinstance(forms, dict) and selected in forms:
        forms[selected] = revised.source
    if st.session_state.pop(local_key + "_review_rerun", False):
        st.rerun()
    if destination == "water_reports":
        _omitted_water_recovery(contents, blocks, local_key, prefix)
    scoped = section_contents(contents, destination, bindings, blocks)
    pending = pending_pages(scoped, destination, blocks)
    by_id = {c.source.id: c for c in scoped}
    ready = bool(pending) and all(page_allowed(by_id[identity].source, number) for identity, number in pending)
    additions = {}

    if destination in AUTO_INCLUDE_PAGE_DESTINATIONS:
        # Only the last explicit include/leave-out click authorizes auto-add.
        # Merely reopening an earlier reviewed file, changing sections, or
        # removing an already included page can NEVER restore that page.
        from app.monthly_report_section_uploads import included_pages
        owned = included_pages(blocks)
        request_key = local_key + "_auto_include"
        failure_key = request_key + "_failure"
        request = st.session_state.get(request_key)
        if request:
            identity = request["source_id"]
            expected = tuple((identity, n) for n in request["pages"])
            if expected and all(destination in owned.get(pair, ()) for pair in expected):
                st.session_state.pop(request_key, None)
                st.session_state.pop(failure_key, None)
                request = None
            else:
                content = by_id.get(identity)
                matches = (content is not None
                           and content.source.fingerprint == request["fingerprint"]
                           and all(pair in pending and page_allowed(content.source, pair[1])
                                   for pair in expected)
                           and not _undecided_pages(content, content.source))
                if not matches:
                    st.session_state.pop(request_key, None)
                    st.session_state.pop(failure_key, None)
                    st.warning("The reviewed source has changed. Check its pages again before including them.")
                else:
                    previous_failure = st.session_state.get(failure_key)
                    retry = (st.button("Retry including reviewed pages", key=local_key + "_auto_retry")
                             if previous_failure and previous_failure[0] == request["fingerprint"]
                             else True)
                    if previous_failure and not retry:
                        st.error(previous_failure[1])
                    elif retry:
                        try:
                            with st.spinner("Including reviewed technical report pages…"):
                                additions = prepare_section_pages(
                                    profile, (content,), destination, blocks, assets,
                                    only_pages=frozenset(expected))
                        except (ValueError, OSError) as exc:
                            message = "Reviewed pages were not added: " + str(exc)
                            st.session_state[failure_key] = (request["fingerprint"], message)
                            st.error(message)
                        else:
                            st.session_state.pop(failure_key, None)
        current_pages = tuple(n for n in sources.image_numbers(revised)
                              if (selected, n) in owned)
        current_is_compact = (current_pages and not _undecided_pages(revised, revised.source)
                              and all(page_allowed(revised.source, n) for n in current_pages)
                              and not st.session_state.get(
                                  local_key + "_" + selected + "_edit_page_reviews", False))
        if (current_is_compact and not additions and not st.session_state.get(request_key)
                and not retained_page_section_omission(blocks.get(destination))):
            # A finished file may be selected while a different file still
            # needs decisions. Name that file and reopen the ordinary review.
            # Only show this shortcut from the compact state, which has no
            # pending caption input to lose. Reviewed report-only removals
            # are not unfinished reviews and never authorize reinclusion.
            remaining = next(((item, _undecided_pages(item, item.source))
                              for item in scoped if item.source.id != selected
                              and _undecided_pages(item, item.source)), None)
            if remaining:
                item, pages = remaining
                count = len(pages)
                st.caption(f"{item.source.filename}: {count} "
                           + ("page needs review." if count == 1 else "pages need review."))
                st.button("Review " + item.source.filename, key=local_key + "_review_next_file",
                          on_click=_select_review_file, args=(selected_key, item.source.id))
        return tuple(c.source for c in contents), additions, {}

    if pending:
        st.caption(f"{sum(page_allowed(by_id[identity].source, n) for identity, n in pending)} of {len(pending)} selected new pages checked.")
    else:
        st.caption("No new pages selected. Previously added pages remain in your report.")
    st.text("Add destination: " + title)
    if st.button("Add reviewed pages", key=local_key + "_apply", disabled=not ready, type="primary"):
        try:
            with st.spinner("Adding the reviewed pages…"):
                additions = prepare_section_pages(profile, scoped, destination, blocks, assets)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            st.caption("Your existing report is unchanged. The selected files and reviews are retained for another attempt.")
    return tuple(c.source for c in contents), additions, {}


def acknowledge_autoincluded_pages(prefix, blocks, destination):
    """Consume only an exact merged page receipt, never an uncommitted click."""
    if destination not in AUTO_INCLUDE_PAGE_DESTINATIONS:
        return
    from app.monthly_report_section_uploads import included_pages
    key = prefix + "_evidence_section_" + destination + "_auto_include"
    request = st.session_state.get(key)
    if not request:
        return
    owners = included_pages(blocks)
    expected = ((request["source_id"], page) for page in request["pages"])
    if all(destination in owners.get(identity, ()) for identity in expected):
        st.session_state.pop(key, None)
        st.session_state.pop(key + "_failure", None)
        # Caller commits the canonical draft before refreshing native widgets.
        st.session_state[prefix + "_period_editor_refresh"] = True


def acknowledge_autoincluded_water_pages(prefix, blocks):
    """Preserve Water's existing caller and review receipt identity."""
    acknowledge_autoincluded_pages(prefix, blocks, "water_reports")


@st.fragment(run_every=1)
def _section_read_progress(local_key):
    job = st.session_state.get(local_key + "_job")
    if job and job["future"].done():
        st.rerun()
    if job:
        st.info("Reading uploaded files and preparing this section…")


def _queue_section_read(local_key, request):
    st.session_state[local_key + "_read_request"] = dict(request)


def render_workorder_metrics(profile, period, prefix, contents, blocks, *, additions=None, selected_id=None):
    """Review one selected spreadsheet without introducing another intake path."""
    from app.monthly_report_guided import _rich_text_scope
    destination = "activity_summary"
    local_key = prefix + "_evidence_structured_" + destination
    additions = additions or {}
    if selected_id is not None:
        contents = tuple(content for content in contents if content.source.id == selected_id)
    # An explicit work-order table can produce useful counts without a model,
    # a twelve-month coverage assumption or the CMMS onsite-call mapping.
    # It is offered as reviewable source evidence, never silently written over
    # an edited Activity paragraph.
    from app.monthly_report_work_order_csv import work_order_evidence
    # Counts depend on selected sites and every accepted site-name alias.
    # A profile key can stay the same while its report-specific scope changes.
    site_scope = tuple((site.key, site.title, site.aliases) for site in profile.facilities)
    metrics_signature = _signature((period.key, profile.contract, profile.key, site_scope,
                               tuple(c.source.fingerprint for c in contents)))
    cache_key = local_key + "_workorder_metrics_cache"
    cached_evidence = st.session_state.get(cache_key)
    if cached_evidence is None or cached_evidence[0] != metrics_signature:
        reports = tuple(item for content in contents
                        for item in work_order_evidence(content, period, profile))
        st.session_state[cache_key] = (metrics_signature, reports)
    else:
        reports = cached_evidence[1]
    for report in reports:
        original = additions.get(destination, blocks.get(destination))
        if original is not None and report.text in original.text:
            st.caption("Work-order totals from " + report.filename + " are already in the Activity summary.")
            continue
        st.info(f"{period.label} · {report.filename}: {report.total} work orders · "
                f"{report.completed} completed · {report.open} open "
                f"({report.completed / report.total:.1%} completed). Uploaded rows only.")
        if report.needs_site_confirmation:
            st.warning("The work-order file has no site column. Check that these records belong to the selected report before adding them.")
        for notice in report.notices:
            st.caption(notice)
        with st.expander("Review counted work-order rows"):
            st.caption(f"{report.filename} · table {report.reference.split(':')[1]} · "
                       f"all {report.total} counted work orders")
            st.dataframe([{"Work order": row[0], "Date": row[1], "Status": row[2]}
                          for row in report.rows], hide_index=True)
        # Streamlit buttons run an on_click callback before the full-page
        # rerender, so the section editor consumes the update *before*
        # drawing its text-area widget. Otherwise its stale widget value can
        # replace the newly accepted source wording.
        previous = blocks.get(destination)
        from app.monthly_report_model import ResolvedBlock
        previous = previous or ResolvedBlock(destination, "This month")
        from app.monthly_report_guided import _pending_rich_text_edit
        # Register a retry against the input already delivered this run,
        # without committing the draft before its normal save boundary.
        previous = _pending_rich_text_edit(prefix, previous) or previous
        current_source = next(c.source for c in contents if c.source.id == report.source_id)
        confirmed = True
        if report.needs_site_confirmation:
            from app.monthly_report_source_details import facility_choice
            from app.monthly_report_source_scope import reviewed_scope
            scope_review = reviewed_scope(current_source, profile)
            confirmed = (bool(scope_review and scope_review["kind"] == "sites") or
                         (not current_source.scope_review and
                          facility_choice(current_source, profile) in {site.key for site in profile.facilities}))
            if not confirmed:
                st.caption("Choose this file's sites in Source details before inserting its totals.")
        action_scope = _rich_text_scope(prefix)
        def accept_workorders(report=report, profile=profile, period=period, previous=previous, prefix=prefix,
                              current_source=current_source, action_scope=action_scope):
            from app.monthly_report_source_scope import contribution_receipt
            # A delivered text edit can reach the working draft before an
            # interrupted rerender refreshes this button's callback. Bind
            # to that exact receipt at activation, while the consumer still
            # rejects a different report, source or unrelated block revision.
            accepted_previous = _pending_rich_text_edit(prefix, previous) or previous
            st.session_state[prefix + "_pending_accepted_workorders"] = {
                "contract": profile.contract, "profile": profile.key,
                "month": period.key, "expected": accepted_previous.fingerprint,
                "scope": action_scope,
                "source_id": report.source_id, "reference": report.reference,
                "text": report.text,
                "scope_receipt": contribution_receipt(report.reference, profile, period,
                                                      destination, text=report.text, source=current_source,
                                                      prior_block=accepted_previous),
            }
        st.button("Add totals to summary",
                  key=local_key + "_accept_work_orders_" + report.source_id[:16] + "_" + action_scope,
                  on_click=accept_workorders, disabled=not confirmed)


def render_structured_uploads(profile, period, prefix, field, destination, *, blocks=None, assets=None, table_columns=None,
                              managed=False):
    """Keep native extraction free; read externally only on an exact user request."""
    from app import monthly_report_structured_uploads as structured
    from app.monthly_report_pre_model_routing import classify_page, choose_reader_pages
    from app.monthly_report_section_uploads import included_pages
    from app import monthly_report_ai as ai
    from app.receipt_jobs import start_receipt
    from app import monthly_report_library as library, monthly_report_testing as testing
    from app.monthly_report_guided import _rich_text_scope
    from uuid import uuid4

    if destination not in {"activity_summary", "capital_renewal", "proposals"}:
        raise ValueError("Unknown upload-first section.")
    blocks = blocks or {}
    evidence_key = prefix + "_evidence"
    local_key = evidence_key + "_structured_" + destination
    contents = st.session_state.setdefault(evidence_key, ())
    labels = {"activity_summary": "Add activity files (optional)", "capital_renewal": "Add capital renewal file", "proposals": "Add proposal file"}
    context = _signature((asdict(profile), period.key, destination, tuple(table_columns or ()),
                          _rich_text_scope(prefix), testing.scope(), testing.generation()))
    from app.monthly_report_native_loading import reserve_empty_uploader
    intake_label = "Add source files" if managed else labels[destination]
    if managed:
        # The same single native uploader owns both Activity jobs; describe
        # their destinations rather than asking for a separate file-type step.
        st.caption("Work-order export (CSV/XLSX): review rows and totals. "
                   "Vendor service report (PDF/DOCX): review Activity text and evidence.")
    reserve_empty_uploader(local_key + "_upload_" + context, intake_label)
    uploaded = st.file_uploader(intake_label, type=sorted(s.lstrip(".") for s in sources.SUPPORTED),
                                accept_multiple_files=True, key=local_key + "_upload_" + context,
                                **evidence_upload_options())
    picked = tuple((u.name, u.getvalue()) for u in (uploaded or ()))
    selected_ids = {hashlib.sha256(raw).hexdigest() for _, raw in picked}
    # A native uploader retains removed bytes. Other uploads must not undo
    # Remove; release each tombstone only after that exact file leaves this
    # chooser, so clearing/reselecting is a new explicit intake decision.
    removed_key = local_key + "_removed_selection_ids"
    removed = set(st.session_state.get(removed_key, ())) & selected_ids
    st.session_state[removed_key] = tuple(removed)
    picked = tuple((name, raw) for name, raw in picked if hashlib.sha256(raw).hexdigest() not in removed)
    signature = _signature([(name, hashlib.sha256(raw).hexdigest()) for name, raw in picked])
    picked_ids = {hashlib.sha256(raw).hexdigest() for _, raw in picked}
    if st.session_state.get(local_key + "_context") != context:
        old = st.session_state.pop(local_key + "_job", None)
        if old:
            old["future"].cancel()
        for suffix in ("read", "native_ids", "completed_ids", "pending", "error",
                       "cache_checked", "completed_read", "read_cycle", "coverage"):
            st.session_state.pop(local_key + "_" + suffix, None)
        st.session_state[local_key + "_context"] = context
    additions = {}

    def _classification_delivery_pending(content):
        # Classification is delivered by the native page owner later in this
        # render. Do not apply an older read (or native insertion) before that
        # exact mounted control commits its newly delivered routing decision.
        # A stale widget from another source/canonical class has no authority.
        source = content.source
        p = evidence_key + "_" + source.id
        previous = st.session_state.get(p + "_canonical_view")
        delivered = st.session_state.get(p + "_classification")
        return (st.session_state.get(prefix + "_source_active_selected") == source.id
                and previous is not None and previous.id == source.id
                and previous.sha256 == source.sha256
                and previous.classification == source.classification
                and delivered in sources.CLASSIFICATIONS
                and delivered != source.classification)

    def correction_key(role):
        return (local_key + "_page_destination_" + role.source_id + "_" +
                str(role.page) + "_" + role.page_sha256)

    def reader_corrections():
        result = {}
        for content in contents:
            if content.source.id not in picked_ids:
                continue
            for number in range(1, len(content.source.page_texts) + 1):
                role = classify_page(content, number)
                if role.ambiguous:
                    chosen = st.session_state.get(correction_key(role), "")
                    if chosen in role.destinations:
                        result[(role.source_id, role.page, content.source.sha256)] = chosen
        return result

    def accepted_page_pairs():
        return tuple(sorted(included_pages(blocks)))

    def activity_input(content):
        # The one managed intake also accepts sources for other sections.
        # Their extracted operational values must not become Activity prose
        # merely because Activity owns the shared source controls.
        # This is the paid-reader gate: only these classifications may
        # start a paid reading.
        if not managed:
            return True
        if _classification_delivery_pending(content):
            return False
        return (content.source.classification in {
            "Vendor service", "CMMS export", "Improvement / training photo",
        } or any("activity_summary" in classify_page(content, n).destinations
                 for n in range(1, len(content.source.page_texts) + 1)))

    def native_input(content):
        # Native (free) plain-text merge into Activity. Reference-only
        # sources auto-merge here, as they did under the pre-Oct-22
        # blocklist rule; the paid-reader gate above stays unchanged, so
        # Reference-only never starts a paid reading.
        if not managed:
            return True
        if _classification_delivery_pending(content):
            return False
        return content.source.classification in {
            "Vendor service", "CMMS export", "Improvement / training photo",
            "Reference only",
        }

    def read_target():
        eligible = tuple(c for c in contents if c.source.id in picked_ids and activity_input(c))
        return {"context": context, "files": _signature(tuple((c.source.filename, c.source.id) for c in eligible)),
                "sources": tuple(c.source.fingerprint for c in eligible),
                "corrections": tuple(sorted((*key, choice) for key, choice in reader_corrections().items())),
                "accepted_pages": accepted_page_pairs(),
                "revision": st.session_state.get(prefix + "_revision", 0)}

    def read_request():
        return dict(read_target(), token=st.session_state.setdefault(local_key + "_read_cycle", uuid4().hex))

    def shared_base_matches(target):
        saved = library.load_snapshot(profile.contract, profile.key, period)
        return target["revision"] == (saved.revision if saved else 0)

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
        if not job:
            return
        if job.get("request") != read_target():
            st.session_state.pop(local_key + "_job", None)
            job["future"].cancel()
            st.session_state[local_key + "_error"] = "The report or selected files changed. The earlier reading was not applied; review the current files before reading again."
            return
        if not job["future"].done():
            return
        st.session_state.pop(local_key + "_job", None)
        try:
            if not shared_base_matches(job["request"]):
                raise ValueError("A newer shared report was saved. The earlier reading was not applied; compare the shared version before reading again.")
            value = job["future"].result()
            current = additions.get(destination, blocks.get(destination))
            from app.monthly_report_guided import _pending_rich_text_edit
            if current is not None and (current.fingerprint != job.get("baseline")
                                        or _pending_rich_text_edit(prefix, current)):
                st.session_state[local_key + "_pending"] = (job, value)
                raise ValueError("New source suggestions are ready. Your edits were kept; add the suggestions below when ready.")
            coverage_mode = isinstance(value, dict) and isinstance(value.get("coverage"), list)
            if coverage_mode:
                result, pages, accepted, failed, visually_skipped = structured.reader_coverage_update(
                    job["contents"], destination, value, current,
                    table_columns=job.get("table_columns"),
                    corrections=job.get("corrections"),
                    accepted_pages=job.get("accepted_pages", ()), profile=profile, period=period)
                _, oversized, eligible = structured.reader_page_plan(
                    job["contents"], destination, profile=profile,
                    table_columns=job.get("table_columns"), period=period,
                    corrections=job.get("corrections"),
                    accepted_pages=job.get("accepted_pages", ()))
                earlier = st.session_state.get(local_key + "_coverage", {})
                if earlier.get("target") != job["request"]:
                    earlier = {}
                processed = set(earlier.get("processed", ())) | set(accepted)
                skipped = set(earlier.get("skipped", ())) | set(oversized) | set(visually_skipped)
                all_pages = set(earlier.get("eligible", ())) | set(eligible)
                # A missing receipt is an unresolved page, not a silent success.
                failed_pages = (set(earlier.get("failed", ())) | set(failed)
                                | (all_pages - processed - skipped)) - processed - skipped
                coverage_state = {
                    "target": job["request"], "eligible": tuple(sorted(all_pages)),
                    "processed": tuple(sorted(processed)), "skipped": tuple(sorted(skipped)),
                    "failed": tuple(sorted(failed_pages)),
                }
                st.session_state[local_key + "_coverage"] = coverage_state
            else:
                result, pages = structured.reader_update(job["contents"], destination, value, current,
                    table_columns=job.get("table_columns"),
                    corrections=job.get("corrections"),
                    accepted_pages=job.get("accepted_pages", ()), profile=profile, period=period)
            prepared = ()
            if destination == "activity_summary" and pages:
                selected = []
                for content in job["contents"]:
                    source = next((item.source for item in contents
                                   if item.source.id == content.source.id), content.source)
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
                changed = {content.source.id: content for content in selected}
                contents = tuple(changed.get(content.source.id, content) for content in contents)
                st.session_state[evidence_key] = contents
            if coverage_mode:
                # A validated image-page inclusion updates the source fingerprint.
                # Rebind receipts to the resulting current scope, not stale job input.
                coverage_state["target"] = read_target()
                st.session_state[local_key + "_coverage"] = coverage_state
            additions[destination] = result
            additions.update({block.key: block for block in prepared})
            remember(result, contents)
            notices = tuple(value.get("notices", ())) + structured.reader_page_notices(
                job["contents"], destination, value)
            finished = set(st.session_state.get(local_key + "_completed_ids", ()))
            if coverage_mode:
                seen = processed | skipped
                for content in job["contents"]:
                    if all(ref in seen for ref in all_pages if ref[0] == content.source.id):
                        finished.add(content.source.id)
                remaining = all_pages - seen
                if remaining:
                    st.session_state.pop(local_key + "_completed_read", None)
                    sources_by_id = {c.source.id: c.source.filename for c in job["contents"]}
                    labels = [f"{sources_by_id.get(sid, 'Source')} page {n}"
                              for sid, n in sorted(remaining)]
                    notices += ("Document reader: " + str(len(remaining))
                                + " pages still need reading. Retry only those pages: "
                                + ", ".join(labels[:8])
                                + (" (and more)" if len(labels) > 8 else "") + ".",)
                else:
                    st.session_state[local_key + "_completed_read"] = read_target()
            else:
                finished.update(content.source.id for content in job["contents"])
                st.session_state[local_key + "_completed_read"] = read_target()
            st.session_state[local_key + "_completed_ids"] = tuple(sorted(finished))
            st.session_state[local_key + "_messages"] = notices
            st.session_state.pop(local_key + "_error", None)
            if coverage_mode and remaining:
                st.session_state[local_key + "_error"] = "Some reading chunks failed; accepted pages remain saved in this draft."
            # Cache only validated results. A cache failure must never erase
            # applied chunks or automatically repeat a paid request.
            cache_safe = (not coverage_mode or
                          (bool(accepted) or not remaining) and
                          not any(r.get("status") == "processed"
                                  and any((p[0], p[1]) in failed_pages for p in r.get("pages", ()))
                                  for r in value["coverage"]))
            if not job.get("cached") and cache_safe:
                try:
                    earlier_cached = ai.cached(profile, "section_upload", job["digest"]) if coverage_mode else None
                    safe_value = (structured.merge_reader_coverage(earlier_cached, value)
                                  if coverage_mode else value)
                    ai.save_cache(profile, "section_upload", job["digest"], safe_value)
                except (ValueError, OSError) as exc:
                    st.session_state[local_key + "_error"] = "The reading is ready, but its reuse cache could not be saved: " + str(exc)
        except ValueError as exc:
            st.session_state[local_key + "_error"] = str(exc)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Monthly section reader failed")
            st.session_state[local_key + "_error"] = (
                "The document reader could not finish. Your uploaded text is kept; "
                "retry reading or edit the section below.")

    def render_current_source_details():
        nonlocal contents
        owned = set(st.session_state.get(local_key + "_native_ids", ()))
        owned.update(st.session_state.get(local_key + "_completed_ids", ()))
        updated = []
        for content in contents:
            if content.source.id in owned:
                source = render_source_details(
                    content.source, profile, local_key + "_" + content.source.id, field)
                content = replace(content, source=source)
            updated.append(content)
        contents = tuple(updated)
        st.session_state[evidence_key] = contents

    # Settle delivered uploader bytes before checking an asynchronous result:
    # an old completed read must never apply in the same render that replaces
    # its source with different bytes.
    if picked and st.session_state.get(local_key + "_read") != signature:
        contents, messages = sources.ingest_batch(profile, picked, contents)
        st.session_state[evidence_key] = contents
        st.session_state[local_key + "_messages"] = messages
    from app.monthly_report_source_recovery_ui import render_failed_file_retries
    retried = render_failed_file_retries(profile, period,
        st.session_state.get(prefix + "_revision", 0), local_key, picked, contents,
            messages=st.session_state.get(local_key + "_messages", ()))
    if retried is not None:
        contents, messages, _ = retried
        st.session_state[evidence_key] = contents
        st.session_state[local_key + "_messages"] = tuple(messages)
    complete_finished_job()
    # Remember a real empty selection, too. Remove does not clear the browser's
    # uploader; only clearing/reselecting may re-ingest those unchanged bytes.
    st.session_state[local_key + "_read"] = signature
    processed = set(st.session_state.get(local_key + "_native_ids", ()))
    fresh = tuple(c for c in contents if c.source.id in picked_ids
                  and c.source.id not in processed and native_input(c))
    if fresh:
        additions[destination] = structured.native_update(
            fresh, destination, additions.get(destination, blocks.get(destination)),
            table_columns=table_columns)
        remember(additions[destination], contents)
        st.session_state[local_key + "_native_ids"] = tuple(processed | {c.source.id for c in fresh})
    # A successful reading consumed these unchanged source bytes. Saving a
    # shared version or editing its human wording must not replay its cached
    # contribution; only new selected files need another reading.
    completed_ids = set(st.session_state.get(local_key + "_completed_ids", ()))
    scoped = tuple(c for c in contents if c.source.id in picked_ids
                   and c.source.id not in completed_ids and activity_input(c))
    for notice in structured.reader_notices(scoped, destination):
        st.warning(notice)
    scoped = structured.reader_sources(scoped, destination)
    # Multiple positive section headings require one explicit page decision.
    # This never changes original source type, page reviews or report content.
    for content in scoped:
        for number in range(1, len(content.source.page_texts) + 1):
            role = classify_page(content, number)
            if not role.ambiguous or destination not in role.destinations:
                continue
            st.caption(content.source.filename + " · page " + str(number) +
                       " · " + role.rule + ": " + ", ".join(role.destinations))
            st.selectbox("Choose destination for this ambiguous page",
                         ("", *role.destinations),
                         format_func=lambda name: name or "Keep out of external reading",
                         key=correction_key(role))
    corrections = reader_corrections()
    accepted_pages = accepted_page_pairs()
    eligible = set(choose_reader_pages(
        profile, scoped, destination, period=period, corrections=corrections,
        accepted_pages=accepted_pages,
        native_mapped=structured._native_reader_page_pairs(scoped, destination, table_columns)))
    skipped = sum(len(c.source.page_texts) for c in scoped) - len(eligible)
    if skipped:
        st.caption(f"{skipped} source page(s) are not sent to the document reader: "
                   "already accepted, native mapped, hidden worksheet, different section, "
                   "unrelated site/month or awaiting destination correction. "
                   "Originals remain available.")
    scoped = tuple(c for c in scoped if any((c.source.id, n) in eligible
                   for n in range(1, len(c.source.page_texts) + 1)))
    target = read_target()
    digest = ai.digest(("section-upload-v6", destination, tuple(table_columns or ()),
                        sorted(eligible), target["corrections"], accepted_pages))
    pending = st.session_state.get(local_key + "_pending")
    if pending and pending[0].get("request") != target:
        st.session_state.pop(local_key + "_pending", None)
        st.session_state.pop(local_key + "_error", None)
        pending = None
    completed = st.session_state.get(local_key + "_completed_read") == target
    if (scoped and not completed and not pending and local_key + "_job" not in st.session_state
            and st.session_state.get(local_key + "_cache_checked") != target):
        st.session_state[local_key + "_cache_checked"] = target
        try:
            cached = ai.cached(profile, "section_upload", digest)
            if cached is not None:
                from concurrent.futures import Future
                future = Future()
                future.set_result(cached)
                current = additions.get(destination, blocks.get(destination))
                st.session_state[local_key + "_job"] = {
                    "future": future, "contents": scoped, "digest": digest,
                    "baseline": current.fingerprint if current else None,
                    "table_columns": table_columns, "request": target,
                    "corrections": corrections, "accepted_pages": accepted_pages,
                    "token": uuid4().hex, "cached": True}
        except (ValueError, OSError) as exc:
            st.session_state[local_key + "_error"] = str(exc)
    submitted = st.session_state.pop(local_key + "_read_request", None)
    if submitted is not None:
        if submitted != read_request() or not scoped:
            st.warning("The report or selected files changed before reading started. Nothing was sent. Review the current files and select Read selected files.")
        elif local_key + "_job" not in st.session_state and not completed:
            st.session_state[local_key + "_read_cycle"] = uuid4().hex
            try:
                if not shared_base_matches(target):
                    raise ValueError("A newer shared report was saved before reading started. Nothing was sent. Compare the shared version and continue with your draft before reading again.")
                if testing.scope() is not None:
                    raise ValueError("External reading is off in isolated testing. Native extracted text and manual editing remain available.")
                if not ai.configured():
                    raise ValueError("The document reader is not configured. Native extracted text and manual editing remain available.")
                def prepare():
                    coverage = st.session_state.get(local_key + "_coverage", {})
                    if coverage.get("target") == target:
                        _, _, eligible_pages = structured.reader_page_plan(
                            scoped, destination, profile=profile,
                            table_columns=table_columns, period=period,
                            corrections=corrections, accepted_pages=accepted_pages)
                        complete = set(coverage.get("processed", ())) | set(coverage.get("skipped", ()))
                        pending_pages = tuple(ref for ref in eligible_pages if ref not in complete)
                        payloads = structured.reader_batches(
                            profile, scoped, destination, table_columns=table_columns,
                            page_refs=pending_pages, period=period, corrections=corrections,
                            accepted_pages=accepted_pages)
                    else:
                        payloads = structured.reader_batches(
                            profile, scoped, destination, table_columns=table_columns,
                            period=period, corrections=corrections,
                            accepted_pages=accepted_pages)
                    if not payloads:
                        # Oversized-only evidence must still acquire a visible
                        # manual-review receipt, without a paid model request.
                        _, oversized, eligible_pages = structured.reader_page_plan(
                            scoped, destination, profile=profile,
                            table_columns=table_columns, period=period,
                            corrections=corrections, accepted_pages=accepted_pages)
                        if not eligible_pages or set(oversized) != set(eligible_pages):
                            raise ValueError("No unmapped eligible pages remain for external reading.")
                    if len(payloads) > ai.MAX_CALLS:
                        raise ValueError("These files require more than 80 bounded reading requests. Select fewer sources; no requests were spent.")
                    for payload in payloads:
                        refs, _, unavailable = structured._payload_pages(payload)
                        if refs and set(refs).issubset(unavailable):
                            continue
                        ai.reserve_call(profile, period)
                    return payloads
                future = start_receipt(prepare, structured.read_batches)
                if future is None:
                    raise ValueError("Other document readings are running. Your extracted text is kept; retry reading when they finish.")
                current = additions.get(destination, blocks.get(destination))
                st.session_state[local_key + "_job"] = {
                    "future": future, "contents": scoped, "digest": digest,
                    "baseline": current.fingerprint if current else None,
                    "table_columns": table_columns, "request": target,
                    "corrections": corrections, "accepted_pages": accepted_pages,
                    "token": uuid4().hex}
                st.session_state.pop(local_key + "_error", None)
            except (ValueError, OSError, RuntimeError) as exc:
                st.session_state[local_key + "_error"] = str(exc)
    for message in st.session_state.get(local_key + "_messages", ()):
        st.warning(message)
    # Consume submitted item-specific scope before deriving its totals/action.
    # Otherwise one successful form submit leaves the old disabled action and
    # stale source revision on screen until an unrelated second rerun.
    if not managed:
        render_current_source_details()
        if destination == "activity_summary":
            render_workorder_metrics(profile, period, prefix, contents, blocks, additions=additions)
    pending = st.session_state.get(local_key + "_pending")
    if pending and st.button("Add new source suggestions to my edits", key=local_key + "_accept_suggestions_" + pending[0]["token"]):
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
    coverage = st.session_state.get(local_key + "_coverage", {})
    if coverage.get("target") == read_target():
        st.caption("Document reader coverage: "
                   + str(len(coverage["processed"])) + "/" + str(len(coverage["eligible"]))
                   + " pages processed; " + str(len(coverage["skipped"]))
                   + " skipped for manual review; " + str(len(coverage["failed"]))
                   + " failed/retryable. Original uploads and accepted edits are retained.")
        if coverage["skipped"]:
            source_names = {c.source.id: c.source.filename for c in contents}
            labels = [f"{source_names.get(sid, 'Source')} page {n}"
                      for sid, n in coverage["skipped"]]
            st.warning("Manual source review needed for unreadable/oversized pages: "
                       + ", ".join(labels[:8]) + (" (and more)" if len(labels) > 8 else "") + ".")
    completed = st.session_state.get(local_key + "_completed_read") == read_target()
    if local_key + "_job" in st.session_state:
        _section_read_progress(local_key)
    elif scoped and not completed and local_key + "_pending" not in st.session_state:
        if testing.scope() is not None:
            st.caption("External reading is off in isolated testing. Native extracted text and manual editing remain available.")
        elif ai.configured():
            st.caption("Reading sends these selected files to the external document reader and uses this report's reading allowance. Charges may apply.")
            request = read_request()
            label = "Retry reading uploaded files" if local_key + "_error" in st.session_state else "Read selected files"
            st.button(label, key=local_key + "_read_selected_" + _signature(request),
                      on_click=_queue_section_read, args=(local_key, request))
        else:
            st.caption("The external reader is not configured. Any native text was kept below; edit directly or use Copilot.")
    return tuple(content.source for content in contents), additions, {}
