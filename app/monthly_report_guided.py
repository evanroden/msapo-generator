"""A small monthly workspace around the versioned report model."""

from dataclasses import asdict, replace
import re

import streamlit as st

from app import monthly_report_library as library
from app.config import operator_today
from app.memory import (record_report_preferences, record_report_preparer,
                        remembered_report_preferences, remembered_report_preparer)
from app.monthly_report_checks import preflight
from app.monthly_report_docx import estimate_bytes, generate_report, normalize_report_image, outline
from app.monthly_report_editor import _grid, _preview, _signature, _typed_table
from app.monthly_report_model import (ReportDraft, ResolvedBlock, STOCK_TEXTS,
                                     layout_blocks, profile_sections)
from app.monthly_report_setup import MONTHLY_BLOCKS, merge_blocks, month_selector, new_month_draft, suggested_period
from app.monthly_report_section_help import section_help, update_label

STEPS = ("1 · Report", "2 · This month’s work", "3 · Site information", "4 · Review & download")


def review_message(check, draft):
    """Tell a manager what to do and where, without exposing model field IDs."""
    from app.monthly_report_sections import readable_label
    key = check.block_key
    label = readable_label(key) if key else "this report"
    section = next((s.title for s in draft.sections if any(b.key == key for b in s.blocks)), "")
    monthly = key in MONTHLY_BLOCKS | {"equipment_issues", "utility_analysis"}
    location = "This month’s work" if monthly else "Site information"
    if section and monthly:
        location += " → " + section
    elif key:
        location += " → " + label
    if key in {"issues", "proposals"} and draft.follow_ups:
        location = "This month’s work → Carried-forward issues and proposals"
    if check.code == "required":
        return f"Add {label.lower()} in {location}."
    if check.code in {"review", "ai_evidence", "ai_number"}:
        return f"Check the wording and linked evidence for {label.lower()} in This month’s work, then confirm its review." + (" Correct any unsupported numbers." if check.code == "ai_number" else "")
    if check.code == "client_pages":
        return f"Open {label} above and confirm that every included picture/page is relevant and has no prices."
    if check.code == "library_save":
        return f"Finish confirming the shared replacement for {label.lower()} in the advanced editor, or use it for this report only."
    message = check.message
    if key:
        message = message.replace(key, label).replace(key.replace("_", " "), label.lower())
    if check.code in {"placeholder", "pricing", "period"} and key:
        message += " Open " + ("Report" if key == "cover" else location) + " to make the correction."
    return message


def _standing_signature(blocks, included):
    keys = included | {b.key for b in layout_blocks()}
    return _signature(sorted((b.key, b.fingerprint) for b in blocks
                             if b.key not in MONTHLY_BLOCKS and b.key in keys))


def _initial_draft(state, period, prepared):
    blocks = []
    for spec in (*[b for s in profile_sections(state.profile) for b in s.blocks], *layout_blocks()):
        saved = state.block(spec.key)
        if saved:
            blocks.append(saved)
        elif spec.stock_text_keys:
            blocks.append(ResolvedBlock(spec.key, "Stock text", text=STOCK_TEXTS[spec.stock_text_keys[0]]))
        else:
            blocks.append(ResolvedBlock(spec.key, "This month" if spec.required else "Omit"))
    return ReportDraft(state.profile, period, prepared, profile_sections(state.profile), tuple(blocks))


