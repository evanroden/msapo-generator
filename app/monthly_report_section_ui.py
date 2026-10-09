"""Upload a report, confirm its sites, then review recognizable report sections."""

import hashlib
from dataclasses import asdict, replace
from pathlib import Path

import streamlit as st

from app import contracts
from app import monthly_report_library as library
from app.config import FACILITIES
from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_editor import _grid, _key, _signature
from app.monthly_report_import import imported_draft
from app.monthly_report_import_ui import _stage
from app.monthly_report_model import (
    Facility,
    ReportProfile,
    ReportTable,
    default_sections,
)
from app.monthly_report_section_help import section_help
from app.monthly_report_sections import (
    default_slot,
    section_reviews,
    table_without_prices,
)
from app.monthly_report_setup import design_profile, item_findings, merge_drafts


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
    try:
        facilities = tuple(options[k] for k in selected) + tuple(Facility(_key(v.strip()), v.strip()) for v in custom.split(";") if v.strip())
        # Validate before rendering widgets keyed by facility identity, so a
        # repeated custom site remains editable instead of crashing every run.
        if facilities:
            ReportProfile(contract, "selection", "Selected sites", facilities,
                          "individual" if len(facilities) == 1 else "multi_site")
    except ValueError:
        message = "A site was selected twice, shares an alternate name, or has no letters/numbers. Keep one entry per actual site and correct the added site name above."
        st.warning(message)
        return None, prepared, [message]
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
        st.caption("Add only the parts that changed. A new picture replaces all previous pictures for that part; the other organization pages stay in the report.")
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
        plan = {"key": section.key, "action": action, "target": section.key, "omit": action == actions[2], "selected": [], "texts": {}, "tables": {}, "destinations": {}, "new_assets": old.get("new_assets", []), "image_notes": dict(old.get("image_notes", {})), "automatic": False}
        blocking = []
        if plan["omit"]:
            st.caption("Left out of this draft only. The original and its contents will still be saved for reference.")
        else:
            from app.monthly_report_word_pages_ui import chart_page_review
            if chart_page_review(section, path, period, p, field, old, plan, blocking):
                if action == actions[1]:
                    _replacement_pictures(section, p, plan)
                elif plan["new_assets"]:
                    from app.monthly_report_sections import readable_label
                    for slot, image in plan["new_assets"]:
                        st.image(image.data, width="stretch", caption="Your updated " + readable_label(slot).lower() + " is retained")
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
                if table:
                    from app.monthly_report_table_review_ui import review_table_headings
                    table = review_table_headings(table, p + "_table_" + item.id, field)
                if removed:
                    st.caption("Pricing columns were removed from this client-facing table. The original table is retained in the uploaded report.")
                if table:
                    st.write(f"Table {n}")
                    rows = [dict(zip(table.columns, r)) for r in table.rows]
                    if action == actions[1]:
                        rows = _grid(p + "_table_" + item.id + "_" + _signature(table.columns), rows, num_rows="dynamic", hide_index=True)
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
    st.subheader("Start with any report from this contract")
    st.caption("Use an earlier month, another site, or a report already underway. We’ll identify its sites and dates and bring across the relevant content.")
    upload = st.file_uploader("Starting report", type=["docx"], max_upload_size=128, key=prefix + "_upload")
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
        st.caption("Word DOCX, up to 128 MB. Your original file is retained.")
        return False
    _, path, inspection = staged
    p = prefix + "_" + inspection.sha256[:16]
    if identity:
        candidate = identity
        st.write("Report sites: " + "; ".join(f.title for f in identity.facilities))
        actor = st.text_input("Your name", key=field(p + "_actor", prepared))
        missing = [] if actor.strip() else ["Enter your name."]
    else:
        candidate, actor, missing = _identity(contract, prepared, p, field, state)
    if not candidate:
        for message in missing:
            st.info(message)
        return True
    from app.monthly_report_start_import import (
        analyze_starting_report,
        automatic_section_plans,
        build_starting_import,
    )
    profiles = library.list_profiles(contract)
    known_sites = {f.key: f for f in (*_site_options(contract), *(f for profile in profiles for f in profile.facilities), *candidate.facilities)}
    analysis = analyze_starting_report(inspection, candidate, period, known_sites.values(), known_profiles=profiles)
    if analysis.site_relation == "unknown":
        st.info("The starting report does not clearly name its sites. Confirm them once so another site's contacts and work are not copied into this report.")
        source_keys = st.multiselect("Sites shown in the starting report", list(known_sites),
                                    format_func=lambda key: known_sites[key].title,
                                    key=field(p + "_source_sites", []))
        with st.expander("A source site is not listed"):
            source_names = st.text_input("Source site name", key=field(p + "_source_site_name", ""),
                                         help="For several source sites, separate the names with semicolons.")
        confirmed_sites = [known_sites[key] for key in source_keys]
        for name in (n.strip() for n in source_names.split(";")):
            if name:
                if not _key(name):
                    st.error("Enter the source site's name using letters or numbers.")
                    return True
                confirmed_sites.append(next((f for f in known_sites.values() if name.casefold() in
                                              {n.casefold() for n in (f.title, *f.aliases)}), Facility(_key(name), name)))
        if not confirmed_sites:
            return True
        analysis = analyze_starting_report(inspection, candidate, period, known_sites.values(),
                                          confirmed_sites=tuple({f.key: f for f in confirmed_sites}.values()))
    source_names = "; ".join(site.title for site in analysis.source_sites)
    st.caption("Starting report: " + source_names + (f" · {analysis.source_period[0]}-{analysis.source_period[1]:02d}" if analysis.source_period else " · source month not stated"))
    if analysis.site_relation == "other":
        st.info("This report covers different sites. Its layout and table headings will be reused; your selected sites keep their own contacts, photos and work.")
    elif analysis.older_items:
        st.info(f"Preparing {period.label}. Earlier monthly work stays in the original. Standing information and any work already updated for this month are carried across.")
    else:
        st.info(f"Preparing {period.label}. Existing work is carried across so you can finish the remaining sections.")
    from app.monthly_report_branding import find_logo, load_branding
    branding = load_branding()
    preferred_logos = tuple(key for key in ("brand_logo", "client_logo")
                            if (state and state.block(key) and state.block(key).asset_hashes)
                            or (branding and find_logo(contract, brand=key == "brand_logo", state=branding)))
    from app.monthly_report_designs import source_for
    native_design = source_for(candidate) is not None
    seed = automatic_section_plans(inspection, analysis, preferred_logos=preferred_logos, native_design=native_design)
    seed_signature = _signature((analysis, preferred_logos, native_design))
    if st.session_state.get(p + "_analysis_signature") != seed_signature:
        st.session_state[p + "_section_plans"] = seed
        st.session_state[p + "_analysis_signature"] = seed_signature
    intent = "Automatic starting report"
    sections = section_reviews(inspection)
    plans = st.session_state.setdefault(p + "_section_plans", {})
    questions = [section for section in sections if seed[section.key].get("questions")]
    if questions:
        st.subheader("A few details need a check")
        for index, section in enumerate(questions):
            for message in seed[section.key]["questions"]:
                st.caption(section.title + ": " + message)
            _section_card(section, path, inspection, period, p, field, plans, index == 0)
    with st.expander("Review what will be carried across (optional)", key=p + "_check_import", on_change="rerun") as details:
        if details.open:
            for section in sections:
                if section not in questions:
                    st.caption(section.title + (" · ready" if plans[section.key].get("selected") else " · starts blank"))
    remaining = [s.title for s in sections if not plans.get(s.key, {}).get("approved")]
    todo = [*missing, *(["Review these sections: " + "; ".join(remaining) + "."] if remaining else [])]
    for message in todo:
        st.info(message)
    if not todo:
        st.success("Your sites and sections are ready. Continue to add this month’s files and finish the report.")
    st.caption("Saving remembers this design and its site information for next month. Saved content is shared in this public internal-testing app. Your entered name records the change; it is not a login.")
    if st.button("Continue to this month’s updates", key=p + "_save", type="primary", disabled=bool(todo) or not candidate):
        try:
            with st.spinner("Saving your report and its reusable design…"):
                mapped, mappings = build_starting_import(path, inspection, tuple(plans[s.key] for s in sections))
                profile = candidate if state else design_profile(candidate, inspection, mappings, mapped.overrides)
                profile = replace(profile, excluded_sections=())
                draft = imported_draft(profile, period, actor, mapped)
                draft = replace(draft, sections=tuple(replace(s, included=True) for s in draft.sections))
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
                # Existing reviewed logos belong to the selected sites/contract.
                # A starting report must not replace them with older artwork.
                assets = dict((*working_assets, *mapped.assets))
                blocks = {b.key: b for b in draft.blocks}
                for key in preferred_logos:
                    saved = state.block(key) if state else None
                    if saved and saved.asset_hashes and key not in blocks:
                        blocks[key] = saved
                        for reference in saved.asset_hashes:
                            assets[reference] = library.read_asset(contract, profile.key, reference)
                from app.monthly_report_branding import apply_defaults
                draft = apply_defaults(replace(draft, blocks=tuple(blocks.values()),
                                               sections=tuple(replace(s, included=True) for s in draft.sections)), assets)
                review = {"sha256": inspection.sha256, "intent": intent, "period": period.key, "image_review_scope": p,
                          "inferred_source": asdict(analysis),
                          "items": [asdict(i) for i in inspection.items],
                          "section_plans": [{k: v for k, v in plan.items() if k not in ("new_assets", "preserved_assets")} for plan in plans.values()]}
                # Normalize dataclass table values for the JSON audit record.
                review["section_plans"] = [dict(plan, tables={k: asdict(v) for k, v in plan.get("tables", {}).items()}) for plan in review["section_plans"]]
                library.save_report_setup(profile, draft, path, review, assets=tuple(assets.items()),
                                          expected_revision=state.revision if state else 0, actor=actor, confirmed=True,
                                          snapshot_revision=current.revision if current else 0)
                st.session_state["report_resume_import"] = (contract, profile.key, period.key)
                st.session_state["report_setup_done"] = profile.key
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    return True
