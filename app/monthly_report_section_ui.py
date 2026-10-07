"""Upload a report, confirm its sites, then review recognizable report sections."""

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

import streamlit as st

from app import contracts, monthly_report_library as library
from app.config import FACILITIES
from app.monthly_report_content_policy import contains_price, page_status, table_has_pricing
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_editor import _grid, _key, _signature
from app.monthly_report_import import imported_draft, read_import_image
from app.monthly_report_import_ui import _stage
from app.monthly_report_model import Facility, ReportProfile, ReportTable, default_sections
from app.monthly_report_sections import section_reviews, table_without_prices, build_section_import, default_slot, small_artwork, apply_section_omissions
from app.monthly_report_setup import design_profile, merge_drafts, item_findings


def plan_signature(plan):
    value = {k: v for k, v in plan.items() if k not in ("new_assets", "approved", "approval_stamp")}
    value["new_assets"] = [(slot, hashlib.sha256(image.data).hexdigest()) for slot, image in plan.get("new_assets", ())]
    return _signature(value)


def _site_options(contract):
    from app.monthly_report_directory import load_directory
    directory = load_directory(contract)
    if directory:
        return tuple(site.facility for site in directory.sites if site.active)
    if contract != contracts.RRH_CONTRACT:
        return tuple(Facility(_key(title), title) for title in contracts.sites_for_contract(contract))
    # Explicit owner-confirmed alias relationship. Never group sites by address
    # or guess regional membership from a title or geographic location.
    result = []
    for key, value in FACILITIES.items():
        if key == "st_marys" and "unity_specialty" in FACILITIES:
            continue
        aliases = (FACILITIES["st_marys"]["name"],) if key == "unity_specialty" and "st_marys" in FACILITIES else ()
        result.append(Facility(key, value["name"], aliases))
    return tuple(result)


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
        actions = ["Keep and review", "Edit text or change pictures", "Leave this section out"]
        action = st.radio("What would you like to do?", actions, key=field(p + "_action", old.get("action", actions[0])), horizontal=True)
        plan = {"key": section.key, "action": action, "target": section.key, "omit": action == actions[2], "selected": [], "texts": {}, "tables": {}, "destinations": {}, "new_assets": old.get("new_assets", []), "image_notes": dict(old.get("image_notes", {}))}
        blocking = []
        if plan["omit"]:
            st.caption("Left out of this draft only. The original and its contents will still be saved for reference.")
        else:
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
                text = st.text_area("Section text", key=field(p + "_text", combined), height=200) if action == actions[1] else combined
                if action != actions[1]:
                    st.text(text[:14000])
                    if len(text) > 14000:
                        st.caption("Long text: choose Edit to review the full section.")
                if contains_price(text):
                    blocking.append("This text includes pricing. Choose Edit and remove the pricing before including it.")
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
                            st.caption("Showing the first 300 rows. Choose Edit to inspect all rows.")
                    if table_has_pricing(table.columns, table.rows):
                        blocking.append("A table cell still contains pricing. Choose Edit and remove it.")
                    plan["tables"][item.id] = table
                    plan["selected"].append(item.id)
            images = [i for i in items if i.kind == "image"]
            if images:
                labels = {i.id: f"Picture / page {n}" + (" · small artwork" if small_artwork(i) else "") for n, i in enumerate(images, 1)}
                suggested = [i.id for i in images if not small_artwork(i)]
                kept = st.multiselect("Pictures and pages to include", list(labels), format_func=labels.get,
                                      key=field(p + "_pictures", old.get("picture_choices", suggested)), help="Uncheck old vendor pages, legal terms, blank/signature-only pages and every page showing a price. Unchecked pages remain in the original.")
                plan["picture_choices"] = kept
                if len(suggested) < len(images):
                    st.caption("Small icons and thin separator graphics start unchecked. You can select one if it is meaningful report content. All remain in the saved original.")
                shown = st.selectbox("Picture or page to view", list(labels), format_func=labels.get, key=field(p + "_preview", images[0].id))
                image = next(i for i in images if i.id == shown)
                preview = read_import_image(path, image, preview=True)
                st.image(preview.data, width=min(preview.width, 700))
                st.caption(f"{len(kept)} of {len(images)} pictures/pages selected. Check the actual pages; a stale cover does not mean the work on a page is old.")
                if section.key == "cover":
                    st.caption("Repeated page artwork is grouped here once. Choose the cover and logos you want to reuse; other artwork stays in the original.")
                    for slot, label in (("cover_photo", "Cover photograph"), ("client_logo", "Client logo"), ("brand_logo", "Brand logo")):
                        default = next((i.id for i in images if i.suggested_slot == "brand_logo"), "") if slot == "brand_logo" else ""
                        if "destinations" in old:
                            default = next((identity for identity, saved_slot in old["destinations"].items() if saved_slot == slot), "")
                        chosen = st.selectbox(label, ["", *labels], format_func=lambda v, labels=labels: labels.get(v, "None selected"), key=field(p + "_cover_" + slot, default))
                        if chosen and chosen in kept:
                            plan["selected"].append(chosen)
                            plan["destinations"][chosen] = slot
                    if len(plan["selected"]) != len(set(plan["selected"])):
                        blocking.append("Choose a different picture for each cover photograph or logo.")
                else:
                    plan["selected"].extend(kept)
                if st.checkbox("Read dates and text from the displayed page (optional)", key=field(p + "_read_image", False)):
                    from app.monthly_report_setup_ui import _image_review
                    notes = _image_review(path, image, p, field, prefix)
                    plan["image_notes"][image.image_part] = notes
                # Persist findings across previews and closed OCR controls.
                for selected_image in images:
                    notes = plan["image_notes"].get(selected_image.image_part, "")
                    kind, reason = page_status(notes, unreadable=not notes.strip())
                    if kind in ("pricing", "legal", "blank", "signature") and selected_image.id in plan["selected"]:
                        blocking.append("Uncheck " + labels[selected_image.id] + ": " + reason)
            if action == actions[1] and section.key not in ("cover", "other"):
                st.caption("Add an updated org chart or photograph below. Uncheck the old picture above to replace it. Add complete vendor/chemical PDFs in the next step.")
                upload = st.file_uploader("Updated picture or chart", type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=p + "_replacement", max_upload_size=30)
                if upload:
                    image = normalize_report_image(upload.getvalue(), Path(upload.name).suffix, line_art=section.key == "organization")
                    st.image(image.data, width="stretch")
                    plan["new_assets"] = [(default_slot(section.key), image)]
                elif plan["new_assets"]:
                    st.caption("Your replacement picture is retained.")
            if any(i.kind == "unsupported" for i in section.items):
                st.warning("Some Word drawings could not be read as editable pictures. Check this section in the original report and add a replacement picture if needed before marking it ready. The original drawings will be retained for reference.")
                choice = st.radio("What should happen to those unread drawings?", ["Choose an option", "I added replacement pictures for the drawings needed", "Leave these drawings out of this draft"],
                                  key=field(p + "_unsupported", old.get("unsupported_choice", "Choose an option")))
                plan["unsupported_choice"] = choice
                plan["unsupported_reviewed"] = choice == "Leave these drawings out of this draft" or (choice == "I added replacement pictures for the drawings needed" and bool(plan["new_assets"]))
                if not plan["unsupported_reviewed"]:
                    blocking.append("Add replacement pictures using Edit, or explicitly choose to leave the unread drawings out of this draft.")
        for message in blocking:
            st.error(message)
        stamp = plan_signature(plan)
        reviewed = st.checkbox("This section is ready — the selected content is relevant and contains no prices, legal-only pages or blank/signature-only pages", key=field(p + "_ready_" + stamp, old.get("approval_stamp") == stamp))
        plan["approved"] = reviewed and not blocking
        plan["approval_stamp"] = stamp if plan["approved"] else ""
        plans[section.key] = plan
        if blocking:
            st.caption("Resolve the message above to finish this section.")


