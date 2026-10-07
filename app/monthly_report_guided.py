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
from app.monthly_report_editor import _grid, _key, _preview, _signature, _typed_table
from app.monthly_report_model import (ReportDraft, ReportPeriod, ResolvedBlock, STOCK_TEXTS,
                                     layout_blocks, profile_sections)
from app.monthly_report_setup import MONTHLY_BLOCKS, merge_blocks, month_selector, new_month_draft, suggested_period

STEPS = ("1 · Report", "2 · This month’s work", "3 · Site information", "4 · Review & download")


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


def _edit_content(spec, block, state, prefix, assets, field):
    key = prefix + "_edit_" + spec.key
    if spec.type in ("rich_text", "stock_text"):
        text = st.text_area(spec.key.replace("_", " ").capitalize(), key=field(key + "_text_" + _signature(block.references), block.text), height=140)
        return replace(block, source="This month", text=text, reviewed_fingerprint=block.reviewed_fingerprint if text == block.text else "")
    if spec.type in ("table", "work_order_grid"):
        seed, config = _typed_table(spec, block.rows)
        rows = _grid(key + "_table_" + _signature(asdict(spec)), seed, num_rows="dynamic", hide_index=True, column_config=config)
        from app.monthly_report_editor import _cell_text
        columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
        return replace(block, source="This month", rows=tuple(tuple(_cell_text(row.get(c)) for c in columns) for row in rows
                                                              if any(v is not None and v != "" for v in row.values())))
    _preview(block, assets, state.profile)
    upload = st.file_uploader("Updated " + spec.key.replace("_", " "), type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    if upload and st.button("Use this replacement in this report", key=key + "_replace"):
        from pathlib import Path
        image = normalize_report_image(upload.getvalue(), Path(upload.name).suffix,
                                       line_art=spec.key in ("org_chart", "contact_matrix", "business_hours_workflow", "after_hours_workflow"))
        reference = library.asset_reference(image.data, image.extension)
        assets[reference] = image.data
        block = replace(block, source="Replace once", asset_hashes=(reference,), asset_captions=(), references=())
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
    from app.monthly_report_directory_ui import contract_choices, render_directory
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
    names = contract_choices()
    contract = st.selectbox("Contract", names, key=field("report_contract", last_contract if last_contract in names else names[0]))
    if st.button("Manage contract and site directory", key="report_directory_open"):
        st.session_state["report_directory_manage"] = True
        st.rerun()
    period = month_selector(field, "report", suggested_period(operator_today(browser_timezone)))
    st.caption("Suggested month: previous month on days 1–10; current month thereafter. Change it whenever needed.")
    profiles = library.list_profiles(contract)
    choices = [p.key for p in profiles] + ["__new__"]
    completed_setup = st.session_state.pop("report_setup_done", None)
    profile_key = field("report_profile_" + _key(contract), last_profile if last_contract == contract and last_profile in choices else choices[0])
    if completed_setup in choices:
        st.session_state[profile_key] = completed_setup
    if st.session_state[profile_key] not in choices:
        st.session_state[profile_key] = choices[0]
    selected = st.selectbox("Site / report", choices, format_func=lambda k: "Set up a report from an existing DOCX" if k == "__new__" else next(p.title for p in profiles if p.key == k), key=profile_key)
    if selected == "__new__":
        from app.monthly_report_setup_ui import render_setup
        render_setup(contract, period, "", field)
        return
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
    prior = library.load_snapshot(contract, selected, ReportPeriod.previous(period.start))
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
        elif prior:
            draft = new_month_draft(prior.draft, period)
        else:
            draft = _initial_draft(state, period, prepared)
        st.session_state[draft_key] = replace(draft, prepared_by=prepared or draft.prepared_by)
        st.session_state[prefix + "_revision"] = library.imported_snapshot_revision(contract, selected) if using_import else snapshot.revision if snapshot else 0
    draft = st.session_state[draft_key]
    prepared = st.text_input("Prepared by", key=field(prefix + "_prepared", draft.prepared_by))
    draft = replace(draft, prepared_by=prepared)
    assets = st.session_state.setdefault(prefix + "_assets", {})
    step = st.radio("Report steps", STEPS, horizontal=True, key=field(prefix + "_step", STEPS[0]))
    blocks = {b.key: b for b in draft.blocks}
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    included = {b.key for s in draft.sections if s.included for b in s.blocks}
    standing = [b for b in draft.blocks if b.key not in MONTHLY_BLOCKS and b.key in included]
    standing_signature = _signature([asdict(b) for b in standing])
    review_state = prefix + "_standing_reviewed_content"

    if step == STEPS[0]:
        st.subheader("Your report, ready to continue")
        st.write(f"{profile.title} · {period.label}")
        st.info("Continue your saved work below. New monthly uploads are added to this draft; they never silently replace another editor’s text or pages.")
        st.write("1. Add this month’s files and update the narrative.\n2. Confirm standing site information or replace what changed.\n3. Review and download DOCX / PDF.")
        if snapshot:
            st.caption(f"Saved version {snapshot.revision} · entered editor: {snapshot.entered_editor or snapshot.draft.prepared_by}")
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
        st.subheader("Update this month’s text")
        st.caption("Source-linked action lines can be appended above. Full AI drafting is still being implemented; unreadable uploads do not silently become completed-work claims.")
        for key in ("activity_summary", "equipment_issues", "training_summary", "utility_analysis"):
            if key in included or key == "activity_summary":
                spec = specs[key]
                block = blocks.get(key, ResolvedBlock(key, "This month"))
                blocks[key] = _edit_content(spec, block, state, prefix, assets, field)
    elif step == STEPS[2]:
        st.subheader("Keep what is still correct; update what changed")
        st.write("Check the org chart, outage workflows, facility/vendor contacts and other standing information for these exact sites.")
        from app.monthly_report_directory_ui import review_contacts
        review_contacts(draft, prefix, field, assets)
        for key in sorted(included - MONTHLY_BLOCKS):
            spec = specs[key]
            block = blocks.get(key, ResolvedBlock(key, "This month"))
            with st.expander(key.replace("_", " ").capitalize()):
                edit = st.checkbox("Update this item", key=field(prefix + "_change_" + key, False))
                if edit:
                    blocks[key] = _edit_content(spec, block, state, prefix, assets, field)
                else:
                    _preview(block, assets, profile)
        standing = [b for b in blocks.values() if b.key not in MONTHLY_BLOCKS and b.key in included]
        standing_signature = _signature([asdict(b) for b in standing])
        reviewed_key = prefix + "_standing_control_" + standing_signature
        def record_review():
            st.session_state[review_state] = standing_signature if st.session_state[reviewed_key] else ""
        st.checkbox("I checked the standing information for these sites", key=reviewed_key,
                    value=st.session_state.get(review_state) == standing_signature, on_change=record_review)
        st.caption("Changes here apply to this report. Use the advanced editor to confirm a shared default for future reports; one-off changes never silently become site defaults.")
    draft = replace(draft, blocks=tuple(blocks.values()))
    footer = blocks.get("footer_text")
    if footer:
        draft = replace(draft, address_line=footer.text if footer.source != "Omit" else "")
    st.session_state[draft_key] = draft
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
        for title, _, pages in outline(draft):
            st.write(f"{title} · at least {pages} pages")
        loader = lambda ref: assets[ref] if ref in assets else library.read_asset(contract, selected, ref)
        estimated = estimate_bytes(draft, loader)
        checks = preflight(draft, estimated)
        for check in checks:
            (st.error if check.blocking else st.warning)(check.message)
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
            st.download_button("Download DOCX", package.docx, file_name=package.docx_name, key=prefix + "_docx")
            if package.pdf:
                st.download_button("Download PDF", package.pdf, file_name=package.pdf_name, mime="application/pdf", key=prefix + "_pdf")
            if package.pdf_error:
                st.warning(package.pdf_error)
        st.caption("Generating also saves this report version with the entered editor name. Use Save progress earlier to preserve unfinished work.")
