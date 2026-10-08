"""Upload a report, confirm its sites, then review recognizable report sections."""

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

import streamlit as st

from app import contracts, monthly_report_library as library
from app.config import FACILITIES
from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_editor import _grid, _key, _signature
from app.monthly_report_import import imported_draft
from app.monthly_report_import_ui import _stage
from app.monthly_report_model import Facility, ReportProfile, ReportTable, default_sections
from app.monthly_report_sections import section_reviews, table_without_prices, build_section_import, default_slot, apply_section_omissions
from app.monthly_report_setup import design_profile, merge_drafts, item_findings
from app.monthly_report_section_help import section_help


def plan_signature(plan):
    value = {k: v for k, v in plan.items() if k not in ("new_assets", "preserved_assets", "approved", "approval_stamp")}
    value["new_assets"] = [(slot, hashlib.sha256(image.data).hexdigest()) for slot, image in plan.get("new_assets", ())]
    value["preserved_assets"] = [(slot, hashlib.sha256(image.data).hexdigest()) for slot, image in plan.get("preserved_assets", ())]
    return _signature(value)


def _site_options(contract):
    from app.monthly_report_directory import available_sites, load_directory
    directory = load_directory(contract)
    if contract != contracts.RRH_CONTRACT:
        catalog = tuple(Facility(_key(title), title) for title in contracts.sites_for_contract(contract))
        return available_sites(catalog, directory)
    # Explicit owner-confirmed alias relationship. Never group sites by address
    # or guess regional membership from a title or geographic location.
    result = []
    for key, value in FACILITIES.items():
        if key == "st_marys" and "unity_specialty" in FACILITIES:
            continue
        aliases = (FACILITIES["st_marys"]["name"],) if key == "unity_specialty" and "st_marys" in FACILITIES else ()
        result.append(Facility(key, value["name"], aliases))
    return available_sites(result, directory)


def _identity(contract, prepared, prefix, field, state):
    st.subheader("1. Who is this report for?")
    if state:
        profile = state.profile
        st.write(profile.title + " · " + "; ".join(f.title for f in profile.facilities))
        actor = st.text_input("Your name", key=field(prefix + "_actor", prepared))
        return profile, actor, [] if actor.strip() else ["Enter your name."]
    options = {f.key: f for f in _site_options(contract)}
    selected = st.multiselect("Which sites does this report cover?", list(options),
                              format_func=lambda k: options[k].title + (" (also " + ", ".join(options[k].aliases) + ")" if options[k].aliases else ""),
                              key=field(prefix + "_sites", []), help="Select only the sites in this report. You can make separate reports for other sites on the same contract.")
    custom = st.text_input("Site not listed? Add its name here", key=field(prefix + "_custom_site", ""),
                           help="For more than one missing site, separate their names with a semicolon.")
    facilities = tuple(options[k] for k in selected) + tuple(Facility(_key(v.strip()), v.strip()) for v in custom.split(";") if v.strip())
    scope_label = st.radio("This report covers", ["One site", "A group of sites", "A region"], key=field(prefix + "_scope", "One site"), horizontal=True)
    scope = {"One site": "individual", "A group of sites": "multi_site", "A region": "regional"}[scope_label]
    actor = st.text_input("Your name", key=field(prefix + "_actor", prepared), help="Shown as the report preparer and recorded when you save.")
    seed_title = facilities[0].title if len(facilities) == 1 else " / ".join(f.title for f in facilities)[:160]
    with st.expander("Report name and other names for these sites (optional)"):
        title = st.text_input("Report name", key=field(prefix + "_title_" + _signature(seed_title), seed_title),
                              help="A name you will recognize next month. The month and year are added automatically.")
        amended = []
        for facility in facilities:
            aliases = st.text_input("Other names for " + facility.title, key=field(prefix + "_aliases_" + facility.key, "; ".join(facility.aliases)))
            amended.append(replace(facility, aliases=tuple(v.strip() for v in aliases.split(";") if v.strip())))
        facilities = tuple(amended)
    missing = []
    if not facilities:
        missing.append("Select a site, or type its name in ‘Site not listed?’.")
    if scope == "individual" and len(facilities) > 1:
        missing.append("For several sites, choose ‘A group of sites’ or ‘A region’.")
    if not title.strip():
        missing.append("Give the report a name in the optional report-name box.")
    if not actor.strip():
        missing.append("Enter your name.")
    candidate = None
    if not missing:
        try:
            candidate = ReportProfile(contract, _key(title), title.strip(), facilities, scope)
        except ValueError:
            missing.append("A site was selected twice or an alternate name belongs to two sites. Keep one entry for each actual site.")
    return candidate, actor, missing