def render_section_setup(contract, period, prepared, field, *, state=None):
    prefix = "report_setup_" + _signature((contract, state.profile.key if state else "new", period.key))
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
    candidate, actor, missing = _identity(contract, prepared, p, field, state)
    intent = st.radio("What are you preparing?", ["A new month using this report’s design", "Finish a report someone already started"],
                      key=field(p + "_intent", "Finish a report someone already started"))
    st.caption(f"Finished report: {period.label}. Existing work stays selected until you choose to change or leave it out. No pages are removed merely because the cover looks old.")
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
                if prior_import and prior_import.period == period and (not current or library.imported_snapshot_revision(contract, profile.key) == current.revision):
                    base = merge_drafts(base, prior_import)
                draft = merge_drafts(base, draft)
                draft = apply_section_omissions(draft, plans.values())
                review = {"sha256": inspection.sha256, "intent": intent, "period": period.key, "image_review_scope": p,
                          "items": [asdict(i) for i in inspection.items],
                          "section_plans": [{k: v for k, v in plan.items() if k != "new_assets"} for plan in plans.values()]}
                # Normalize dataclass table values for the JSON audit record.
                review["section_plans"] = [dict(plan, tables={k: asdict(v) for k, v in plan.get("tables", {}).items()}) for plan in review["section_plans"]]
                library.save_report_setup(profile, draft, path, review, assets=mapped.assets,
                                          expected_revision=state.revision if state else 0, actor=actor, confirmed=True,
                                          snapshot_revision=current.revision if current else 0)
                st.session_state["report_resume_import"] = (contract, profile.key, period.key)
                st.session_state["report_setup_done"] = profile.key
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