def _edit_content(spec, block, state, prefix, assets, field, draft=None):
    if draft is not None and spec.type == "image_grid":
        from app.monthly_report_visual_ui import edit_photos
        return edit_photos(draft, block, prefix, assets, field)
    key = prefix + "_edit_" + spec.key
    if block.extra_tables:
        from app.monthly_report_editor import _cell_text
        tables = []
        for n, table in enumerate(block.extra_tables):
            st.write(f"Table {n+1}")
            rows = _grid(key + f"_imported_{n}_" + _signature(table.columns), [dict(zip(table.columns, r)) for r in table.rows] or [dict.fromkeys(table.columns)], num_rows="dynamic", hide_index=True)
            tables.append(replace(table, rows=tuple(tuple(_cell_text(r.get(c)) for c in table.columns) for r in rows if any(v is not None and v != "" for v in r.values()))))
        block = replace(block, extra_tables=tuple(tables))
    if spec.type in ("rich_text", "stock_text") and block.ai_paragraphs:
        st.caption("Edit this source-linked wording in the wording and sources box above.")
        st.text(block.text)
    elif spec.type in ("rich_text", "stock_text"):
        text = st.text_area(spec.key.replace("_", " ").capitalize(), key=field(key + "_text_" + _signature(block.references), block.text), height=140)
        block = replace(block, source="This month", text=text, reviewed_fingerprint=block.reviewed_fingerprint if text == block.text else "")
    elif spec.type in ("table", "work_order_grid") and (block.rows or not block.extra_tables):
        seed, config = _typed_table(spec, block.rows)
        rows = _grid(key + "_table_" + _signature(asdict(spec)), seed, num_rows="dynamic", hide_index=True, column_config=config)
        from app.monthly_report_editor import _cell_text
        columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
        block = replace(block, source="This month", rows=tuple(tuple(_cell_text(row.get(c)) for c in columns) for row in rows
                                                               if any(v is not None and v != "" for v in row.values())))
    if block.asset_hashes:
        labels = {ref: f"Picture / page {n+1}" for n, ref in enumerate(block.asset_hashes)}
        keep = st.multiselect("Pictures/pages to keep", list(block.asset_hashes),
                              format_func=labels.get, key=field(key + "_keep_" + _signature(block.asset_hashes), list(block.asset_hashes)))
        original = block
        block = replace(block, asset_hashes=tuple(keep), asset_captions=tuple(original.asset_captions[n] if n < len(original.asset_captions) else "" for n, ref in enumerate(original.asset_hashes) if ref in keep))
        if len(original.references) == len(original.asset_hashes):
            block = replace(block, references=tuple(original.references[n] for n, ref in enumerate(original.asset_hashes) if ref in keep))
        if keep:
            shown = st.selectbox("Picture/page to view", keep, format_func=labels.get, key=key + "_shown_" + _signature(keep))
            st.image(assets.get(shown) or library.read_asset(state.profile.contract, state.profile.key, shown), width="stretch")
    if spec.type in ("rich_text", "stock_text", "table", "work_order_grid"):
        return block
    upload = st.file_uploader("Updated " + spec.key.replace("_", " "), type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    if upload and st.button("Use this replacement in this report", key=key + "_replace"):
        from pathlib import Path
        image = normalize_report_image(upload.getvalue(), Path(upload.name).suffix,
                                       line_art=spec.key in ("org_chart", "contact_matrix", "business_hours_workflow", "after_hours_workflow"))
        reference = library.asset_reference(image.data, image.extension)
        assets[reference] = image.data
        block = replace(block, source="Replace once", asset_hashes=(reference,), asset_captions=(), references=())
        st.image(image.data, width="stretch", caption="Updated image in this report")
    return block


def activity_from_sources(sources, existing):
    """Append reviewed action fields only. Recommendations are not completed work."""
    from app.monthly_report_sources import source_reference
    text, references = [], []
    for source in sources:
        if source.classification not in ("Vendor service", "Water treatment") or not source.actions.strip() or not source.selected_pages:
            continue
        refs = tuple(source_reference(source, n) for n in source.selected_pages)
        if all(r in existing.references for r in refs):
            continue
        action = ": ".join(v for v in (source.vendor, source.actions.strip()) if v)
        action = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[contact omitted]", action)
        action = re.sub(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)", "[contact omitted]", action)
        text.append("- " + action.strip())
        references.extend(refs)
    return merge_blocks(existing, ResolvedBlock("activity_summary", "This month", text="\n".join(text), references=tuple(references)))


def render_guided_workflow(browser_token, browser_timezone, field, move):
    if st.session_state.get("report_branding_manage", False):
        from app.monthly_report_branding_ui import render_branding
        render_branding(field)
        return
    from app.monthly_report_directory_ui import render_directory
    if st.session_state.get("report_directory_manage", False):
        render_directory(field)
        return
    # The legacy detailed editor remains available for layout/reordering; it is
    # not a demo and is not the primary asset-manager experience.
    if st.session_state.get("report_advanced", False):
        if st.button("Return to guided report", key="report_exit_advanced"):
            st.session_state["report_advanced"] = False
            st.rerun()
        from app.monthly_report_editor import render_profile_workflow
        render_profile_workflow(browser_token, browser_timezone, field, move)
        return
    last_contract, last_profile = remembered_report_preferences(browser_token)
    with st.expander("First time here? How to finish a monthly report"):
        st.write("1. Choose your contract and check the sites that belong in **one** report.\n2. Use a saved design, the general template, or upload an older/unfinished report.\n3. Open the section boxes to update this month’s work, pictures, people and contacts.\n4. Preview the report, finish the review checks, then download DOCX and PDF.")
        st.caption("You can move between steps in any order. Save progress before leaving; return to the same sites and month to continue. Chart and photo layouts update beside their fields. Refresh the draft PDF preview when you want to check the whole report.")
    from app.monthly_report_start_ui import choose_contract, select_sites, starting_choice
    contract = choose_contract(last_contract, field)
    with st.expander("Set up or update the contract’s site/contact list (optional)"):
        st.caption("Use a contract directory workbook to suggest sites and contacts. Each report still confirms its own sites.")
        if st.button("Manage contract and site directory", key="report_directory_open"):
            st.session_state["report_directory_manage"] = True
            st.rerun()
    with st.expander("Shared contract logos (optional)"):
        st.caption("Current shared logos are used on the contract cards and offered in reports. Site-specific replacements remain available in Site information.")
        if st.button("Manage shared logos", key="report_branding_open"):
            st.session_state["report_branding_manage"] = True
            st.rerun()
    if not contract:
        return
    period = month_selector(field, "report", suggested_period(operator_today(browser_timezone)))
    st.caption("Suggested month: previous month on days 1–10; current month thereafter. Change it whenever needed.")
    profiles = library.list_profiles(contract)
    completed_setup = st.session_state.pop("report_setup_done", None)
    candidate, existing = select_sites(contract, profiles, last_profile if last_contract == contract else "", field, completed_setup)
    if not candidate:
        return
    if not existing:
        starting_choice(candidate, profiles, period, "", field)
        return
    selected = existing.key
    state = library.load_profile(contract, selected)
    profile = state.profile
    st.caption(profile.scope_type.replace("_", " ").capitalize() + " · " + "; ".join(f.title for f in profile.facilities))
    prefix = "report_guided_" + _signature((contract, selected, period.key))
    snapshot = library.load_snapshot(contract, selected, period)
    imported = library.load_imported_draft(contract, selected)
    if completed_setup == selected:
        record_report_preferences(browser_token, contract, selected)
        if imported:
            record_report_preparer(browser_token, contract, selected, imported.prepared_by)
    from app.monthly_report_start import latest_snapshot, latest_saved_draft
    prior = latest_snapshot(contract, selected, period)
    prior_draft = latest_saved_draft(contract, selected, period, before=True)
    draft_key = prefix + "_draft"
    resume = st.session_state.get("report_resume_import") == (contract, selected, period.key)
    if draft_key not in st.session_state or resume:
        prepared = remembered_report_preparer(browser_token, contract, selected)
        using_import = False
        pending_import = imported and imported.period == period and (not snapshot or snapshot.revision == library.imported_snapshot_revision(contract, selected))
        if imported and (resume or pending_import):
            draft = imported
            using_import = True
            st.session_state.pop("report_resume_import", None)
        elif snapshot:
            draft = snapshot.draft
        elif imported and imported.period == period:
            draft = imported
            using_import = True
        elif prior_draft:
            draft = replace(new_month_draft(prior_draft, period), profile=profile)
        else:
            draft = _initial_draft(state, period, prepared)
        st.session_state[draft_key] = replace(draft, prepared_by=prepared or draft.prepared_by)
        st.session_state[prefix + "_revision"] = library.imported_snapshot_revision(contract, selected) if using_import else snapshot.revision if snapshot else 0
    draft = st.session_state[draft_key]
    prepared = st.text_input("Prepared by", key=field(prefix + "_prepared", draft.prepared_by))
    draft = replace(draft, prepared_by=prepared)
    if candidate != profile:
        st.caption("The updated group name/scope will be remembered after you save it.")
        rename_ok = st.checkbox("Remember this name and scope for these same sites", key=prefix + "_rename_" + _signature((candidate, prepared, state.revision)))
        if st.button("Save group name", disabled=not (rename_ok and prepared.strip()), key=prefix + "_rename_save"):
            library.save_profile(candidate, expected_revision=state.revision, actor=prepared, confirmed=True)
            st.session_state[draft_key] = replace(draft, profile=candidate)
            st.rerun()
    assets = st.session_state.setdefault(prefix + "_assets", {})
    step_key = field(prefix + "_step", STEPS[0])
    if completed_setup == selected:
        start_standing = st.session_state.pop("report_start_at_site_information", None) == selected
        st.session_state[step_key] = STEPS[0] if start_standing else STEPS[1]
    step = st.radio("Report steps", STEPS, horizontal=True, key=step_key)
    def go_to_step(value):
        st.session_state[step_key] = value

    save_status = st.empty()
    blocks = {b.key: b for b in draft.blocks}
    specs = {b.key: b for s in draft.sections for b in s.blocks} | {b.key: b for b in layout_blocks()}
    included = {b.key for s in draft.sections if s.included for b in s.blocks}
    standing_signature = _standing_signature(draft.blocks, included)
    review_state = prefix + "_standing_reviewed_content"

    if step == STEPS[0]:
        st.subheader("Choose what belongs in this report")
        st.write(f"{profile.title} · {period.label}")
        st.write("Check the sections you need. Unchecking a section leaves it out of the download and keeps its content available if you change your mind. Your saved choices carry forward to the next month.")
        sections = []
        for section in draft.sections:
            with st.expander(section.title):
                st.caption(section_help(section.key).guidance)
                keep = st.checkbox("Include " + section.title, key=field(prefix + "_include_" + section.key, section.included))
                sections.append(replace(section, included=keep))
        draft = replace(draft, sections=tuple(sections))
        st.caption(f"{sum(s.included for s in draft.sections)} sections selected. Nothing is deleted when a section is left out.")
        st.button("Continue to this month’s work", key=prefix + "_next_work", type="primary", on_click=go_to_step, args=(STEPS[1],))
        with st.expander("Upload a report someone already started"):
            from app.monthly_report_setup_ui import render_setup
            render_setup(contract, period, prepared, field, state=state)
        with st.expander("Advanced layout, shared assets and history"):
            st.caption("Save your progress first. Detailed controls include section order, shared asset replacement, library history and restoration.")
            if st.button("Open advanced editor", key=prefix + "_advanced"):
                st.session_state["report_advanced"] = True
                st.rerun()
    elif step == STEPS[1]:
        from app.monthly_report_upload_ui import render_uploads
        from app.monthly_report_sources import ingest, source_bytes
        if prefix + "_evidence" not in st.session_state and draft.sources:
            # Cached native extraction is restored once; reviewed source fields
            # remain the pinned snapshot values, not regenerated suggestions.
            st.session_state[prefix + "_evidence"] = tuple(replace(ingest(profile, s.filename, source_bytes(profile, s))[0], source=s) for s in draft.sources)
        report_sources, monthly_blocks, monthly_specs = render_uploads(profile, period, prefix, field)
        draft = replace(draft, sources=report_sources)
        if monthly_blocks and st.button("Add prepared pages and tables to this draft", key=prefix + "_apply_uploads"):
            applied = set()
            for key, block in monthly_blocks.items():
                if block.rows and blocks.get(key) and blocks[key].rows and specs.get(key) != monthly_specs.get(key, specs.get(key)):
                    st.error("The existing table has different columns. Review it in the advanced editor; nothing was replaced.")
                    continue
                blocks[key] = merge_blocks(blocks.get(key), block)
                applied.add(key)
            draft = replace(draft, sections=tuple(replace(s, included=s.included or any(b.key in applied for b in s.blocks),
                                                         blocks=tuple(monthly_specs.get(b.key, b) if b.key in applied else b for b in s.blocks)) for s in draft.sections))
        activity = blocks.get("activity_summary", ResolvedBlock("activity_summary", "This month"))
        reviewed_actions = st.checkbox("I reviewed the vendor / chemical report action fields against the sources", key=prefix + "_actions_ok_" + _signature([s.fingerprint for s in report_sources]))
        if st.button("Add reviewed work to the activity summary", key=prefix + "_add_actions", disabled=not reviewed_actions):
            blocks["activity_summary"] = activity_from_sources(report_sources, activity)
            draft = replace(draft, sections=tuple(replace(s, included=True) if s.key == "activity" else s for s in draft.sections))
        from app.monthly_report_ai_ui import render_drafting
        draft, blocks = render_drafting(draft, blocks, prefix, field)
        from app.monthly_report_followups import render_followups
        draft = render_followups(draft, prefix, field)
        st.subheader("Update this month’s text")
        st.caption("Edit the wording below. Suggested text must be checked against its linked evidence before download.")
        monthly_keys = MONTHLY_BLOCKS | {"equipment_issues", "utility_analysis"}
        for section in draft.sections:
            if section.included or section.key == "activity":
                relevant = [b for b in section.blocks if b.key in monthly_keys]
                if relevant:
                    with st.expander(section.title, expanded=section.key == "activity"):
                        st.caption(section_help(section.key).guidance)
                        for spec in relevant:
                            block = blocks.get(spec.key, ResolvedBlock(spec.key, "This month"))
                            if block.source == "Omit" and spec.key != "activity_summary" and spec.type != "image_grid":
                                continue
                            blocks[spec.key] = _edit_content(spec, block, state, prefix, assets, field, draft)
    elif step == STEPS[2]:
        st.subheader("Keep what is still correct; update what changed")
        st.write("Check the org chart, outage workflows, facility/vendor contacts and other standing information for these exact sites.")
        with st.expander("Equipment tags for these sites (optional)"):
            tags_text = st.text_area("Known equipment tags", key=field(prefix + "_asset_tags", "\n".join(profile.asset_tags)), help="One tag per line, such as the tag printed on a pump or air handler. Suggestions flag tags that are not on this confirmed list.")
            tags = tuple(dict.fromkeys(t.strip() for t in tags_text.splitlines() if t.strip()))
            tags_ok = st.checkbox("Remember these equipment tags for these exact report sites", key=prefix + "_tags_ok_" + _signature((tags,state.revision,prepared)))
            if st.button("Save equipment tags", key=prefix + "_tags_save", disabled=not (tags_ok and prepared.strip())):
                updated_profile = replace(profile, asset_tags=tags)
                library.save_profile(updated_profile, expected_revision=state.revision, actor=prepared, confirmed=True)
                st.session_state[draft_key] = replace(draft, profile=updated_profile)
                st.rerun()
        with st.expander("Client logo, cover photo and footer", expanded=not blocks.get("client_logo", ResolvedBlock("client_logo", "This month")).asset_hashes):
            st.caption("Drop in a replacement logo or photo. Images fit the available space without stretching; transparent backgrounds are printed on white.")
            for key in ("client_logo", "brand_logo", "cover_photo", "footer_text"):
                st.write(key.replace("_", " ").capitalize())
                blocks[key] = _edit_content(specs[key], blocks.get(key, ResolvedBlock(key, "This month")), state, prefix, assets, field)
                if key in ("client_logo", "brand_logo"):
                    from app.monthly_report_branding_ui import offer_logo
                    blocks[key] = offer_logo(blocks[key], contract, prefix, assets)
        from app.monthly_report_directory_ui import review_contacts
        review_contacts(draft, prefix, field, assets)
        from app.monthly_report_visual_ui import edit_org_chart, edit_contacts
        from app.monthly_report_sections import readable_label
        for key in sorted(included - MONTHLY_BLOCKS):
            spec = specs[key]
            block = blocks.get(key, ResolvedBlock(key, "This month"))
            with st.expander(readable_label(key)):
                if key == "org_chart":
                    blocks[key] = edit_org_chart(replace(draft, blocks=tuple(blocks.values())), block, prefix, assets, field)
                    if not blocks[key].org_nodes:
                        blocks[key] = _edit_content(spec, blocks[key], state, prefix, assets, field)
                elif key in ("contact_matrix", "subcontractor_matrix"):
                    blocks[key] = edit_contacts(draft, spec, block, prefix, assets, field)
                elif st.checkbox(update_label(key), key=field(prefix + "_change_" + key, False)):
                    blocks[key] = _edit_content(spec, block, state, prefix, assets, field)
                else:
                    _preview(block, assets, profile)
        standing_signature = _standing_signature(blocks.values(), included)
        reviewed_key = prefix + "_standing_control_" + standing_signature
        def record_review():
            st.session_state[review_state] = standing_signature if st.session_state[reviewed_key] else ""
        st.checkbox("I checked the standing information for these sites", key=reviewed_key,
                    value=st.session_state.get(review_state) == standing_signature, on_change=record_review)
        st.caption("Save progress to keep these changes. Next month starts from your latest saved report for these exact sites, with monthly work cleared. Shared defaults for other reports are managed separately in the advanced editor.")
    draft = replace(draft, blocks=tuple(blocks.values()))
    footer = blocks.get("footer_text")
    if footer:
        draft = replace(draft, address_line=footer.text if footer.source != "Omit" else "")
    st.session_state[draft_key] = draft
    if snapshot and snapshot.draft.fingerprint == draft.fingerprint:
        save_status.success(f"Saved · version {snapshot.revision} · {period.label} · {snapshot.entered_editor or snapshot.draft.prepared_by}")
    elif snapshot:
        save_status.info(f"You have changes to save. Version {snapshot.revision} is safely stored; use Save progress below before leaving.")
    elif prior_draft:
        save_status.info(f"Starting from your saved {prior_draft.period.label} report for these exact sites. Monthly work and attachments start fresh; standing site information is carried forward for review.")
    else:
        save_status.info("Your starting design is saved. Use Save progress below to store the changes you make for this month.")
    from app.monthly_report_preview import render_preview
    render_preview(draft, assets, prefix, field)
    current_revision = snapshot.revision if snapshot else 0
    conflict = current_revision != st.session_state[prefix + "_revision"]
    if conflict:
        st.warning("Another version was saved. Your working draft is preserved. Compare it with the saved report before creating another version.")
        with st.expander("Compare saved content"):
            st.json({b.key: asdict(b) for b in snapshot.draft.blocks})
        accept = st.checkbox("I compared the saved version and want to save my draft as the next version", key=prefix + f"_accept_{current_revision}")
        if st.button("Accept current revision", key=prefix + "_accept_revision", disabled=not accept):
            st.session_state[prefix + "_revision"] = current_revision
            st.rerun()
    save_ok = st.checkbox("Save this draft for others on this report to continue", key=prefix + "_save_ok_" + draft.fingerprint)
    if not prepared.strip():
        st.caption("Enter your name in Prepared by above to save your progress.")
    if st.button("Save progress", key=prefix + "_save", disabled=conflict or not (save_ok and prepared.strip())):
        saved = library.save_snapshot(draft, expected_revision=current_revision, assets=tuple(assets.items()), entered_editor=prepared,
                                      open_issues=snapshot.open_issues if snapshot else prior.open_issues if prior else (),
                                      pending_proposals=snapshot.pending_proposals if snapshot else prior.pending_proposals if prior else ())
        st.session_state[prefix + "_revision"] = saved.revision
        record_report_preferences(browser_token, contract, selected)
        record_report_preparer(browser_token, contract, selected, prepared)
        st.success("Progress saved. Returning to this report and month resumes this version.")
        st.rerun()
    package = st.session_state.get(prefix + "_package")
    if package and package.fingerprint != draft.fingerprint:
        st.session_state.pop(prefix + "_package", None)
        package = None
    if step == STEPS[3]:
        st.subheader("Review and download")
        from app.monthly_report_editor import review_client_images
        draft = review_client_images(draft, assets, prefix, field)
        st.session_state[draft_key] = draft
        for title, _, pages in outline(draft):
            st.write(f"{title} · at least {pages} pages")
        loader = lambda ref: assets[ref] if ref in assets else library.read_asset(contract, selected, ref)
        estimated = estimate_bytes(draft, loader)
        st.caption(f"Estimated document size: {estimated / (1024 * 1024):.1f} MB. Aim for under 15 MB; fewer attachment pages and more photos per page can help.")
        checks = preflight(draft, estimated)
        if any(c.blocking for c in checks):
            st.info("Complete the items below to unlock your downloads. You can leave an entire section out in Report if it does not belong in this month’s report.")
            for n, (label, target) in enumerate((("Choose included sections", STEPS[0]), ("Update this month’s work", STEPS[1]), ("Check site information", STEPS[2]))):
                st.button(label, key=prefix + f"_fix_{n}", on_click=go_to_step, args=(target,))
        for check in checks:
            (st.error if check.blocking else st.warning)(review_message(check, draft))
        standing_reviewed = st.session_state.get(review_state) == standing_signature
        if not standing_reviewed:
            st.warning("Finish step 3: confirm the standing site information.")
        warnings_ok = not any(not c.blocking for c in checks)
        if not warnings_ok:
            warnings_ok = st.checkbox("I checked these specific warnings", key=prefix + "_warnings_" + draft.fingerprint)
        if st.button("Generate DOCX and PDF", key=prefix + "_generate", type="primary",
                     disabled=conflict or any(c.blocking for c in checks) or not warnings_ok or not standing_reviewed):
            package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
            st.session_state[prefix + "_package"] = package
            try:
                saved = library.save_snapshot(draft, expected_revision=current_revision, assets=tuple(assets.items()), entered_editor=prepared,
                                              open_issues=snapshot.open_issues if snapshot else prior.open_issues if prior else (),
                                              pending_proposals=snapshot.pending_proposals if snapshot else prior.pending_proposals if prior else ())
                st.session_state[prefix + "_revision"] = saved.revision
                record_report_preferences(browser_token, contract, selected)
                record_report_preparer(browser_token, contract, selected, prepared)
            except (ValueError, OSError) as exc:
                st.warning(f"Downloads are ready, but this version could not be saved: {exc}")
        if package:
            sizes = f"DOCX {len(package.docx) / (1024 * 1024):.1f} MB"
            if package.pdf:
                sizes += f" · PDF {len(package.pdf) / (1024 * 1024):.1f} MB"
            st.caption(sizes)
            if max(len(package.docx), len(package.pdf or b"")) > 15 * 1024 * 1024:
                st.warning("The finished report exceeds the 15 MB target. You can reduce selected attachment pages or use denser photo layouts, then generate it again.")
            st.download_button("Download DOCX", package.docx, file_name=package.docx_name, key=prefix + "_docx")
            if package.pdf:
                st.download_button("Download PDF", package.pdf, file_name=package.pdf_name, mime="application/pdf", key=prefix + "_pdf")
            if package.pdf_error:
                st.warning(package.pdf_error)
        st.caption("Generating also saves this report version with the entered editor name. Use Save progress earlier to preserve unfinished work.")