def _replacement_pictures(section, p, plan):
    """Keep each replacement tied to a named report part across reruns."""
    if section.key == "cover":
        labels = {"cover_photo": "New cover photograph", "client_logo": "New client logo", "brand_logo": "New ENFRA logo"}
        st.caption("Add only what you want to change. Each new picture replaces the selected picture for that purpose; other cover details stay as they are.")
    elif section.key == "organization":
        labels = {"org_chart": "New organization chart", "business_hours_workflow": "New daytime outage procedure", "after_hours_workflow": "New after-hours outage procedure", "contact_matrix": "New facility contact page"}
        st.caption("Add only the parts that changed. Leave out the old picture or uncheck its original page when replacing it. Other selected pages stay in the report.")
    else:
        labels = {{"activity": "improvements", "training": "training_summary", "maintenance": "vendor_reports", "water": "water_reports"}.get(section.key, default_slot(section.key)): section_help(section.key).upload_label}
        st.caption("Choose “Leave out” on the old picture when replacing it. Complete vendor, chemical and MBCx files can be added in This month’s work after setup.")
    replacements = dict(plan.get("new_assets", ()))
    for slot, label in labels.items():
        upload = st.file_uploader(label, type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=p + "_replacement_" + slot, max_upload_size=30)
        if upload:
            try:
                replacements[slot] = normalize_report_image(upload.getvalue(), Path(upload.name).suffix, line_art=section.key == "organization" or slot.endswith("logo"))
            except (ValueError, OSError):
                st.error("This picture could not be read. Choose another image; your previous selection is retained.")
        if slot in replacements:
            st.image(replacements[slot].data, width="stretch", caption=label + " — included in this report")
    plan["new_assets"] = list(replacements.items())


def _section_card(section, path, inspection, period, prefix, field, plans, first):
    p = prefix + "_section_" + section.key
    old = plans.get(section.key, {})
    status = "Ready" if old.get("approved") else "Review"
    # Streamlit includes an expander's label in its identity, even with a key.
    # A changing "Ready" suffix would close it and discard its active widgets.
    box = st.expander(section.title, expanded=first, key=p + "_open", on_change="rerun")
    if not box.open:
        return
    with box:
        st.caption(status)
        guide = section_help(section.key)
        st.write(guide.guidance)
        actions = ["Keep and review", "Edit text or change pictures", "Leave this section out"]
        labels = dict(zip(actions, (guide.keep, guide.edit, "Leave this section out")))
        action = st.radio("What would you like to do?", actions, format_func=labels.get, key=field(p + "_action", old.get("action", actions[0])), horizontal=True)
        plan = {"key": section.key, "action": action, "target": section.key, "omit": action == actions[2], "selected": [], "texts": {}, "tables": {}, "destinations": {}, "new_assets": old.get("new_assets", []), "image_notes": dict(old.get("image_notes", {}))}
        blocking = []
        if plan["omit"]:
            st.caption("Left out of this draft only. The original and its contents will still be saved for reference.")
        else:
            from app.monthly_report_word_pages_ui import chart_page_review
            if chart_page_review(section, path, period, p, field, old, plan, blocking):
                _replacement_pictures(section, p, plan)
                _approve_plan(plan, p, field, old, plans, blocking)
                return
            items = list(section.items)
            if section.key == "cover":
                st.info(f"The cover will use the confirmed sites and {period.label}. Old cover dates and the old contents list are not reused.")
                # Logo/cover choices are visual; old cover prose cannot masquerade
                # as this month's activity. It remains in the retained original.
                items = [i for i in items if i.kind == "image" or i.suggested_slot == "footer_text"]
            elif section.key == "other":
                target = st.selectbox("Where should this content appear?", ["", *[s.key for s in default_sections()]],
                                      format_func=lambda k: next((s.title for s in default_sections() if s.key == k), "Choose a report section"), key=field(p + "_target", old.get("target", "")))
                plan["target"] = target
                if not target:
                    blocking.append("Choose a section above, or leave this additional content out of the draft.")
            texts = [i for i in items if i.kind == "text"]
            if texts:
                combined = old.get("texts", {}).get(texts[0].id, "\n\n".join(i.text for i in texts))
                text = st.text_area(guide.text_label, key=field(p + "_text", combined), height=200) if action == actions[1] else combined
                if action != actions[1]:
                    st.text(text[:14000])
                    if len(text) > 14000:
                        st.caption(f"Long text: choose ‘{guide.edit}’ above to review the full section.")
                if contains_price(text):
                    blocking.append(f"This text includes pricing. Choose ‘{guide.edit}’ above and remove the pricing before including it.")
                plan["selected"].append(texts[0].id)
                plan["texts"][texts[0].id] = text
                if section.key == "cover":
                    plan["destinations"][texts[0].id] = "footer_text"
                # All original paragraphs remain identifiable in the review record.
                plan["combined_text_ids"] = [i.id for i in texts]
                findings = tuple(dict.fromkeys(f for i in texts for f in item_findings(i, period) if f.startswith("Other-month")))
                if findings:
                    st.warning("Check older dates in this section. Keep valid ongoing history; update only the parts that refer to this month’s work.")
            for n, item in enumerate((i for i in items if i.kind == "table"), 1):
                table, removed = table_without_prices(item)
                table = old.get("tables", {}).get(item.id, table)
                if removed:
                    st.caption("Pricing columns were removed from this client-facing table. The original table is retained in the uploaded report.")
                if table:
                    st.write(f"Table {n}")
                    rows = [dict(zip(table.columns, r)) for r in table.rows]
                    if action == actions[1]:
                        rows = _grid(p + "_table_" + item.id, rows, num_rows="dynamic", hide_index=True)
                        table = ReportTable(table.columns, tuple(tuple("" if r.get(c) is None else str(r[c]) for c in table.columns) for r in rows))
                    else:
                        st.dataframe(rows[:300], hide_index=True)
                        if len(rows) > 300:
                            st.caption(f"Showing the first 300 rows. Choose ‘{guide.edit}’ above to inspect all rows.")
                    if table_has_pricing(table.columns, table.rows):
                        blocking.append(f"A table cell still contains pricing. Choose ‘{guide.edit}’ above and remove it.")
                    plan["tables"][item.id] = table
                    plan["selected"].append(item.id)
            from app.monthly_report_picture_cards import review_pictures
            review_pictures([i for i in items if i.kind == "image"], section.key,
                            path, p, prefix, field, old, plan, blocking)
            if action == actions[1] and section.key != "other":
                _replacement_pictures(section, p, plan)
            elif plan["new_assets"]:
                from app.monthly_report_sections import readable_label
                for slot, image in plan["new_assets"]:
                    st.image(image.data, width="stretch", caption="Your updated " + readable_label(slot).lower() + " is retained")
            if any(i.kind == "unsupported" for i in section.items):
                preserve_hint = "Open ‘Preview the original charts and contact lists’ above to preview complete pages. " if section.key == "organization" else ""
                st.warning("Some charts or artwork in the original Word file could not be displayed. " + preserve_hint + "If they cannot be kept clearly, add replacement pictures or explicitly leave them out. The original is retained.")
                options = ["Choose an option", "Continue without the content that could not be shown"]
                if section.key != "other":
                    options.insert(1, "I uploaded clear replacements")
                previous = old.get("unsupported_choice", "Choose an option")
                choice = st.radio("Some content could not be shown. How would you like to continue?", options,
                                  key=field(p + "_unsupported", previous if previous in options else options[0]))
                plan["unsupported_choice"] = choice
                plan["unsupported_reviewed"] = choice == "Continue without the content that could not be shown" or (choice == "I uploaded clear replacements" and bool(plan["new_assets"]))
                if not plan["unsupported_reviewed"]:
                    if section.key == "other":
                        blocking.append("Choose ‘Continue without the content that could not be shown’ to retain them only in the original. You can add clear replacement pictures to the appropriate report section after setup.")
                    else:
                        blocking.append(preserve_hint + f"To upload a replacement, choose ‘{guide.edit}’ above. Otherwise choose ‘Continue without the content that could not be shown’.")
        _approve_plan(plan, p, field, old, plans, blocking)


def _approve_plan(plan, p, field, old, plans, blocking):
    for message in blocking:
        st.error(message)
    stamp = plan_signature(plan)
    reviewed = st.checkbox("This section is ready — the selected content is relevant and contains no prices, legal-only pages or blank/signature-only pages", key=field(p + "_ready_" + stamp, old.get("approval_stamp") == stamp))
    plan["approved"] = reviewed and not blocking
    plan["approval_stamp"] = stamp if plan["approved"] else ""
    plans[plan["key"]] = plan
    if blocking:
        st.caption("Resolve the message above to finish this section.")


def render_section_setup(contract, period, prepared, field, *, state=None, identity=None,
                         working_draft=None, working_assets=(), working_revision=None):
    prefix = "report_setup_" + _signature((contract, state.profile.key if state else identity.key if identity else "new", period.key))
    st.subheader("Start with a report you already have")
    st.write("Upload an older report or a teammate’s unfinished report. Then review its sections below. Your original file will not be changed.")
    upload = st.file_uploader("Older or partially completed report", type=["docx"], max_upload_size=128, key=prefix + "_upload")
    if st.button("Analyze report", key=prefix + "_analyze", disabled=upload is None, type="primary"):
        try:
            with st.spinner("Finding report sections and pictures…"):
                staged = _stage(upload)
            old = st.session_state.get(prefix + "_stage")
            st.session_state[prefix + "_stage"] = staged
            if old and old[0]:
                old[0].cleanup()
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    if state:
        original = library.imported_original(contract, state.profile.key)
        if original and st.button("Open the saved original for section review", key=prefix + "_original"):
            from app.monthly_report_import import inspect_docx
            st.session_state[prefix + "_stage"] = (None, original, inspect_docx(original))
            st.rerun()
    staged = st.session_state.get(prefix + "_stage")
    if not staged:
        st.caption("DOCX up to 128 MB. After upload, you’ll see the report’s sections—not a list of document fragments.")
        return
    _, path, inspection = staged
    p = prefix + "_" + inspection.sha256[:16]
    if identity:
        candidate = identity
        st.write("Report sites: " + "; ".join(f.title for f in identity.facilities))
        actor = st.text_input("Your name", key=field(p + "_actor", prepared))
        missing = [] if actor.strip() else ["Enter your name."]
    else:
        candidate, actor, missing = _identity(contract, prepared, p, field, state)
    intent = "Content-based review"
    from app.monthly_report_setup import report_period_findings
    findings = report_period_findings(inspection, period)
    if findings["current"] and findings["older"]:
        message = "Some work refers to this month and some to other months. Parts of this report may already be updated."
    elif findings["older"]:
        message = "Some work refers to earlier months. Keep relevant ongoing history and update old monthly work."
    elif findings["current"]:
        message = "The report includes work dated this month. Check the sections for anything still needing an update."
    else:
        message = "The month is not clear from the readable work details. Review the sections before deciding what to keep."
    st.info(f"Preparing {period.label}. " + message + " An old cover never decides which work is kept.")
    if findings["images"]:
        st.caption("Check the embedded page previews too: nearby headings cannot establish an image’s service date. Uncertain content stays available until you decide.")
    st.subheader("2. Review your report sections")
    st.write("Open a section, check what is already there, and choose whether to keep or change it. Mark it ready when you’re finished. You can add this month’s vendor and water-treatment files in the next step.")
    sections = section_reviews(inspection)
    plans = st.session_state.setdefault(p + "_section_plans", {})
    for index, section in enumerate(sections):
        _section_card(section, path, inspection, period, p, field, plans, index == 0)
    remaining = [s.title for s in sections if not plans.get(s.key, {}).get("approved")]
    st.subheader("3. Continue when you’re ready")
    todo = [*missing, *(["Review these sections: " + "; ".join(remaining) + "."] if remaining else [])]
    for message in todo:
        st.info(message)
    if not todo:
        st.success("Your sites and sections are ready. Continue to add this month’s files and finish the report.")
    st.caption("Saving remembers this design and its site information for next month. Saved content is shared in this public internal-testing app. Your entered name records the change; it is not a login.")
    fingerprint = _signature((asdict(candidate) if candidate else None, actor, [plan_signature(plan) for plan in plans.values()], intent, state.revision if state else 0))
    confirmed = st.checkbox("Save this report and its reusable design for these sites", key=p + "_save_ok_" + fingerprint)
    if st.button("Continue to this month’s updates", key=p + "_save", type="primary", disabled=bool(todo) or not (candidate and confirmed)):
        try:
            with st.spinner("Saving your report and its reusable design…"):
                mapped, mappings = build_section_import(path, inspection, tuple(plans[s.key] for s in sections))
                profile = candidate if state else design_profile(candidate, inspection, mappings, mapped.overrides)
                draft = imported_draft(profile, period, actor, mapped)
                # A replacement may be the only selected content in a section.
                present = {s.key for s in draft.sections if s.included}
                profile = replace(profile, excluded_sections=tuple(s for s in profile.excluded_sections if s not in present))
                draft = replace(draft, profile=profile)
                current = library.load_snapshot(contract, profile.key, period) if state else None
                prior_import = library.load_imported_draft(contract, profile.key) if state else None
                base = current.draft if current else None
                if working_draft is not None:
                    if (working_draft.profile.contract, working_draft.profile.key, working_draft.period) != (contract, profile.key, period):
                        raise ValueError("The open draft belongs to different sites or a different month. Reopen the intended report before importing.")
                    if working_revision != (current.revision if current else 0):
                        raise ValueError("Another version was saved while you were working. Compare and accept that version using Save progress before adding this report. Your open draft and upload are preserved.")
                    base = working_draft
                elif prior_import and prior_import.period == period and (not current or library.imported_snapshot_revision(contract, profile.key) == current.revision):
                    base = merge_drafts(base, prior_import)
                draft = merge_drafts(base, draft)
                draft = apply_section_omissions(draft, plans.values())
                review = {"sha256": inspection.sha256, "intent": intent, "period": period.key, "image_review_scope": p,
                          "items": [asdict(i) for i in inspection.items],
                          "section_plans": [{k: v for k, v in plan.items() if k not in ("new_assets", "preserved_assets")} for plan in plans.values()]}
                # Normalize dataclass table values for the JSON audit record.
                review["section_plans"] = [dict(plan, tables={k: asdict(v) for k, v in plan.get("tables", {}).items()}) for plan in review["section_plans"]]
                library.save_report_setup(profile, draft, path, review, assets=tuple(dict((*working_assets, *mapped.assets)).items()),
                                          expected_revision=state.revision if state else 0, actor=actor, confirmed=True,
                                          snapshot_revision=current.revision if current else 0)
                st.session_state["report_resume_import"] = (contract, profile.key, period.key)
                st.session_state["report_setup_done"] = profile.key
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
