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
from app.monthly_report_editor import _grid, _signature, _typed_table
from app.monthly_report_model import (ReportDraft, ResolvedBlock, STOCK_TEXTS,
                                     layout_blocks, profile_sections)
from app.monthly_report_setup import MONTHLY_BLOCKS, merge_blocks, month_selector, new_month_draft, suggested_period
from app.monthly_report_section_help import section_help

# UI location is separate from next-month clearing: issues and renewal plans carry forward.
MONTHLY_EDIT_KEYS = MONTHLY_BLOCKS | {"equipment_issues", "utility_analysis", "capital_renewal", "end_of_life", "proposals", "rfi_matrix", "mbcx_status"}

STEPS = ("1 · Report", "2 · This month’s work", "3 · Site information", "4 · Review & download")


def _monthly_specs(section):
    # Capacity is standing data but belongs beside utility results in the UI.
    # This routing must not change rollover or standing-review semantics.
    return tuple(b for b in section.blocks if b.key in MONTHLY_EDIT_KEYS or section.key == "scorecards")


def _standing_specs(section):
    monthly = {b.key for b in _monthly_specs(section)}
    return tuple(b for b in section.blocks if b.key not in monthly)


def _forget_block_widgets(prefix, keys):
    starts = tuple(prefix + "_edit_" + key + "_" for key in keys)
    for key in list(st.session_state):
        if key.startswith(starts):
            del st.session_state[key]
    st.session_state["report_draft_mirror"] = {
        key: value for key, value in st.session_state.get("report_draft_mirror", {}).items()
        if not key.startswith(starts)
    }


def _apply_prepared(draft, blocks, additions, incoming_specs, prefix):
    """Apply one reviewed batch atomically; leave the draft intact on conflict."""
    from app.monthly_report_setup import merge_report_block
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    proposed = dict(blocks)
    try:
        for key, block in additions.items():
            incoming = incoming_specs.get(key, specs.get(key))
            if block.rows and blocks.get(key) and blocks[key].rows and specs.get(key) != incoming:
                raise ValueError("The existing table has different columns. Match the uploaded table headings to the current section and try again; nothing was replaced.")
            proposed[key] = merge_report_block(blocks.get(key), block, specs.get(key), incoming)
    except ValueError as exc:
        st.error(str(exc))
        st.caption("Nothing was added. Your current draft is retained; correct the source and try again.")
        return draft, blocks
    changed = {key for key in additions if proposed.get(key) != blocks.get(key)}
    _forget_block_widgets(prefix, changed)
    sections = tuple(replace(s, included=s.included or any(b.key in additions for b in s.blocks),
                             blocks=tuple(incoming_specs.get(b.key, b) if b.key in additions else b for b in s.blocks))
                     for s in draft.sections)
    return replace(draft, sections=sections), proposed


def review_destination(draft, block_key):
    follow_up = next((item for item in draft.follow_ups if item.key == block_key), None)
    if follow_up:
        block_key = "proposals" if follow_up.category == "proposal" else "equipment_issues"
    if block_key in {"cover", *(b.key for b in layout_blocks())}:
        return STEPS[0], None
    if block_key == "issues":
        block_key = "equipment_issues"
    section = next((s for s in draft.sections if any(b.key == block_key for b in s.blocks)), None)
    if section:
        if not section.included:
            return STEPS[0], None
        monthly = any(b.key == block_key for b in _monthly_specs(section))
        return STEPS[1] if monthly else STEPS[2], section.key
    return None, None


def review_message(check, draft):
    """Tell a manager what to do and where, without exposing model field IDs."""
    from app.monthly_report_sections import readable_label
    key = check.block_key
    follow_up = next((item for item in draft.follow_ups if item.key == key), None)
    if follow_up:
        category = "proposals" if follow_up.category == "proposal" else "equipment issues"
        return check.message.replace(key, category) + f" Check this item in {category.capitalize()} above."
    label = readable_label(key) if key else "this report"
    section = next((s.title for s in draft.sections if any(b.key == key for b in s.blocks)), "")
    location = section or "the report fields above"
    if key and not section:
        location = label
    if key in {"issues", "proposals"} and draft.follow_ups:
        location = "Equipment Performance Issues" if key == "issues" else "Pending & Declined Proposals"
    if check.code == "required":
        return f"Add {label.lower()} in {location}."
    if check.code in {"review", "ai_evidence", "ai_number"}:
        return f"Check the wording and linked evidence for {label.lower()} above, then confirm its review." + (" Correct any unsupported numbers." if check.code == "ai_number" else "")
    if check.code == "client_pages":
        return f"Review the new or changed pictures in {label} above and confirm they are relevant and have no prices. Unchanged reviewed pictures stay ready."
    if check.code == "library_save":
        return f"The shared replacement for {label.lower()} needs confirmation before it can be saved. Keep the existing saved content to continue."
    message = check.message
    if key:
        message = message.replace(key, label).replace(key.replace("_", " "), label.lower())
    if check.code in {"placeholder", "pricing", "period"} and key:
        message += " Correct it in " + ("the cover details" if key == "cover" else location) + " above."
    return message


def _standing_signature(blocks, included):
    keys = included | {b.key for b in layout_blocks()}
    return _signature(sorted((b.key, b.fingerprint) for b in blocks
                             if b.key not in MONTHLY_EDIT_KEYS and b.key in keys))


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


def complete_guided_sections(draft):
    """Keep every standard section, including intentionally blank sections.

    Existing order, titles, imported schemas and content remain authoritative.
    Older partial designs gain the missing sections and standard block slots;
    this guided working copy never requires content just to retain a heading.
    """
    full_profile = replace(draft.profile, section_order=(), section_block_order=(), excluded_sections=())
    standard = {section.key: section for section in profile_sections(full_profile)}
    sections = []
    for section in draft.sections:
        present = {block.key for block in section.blocks}
        additions = tuple(block for block in standard[section.key].blocks if block.key not in present) if section.key in standard else ()
        sections.append(replace(section, included=True,
                                blocks=tuple(replace(block, required=False) for block in (*section.blocks, *additions))))
    present = {section.key for section in sections}
    sections.extend(replace(section, included=True, blocks=tuple(replace(block, required=False) for block in section.blocks))
                    for key, section in standard.items() if key not in present)
    return replace(draft, sections=tuple(sections))


def _review_carried_update(block, period, prefix):
    from app.monthly_report_setup import carried_period, confirm_current_period
    previous = carried_period(block, period)
    if previous is None:
        return block
    st.info(f"This update was carried from {previous.label}. Check its wording and any charts for {period.label} before including it.")
    if st.button(f"This update is correct for {period.label}", key=prefix + "_current_period_" + block.key + "_" + block.fingerprint):
        return confirm_current_period(block, period)
    return block


def _edit_content(spec, block, state, prefix, assets, field, draft=None):
    if draft is not None and spec.type == "image_grid":
        from app.monthly_report_visual_ui import edit_photos
        return edit_photos(draft, block, prefix, assets, field, show_preview=False)
    key = prefix + "_edit_" + spec.key
    if spec.type not in ("rich_text", "stock_text") and block.text.strip():
        if block.ai_paragraphs:
            st.caption("Edit these source-linked notes in the wording and sources editor above.")
            st.text(block.text)
        else:
            notes = st.text_area("Notes included in this section", key=field(key + "_notes_" + _signature(block.references), block.text), height=120)
            if notes != block.text:
                block = replace(block, source="This month", text=notes, reviewed_fingerprint="", client_reviewed_fingerprint="")
    if block.extra_tables:
        from app.monthly_report_editor import _cell_text
        tables = []
        for n, table in enumerate(block.extra_tables):
            from app.monthly_report_table_review_ui import review_table_headings
            table = review_table_headings(table, key + f"_imported_{n}", field)
            st.write(f"Table {n+1}")
            rows = _grid(key + f"_imported_{n}_" + _signature(table.columns), [dict(zip(table.columns, r)) for r in table.rows] or [dict.fromkeys(table.columns)], num_rows="dynamic", hide_index=True)
            tables.append(replace(table, rows=tuple(tuple(_cell_text(r.get(c)) for c in table.columns) for r in rows if any(v is not None and v != "" for v in r.values()))))
        block = replace(block, extra_tables=tuple(tables))
    if spec.type in ("rich_text", "stock_text") and block.ai_paragraphs:
        st.caption("Edit this source-linked wording in the wording and sources box above.")
        st.text(block.text)
    elif spec.type in ("rich_text", "stock_text"):
        text = st.text_area(spec.key.replace("_", " ").capitalize(), key=field(key + "_text_" + _signature(block.references), block.text), height=140)
        if text != block.text:
            block = replace(block, source="This month", text=text, reviewed_fingerprint="", client_reviewed_fingerprint="")
    elif spec.type in ("table", "work_order_grid") and (block.rows or not block.extra_tables):
        seed, config = _typed_table(spec, block.rows)
        rows = _grid(key + "_table_" + _signature(asdict(spec)), seed, num_rows="dynamic", hide_index=True, column_config=config)
        from app.monthly_report_editor import _cell_text
        columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
        edited_rows = tuple(tuple(_cell_text(row.get(c)) for c in columns) for row in rows
                            if any(v is not None and v != "" for v in row.values()))
        if rows != seed and edited_rows != block.rows:
            block = replace(block, source="This month", rows=edited_rows, reviewed_fingerprint="", client_reviewed_fingerprint="")
    if block.asset_hashes:
        from app.monthly_report_saved_pictures_ui import edit_saved_pictures
        block = edit_saved_pictures(block, key, lambda ref: assets.get(ref) or library.read_asset(state.profile.contract, state.profile.key, ref), show_preview=False)
    if spec.type in ("rich_text", "stock_text", "table", "work_order_grid"):
        if spec.key in ("training_summary", "equipment_issues"):
            with st.expander("Add a supporting photo (optional)"):
                photo = st.file_uploader("Photo to add to this section", type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_add_photo")
                if photo and st.button("Add this photo", key=key + "_add_photo_save"):
                    from pathlib import Path
                    try:
                        normalized = normalize_report_image(photo.getvalue(), Path(photo.name).suffix)
                        reference = library.asset_reference(normalized.data, normalized.extension)
                        assets[reference] = normalized.data
                        if reference not in block.asset_hashes:
                            captions = (*block.asset_captions, *("" for _ in range(len(block.asset_hashes) - len(block.asset_captions))), "")
                            block = replace(block, source="This month", asset_hashes=(*block.asset_hashes, reference), asset_captions=captions,
                                            reviewed_fingerprint="", client_reviewed_fingerprint="")
                    except (ValueError, OSError):
                        st.error("This photo could not be read. Choose another image; the existing section is retained.")
        return block
    from app.monthly_report_sections import readable_label
    if spec.type == "pdf_pages":
        with st.expander("Replace all report pages with one image (optional)"):
            upload = st.file_uploader("Replacement image for all pages in this part", type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    else:
        upload = st.file_uploader("Upload a new " + readable_label(spec.key).lower(), type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
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
    from app.monthly_report_sources import action_evidence, source_reference
    text, references = [], []
    for source in sources:
        if source.classification not in ("Vendor service", "Water treatment"):
            continue
        accepted, _ = action_evidence(source)
        for line, pages in accepted:
            refs = tuple(source_reference(source, n) for n in pages)
            action = ": ".join(v for v in (source.vendor, line) if v)
            action = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[contact omitted]", action)
            action = re.sub(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)", "[contact omitted]", action)
            rendered = "- " + action.strip()
            if rendered in existing.text.splitlines() and all(r in existing.references for r in refs):
                continue
            text.append(rendered)
            references.extend(refs)

    return merge_blocks(existing, ResolvedBlock("activity_summary", "This month", text="\n".join(text), references=tuple(references)))


def client_table_draft(draft):
    """Edit a price-free copy; saved history and non-table wording stay intact."""
    from app.monthly_report_content_policy import price_free_table
    blocks = {b.key: b for b in draft.blocks}
    sections, removed = [], []
    for section in draft.sections:
        specs = []
        for spec in section.blocks:
            if spec.key in blocks:
                spec, blocks[spec.key], labels = price_free_table(spec, blocks[spec.key])
                removed.extend(labels)
            specs.append(spec)
        sections.append(replace(section, blocks=tuple(specs)))
    return replace(draft, sections=tuple(sections), blocks=tuple(blocks.values())), tuple(dict.fromkeys(removed))


def _render_ordered_section(draft, section, blocks, specs, state, prefix, assets, field):
    """Edit one report section without splitting standing and monthly content."""
    from app.monthly_report_sections import readable_label
    draft = replace(draft, blocks=tuple(blocks.values()))
    profile, period = draft.profile, draft.period
    destination = {"activity": "activity_summary", "capital": "capital_renewal", "proposals": "proposals"}.get(section.key)
    if destination:
        from app.monthly_report_upload_ui import render_structured_uploads
        sources, additions, incoming_specs = render_structured_uploads(
            profile, period, prefix, field, destination, blocks=blocks, assets=assets)
        draft = replace(draft, sources=sources)
        if additions:
            # Structured readers return the updated destination block; their
            # attachment assets alone are incremental. Never append the prior
            # text/table a second time when applying a later upload.
            for key, block in additions.items():
                blocks[key] = merge_blocks(blocks.get(key), block) if key == "improvements" else block
            _forget_block_widgets(prefix, additions)
    local_destination = {"maintenance": "vendor_reports", "water": "water_reports", "mbcx": "mbcx_report", "scorecards": "utility_analysis"}.get(section.key)
    if local_destination:
        from app.monthly_report_upload_ui import render_section_uploads
        sources, additions, incoming_specs = render_section_uploads(
            profile, period, prefix, field, local_destination, blocks=blocks, assets=assets)
        draft = replace(draft, sources=sources)
        if additions:
            draft, blocks = _apply_prepared(draft, blocks, additions, incoming_specs, prefix)
    if section.key == "activity":
        if st.checkbox("Add work-order spreadsheets", key=field(prefix + "_batch_files_open", False)):
            from app.monthly_report_upload_ui import render_uploads
            sources, additions, incoming_specs = render_uploads(profile, period, prefix, field)
            draft = replace(draft, sources=sources)
            if additions and st.button("Add prepared pages and tables to this draft", key=prefix + "_apply_uploads"):
                draft, blocks = _apply_prepared(draft, blocks, additions, incoming_specs, prefix)
        from app.monthly_report_ai_ui import render_drafting
        # One shared evidence workspace: rendering this once avoids duplicated
        # source/job widget identities when every report section is visible.
        draft, blocks = render_drafting(draft, blocks, prefix, field, allowed_keys={spec.key for spec in section.blocks})
    if section.key != "activity":
        from app.monthly_report_ai_ui import edit_linked_paragraphs
        blocks = edit_linked_paragraphs(draft, blocks, prefix, field, {spec.key for spec in section.blocks})
    specs.update({b.key: b for current in draft.sections for b in current.blocks})
    if section.key in ("issues", "proposals"):
        from app.monthly_report_followups import render_followups
        draft = render_followups(draft, prefix, field, category="issue" if section.key == "issues" else "proposal")
    handled = set()
    if section.key == "training":
        from app.monthly_report_training_ui import render_training
        blocks = render_training(draft, blocks, prefix, field)
        handled.add("training_summary")
    if section.key == "organization":
        from app.monthly_report_organization_ui import render_organization
        blocks = render_organization(draft, blocks, specs, prefix, assets, field,
            lambda spec, block: _edit_content(spec, block, state, prefix, assets, field, draft), show_preview=False)
        handled.update(spec.key for spec in _standing_specs(section))
    if section.key == "mbcx":
        from app.monthly_report_mbcx_ui import render_mbcx
        status = blocks.get("mbcx_status", ResolvedBlock("mbcx_status", "This month"))
        pages = blocks.get("mbcx_report", ResolvedBlock("mbcx_report", "This month"))
        blocks["mbcx_status"], blocks["mbcx_report"] = render_mbcx(
            status, pages, prefix, field,
            lambda block: _edit_content(specs["mbcx_report"], block, state, prefix, assets, field, draft))
        blocks["mbcx_status"] = _review_carried_update(blocks["mbcx_status"], period, prefix)
        handled.update(("mbcx_status", "mbcx_report"))
    for original_spec in section.blocks:
        if original_spec.key in handled:
            continue
        spec = specs[original_spec.key]
        block = blocks.get(spec.key, ResolvedBlock(spec.key, "This month"))
        st.markdown("**" + readable_label(spec.key) + "**")
        if spec.key == "thermal_capacity":
            from app.monthly_report_capacity_ui import render_capacity
            before = block
            draft, block = render_capacity(draft, block, prefix, field)
            if block != before:
                _forget_block_widgets(prefix, {spec.key})
            spec = next((item for current in draft.sections for item in current.blocks if item.key == spec.key), spec)
            specs[spec.key] = spec
        if spec.key in ("contact_matrix", "subcontractor_matrix"):
            from app.monthly_report_visual_ui import edit_contacts
            block = edit_contacts(draft, spec, block, prefix, assets, field, show_preview=False)
        else:
            block = _edit_content(spec, block, state, prefix, assets, field, draft)
        if spec.key in MONTHLY_EDIT_KEYS:
            block = _review_carried_update(block, period, prefix)
        blocks[spec.key] = block
    return draft, blocks


def render_guided_workflow(browser_token, browser_timezone, field, move):
    last_contract, last_profile = remembered_report_preferences(browser_token)
    with st.expander("First time here? How to finish a monthly report"):
        st.write("1. Choose your contract and the sites that belong in **one** report.\n2. Use a saved design, the general template, or a starting report.\n3. Scroll through the sections in report order and update them beside their previews. Every section stays in the report, including sections you leave blank.\n4. Review the whole report, then download DOCX and PDF.")
        st.write("For vendor and chemical reports, check each page preview, then choose **Include page and continue** or **Leave page out and continue**. The next page needing review opens for you. Prices, legal-only pages and blank/signature-only pages do not belong in the client report.")
        st.caption("You can edit the sections in any order. Save progress before leaving; return to the same sites and month to continue. Each section updates beside its fields. Review and download is at the bottom.")
    with st.expander("What will be remembered?"):
        st.write("**For these sites:** saved report designs, logos, org charts, contacts and monthly drafts are shared. Anyone choosing the same contract and exact sites can continue the saved report, even on a different device.")
        st.write("**On this browser:** after you save, we remember your last contract/site selection and the name you entered for that report. A different browser, private browsing or cleared browser data may require selecting them again. Your reports remain saved.")
        st.write("**Next month:** we reuse the latest saved earlier report for these exact sites. Layout and site information carry forward; monthly activity, vendor/chemical attachments and photos start fresh. Open issues and proposals remain follow-ups to review.")
        st.caption("Use Save progress before leaving. Changes are not automatically saved. Your entered name records your edits; it is not a login or verified identity. Check it on a shared device.")
        if st.button("Check available storage", key="report_storage_check"):
            from app.monthly_report_storage import storage_summary
            try:
                st.session_state["report_storage_summary"] = storage_summary()
            except OSError:
                st.session_state.pop("report_storage_summary", None)
                st.warning("Storage could not be measured right now. Your saved reports were not changed.")
        if storage := st.session_state.get("report_storage_summary"):
            from app.monthly_report_storage import readable_bytes
            st.write(f"Disk capacity: {readable_bytes(storage['total'])} · Available: {readable_bytes(storage['free'])} · Monthly report files: {'at least ' if not storage['complete'] else ''}{readable_bytes(storage['monthly'])}")
            st.caption("Measured when you click Check available storage. The disk is also used by other app workflows. Originals are retained. Identical new assets and source files share one stored copy across all contracts and sites. Monthly history keeps references, so changing one site's selection does not change another report. Existing files can be consolidated below.")
            if storage["free"] < max(512 * 1024 * 1024, storage["total"] * .05):
                st.warning("Storage is running low. Keep space available before importing more large reports. This check does not delete anything.")
        if st.button("Consolidate duplicate stored files", key="report_storage_consolidate"):
            from app.monthly_report_objects import consolidate_existing
            from app.monthly_report_storage import storage_summary, readable_bytes
            try:
                with st.spinner("Sharing identical stored files; originals and history remain available…"):
                    result = consolidate_existing()
                st.session_state["report_storage_summary"] = storage_summary()
                st.success(f"Consolidated {result['changed']} files; released {readable_bytes(result['reclaimed'])} from duplicate copies.")
                if not result["complete"]:
                    st.info("This batch is complete. Run consolidation again to continue through the remaining files.")
            except (ValueError, OSError):
                st.warning("Consolidation stopped. Original paths and report history remain available; completed files can safely be reused when you retry.")
    from app.monthly_report_start_ui import choose_contract, select_sites, starting_choice
    contract = choose_contract(last_contract, field)
    if not contract:
        return
    period = month_selector(field, "report", suggested_period(operator_today(browser_timezone)))
    st.caption("Suggested month: previous month on days 1–10; current month thereafter. Change it whenever needed.")
    profiles = library.list_profiles(contract)
    completed_setup = st.session_state.pop("report_setup_done", None)
    remembered = last_profile if last_contract == contract else ""
    returning = any(p.key == remembered for p in profiles) and not completed_setup
    site_box = st.expander("Report sites — expand to change", expanded=False) if returning else st.container()
    with site_box:
        candidate, existing = select_sites(contract, profiles, remembered, field, completed_setup)
    if not candidate:
        return
    if not existing:
        starting_choice(candidate, profiles, period, "", field)
        return
    selected = existing.key
    state = library.load_profile(contract, selected)
    profile = state.profile
    st.subheader(profile.title)
    st.caption(profile.scope_type.replace("_", " ").capitalize() + " · " + "; ".join(f.title for f in profile.facilities))
    prefix = "report_guided_" + _signature((contract, selected, period.key))
    assets = st.session_state.setdefault(prefix + "_assets", {})
    snapshot = library.load_snapshot(contract, selected, period)
    imported = library.load_imported_draft(contract, selected)
    if completed_setup == selected:
        record_report_preferences(browser_token, contract, selected)
        if imported:
            record_report_preparer(browser_token, contract, selected, imported.prepared_by)
    from app.monthly_report_start import latest_snapshot, latest_saved_draft, refresh_profile_identity
    prior = latest_snapshot(contract, selected, period)
    prior_draft = latest_saved_draft(contract, selected, period, before=True)
    draft_key = prefix + "_draft"
    resume = st.session_state.get("report_resume_import") == (contract, selected, period.key)
    if draft_key not in st.session_state or resume:
        prepared = remembered_report_preparer(browser_token, contract, selected)
        using_import = False
        preserve_saved_defaults = False
        pending_import = imported and imported.period == period and (not snapshot or snapshot.revision == library.imported_snapshot_revision(contract, selected))
        if imported and (resume or pending_import):
            draft = imported
            using_import = True
            st.session_state.pop("report_resume_import", None)
        elif snapshot:
            draft = snapshot.draft
            preserve_saved_defaults = True
        elif imported and imported.period == period:
            draft = imported
            using_import = True
        elif prior_draft:
            draft = replace(new_month_draft(prior_draft, period), profile=profile)
            preserve_saved_defaults = True
        else:
            draft = _initial_draft(state, period, prepared)
        # A shared report's author is not the identity of a new visitor.
        # Only a setup/import just completed in this session can seed that name.
        current_actor = prepared or (draft.prepared_by if completed_setup == selected or resume else "")
        draft = complete_guided_sections(replace(draft, prepared_by=current_actor))
        from app.monthly_report_designs import pin
        draft = replace(draft, profile=pin(draft.profile, latest_master=not bool(snapshot)))
        if not preserve_saved_defaults:
            from app.monthly_report_capacity import resolve_capacity
            from app.monthly_report_workflow_standards import apply_defaults as apply_workflow_defaults
            draft = apply_workflow_defaults(resolve_capacity(draft), assets)
        st.session_state[draft_key] = draft
        # A saved empty standing block is an intentional report choice, not a
        # first-use gap. Preserve it on reopen and next-month rollover alike.
        st.session_state[prefix + "_directory_defaults_attempted"] = preserve_saved_defaults
        st.session_state[prefix + "_revision"] = library.imported_snapshot_revision(contract, selected) if using_import else snapshot.revision if snapshot else 0
    from app.monthly_report_setup import normalize_mbcx
    draft, removed_prices = client_table_draft(complete_guided_sections(normalize_mbcx(refresh_profile_identity(st.session_state[draft_key], profile))))
    if removed_prices:
        st.info("Price columns were left out of this working report: " + ", ".join(removed_prices) + ". The saved original remains available. Check the remaining wording and images for prices before download.")
    if snapshot:
        st.info(f"Continue your saved {period.label} report for these sites. Your saved work is here; you do not need to upload the old report again.")
    elif prior_draft:
        st.info(f"Your {period.label} starting point is the saved {prior_draft.period.label} report for these exact sites. Add this month’s work and update any site information that changed.")
    else:
        st.info("Your design for these sites is saved. Update this month’s work and any site information that changed, then review and download. Every section stays in the report.")
    prepared = st.text_input("Prepared by", key=field(prefix + "_prepared", draft.prepared_by))
    st.caption("Use your own name. It is remembered on this browser after saving; another person's saved report does not identify you.")
    draft = replace(draft, prepared_by=prepared)
    if prepared.strip() and not st.session_state.get(prefix + "_directory_defaults_attempted"):
        from app.monthly_report_directory import apply_defaults
        draft = apply_defaults(draft)
        st.session_state[prefix + "_directory_defaults_attempted"] = True
    from app.monthly_report_directory_ui import render_selected_directory
    render_selected_directory(contract, profile.facilities, prepared, prefix)
    if candidate != profile:
        st.caption("The updated group name/scope will be remembered after you save it.")
        if st.button("Save group name", disabled=not prepared.strip(), key=prefix + "_rename_save"):
            library.save_profile(candidate, expected_revision=state.revision, actor=prepared, confirmed=True)
            st.session_state[draft_key] = replace(draft, profile=candidate)
            st.rerun()
    save_status = st.empty()
    from app.monthly_report_asset_review import refresh_asset_source_context
    from app.monthly_report_section_preview_ui import render_section_preview
    blocks = {b.key: refresh_asset_source_context(b, draft.sources) for b in draft.blocks}
    specs = {b.key: b for s in draft.sections for b in s.blocks} | {b.key: b for b in layout_blocks()}
    from app.monthly_report_sources import ingest, source_bytes
    if prefix + "_evidence" not in st.session_state and draft.sources:
        st.session_state[prefix + "_evidence"] = tuple(
            replace(ingest(profile, source.filename, source_bytes(profile, source))[0], source=source)
            for source in draft.sources
        )
    st.caption("Work down the report in order. Existing information stays in place; update only what changed.")
    editor_column, preview_column = st.columns(2, gap="large")
    with editor_column:
        from app.monthly_report_cover_ui import render_cover
        blocks = render_cover(draft, blocks, prefix, assets, field,
                              lambda ref: assets.get(ref) or library.read_asset(contract, selected, ref))
        from app.monthly_report_section_ui import render_section_setup
        render_section_setup(contract, period, prepared, field, state=state,
                             working_draft=replace(draft, blocks=tuple(blocks.values())),
                             working_assets=tuple(assets.items()), working_revision=st.session_state[prefix + "_revision"])
        with st.expander("Report design and version"):
            from app.monthly_report_designs_ui import render_design_settings
            render_design_settings(replace(draft, blocks=tuple(blocks.values())), prefix)
    with preview_column:
        render_section_preview(replace(draft, blocks=tuple(blocks.values())), "cover", assets, prefix, deferred=True)
    for section in draft.sections:
        st.divider()
        st.subheader(section.title, anchor="report-section-" + section.key)
        st.caption(section_help(section.key).guidance)
        editor_column, preview_column = st.columns(2, gap="large")
        with editor_column:
            draft, blocks = _render_ordered_section(draft, section, blocks, specs, state, prefix, assets, field)
        with preview_column:
            render_section_preview(replace(draft, blocks=tuple(blocks.values())), section.key, assets, prefix, deferred=True)
    blocks = {key: refresh_asset_source_context(block, draft.sources) for key, block in blocks.items()}
    draft = complete_guided_sections(replace(draft, blocks=tuple(blocks.values())))
    footer = blocks.get("footer_text")
    if footer:
        draft = replace(draft, address_line=footer.text if footer.source != "Omit" else "")
    st.session_state[draft_key] = draft
    if snapshot and snapshot.draft.fingerprint == draft.fingerprint:
        save_status.success(f"Saved · version {snapshot.revision} · {period.label} · {snapshot.entered_editor or snapshot.draft.prepared_by}")
    elif snapshot:
        save_status.info(f"You have changes to save. Version {snapshot.revision} is safely stored; use Save progress below before leaving.")
    elif prior_draft:
        save_status.info(f"Starting from your saved {prior_draft.period.label} report for these exact sites. Monthly work and attachments start fresh; site information carries forward.")
    else:
        save_status.info("Your starting design is saved. Use Save progress below to store the changes you make for this month.")
    current_revision = snapshot.revision if snapshot else 0
    conflict = current_revision != st.session_state[prefix + "_revision"]
    if conflict:
        st.warning("Another version was saved. Your working draft is preserved. Compare it with the saved report before creating another version.")
        with st.expander("Compare saved content"):
            from app.monthly_report_compare_ui import render_conflict_comparison
            render_conflict_comparison(draft, snapshot,
                working_asset_loader=lambda ref: assets.get(ref) or library.read_asset(contract, selected, ref),
                saved_asset_loader=lambda ref: library.read_asset(contract, selected, ref))
        accept = st.checkbox("I compared the saved version and want to save my draft as the next version", key=prefix + f"_accept_{current_revision}")
        if st.button("Accept current revision", key=prefix + "_accept_revision", disabled=not accept):
            st.session_state[prefix + "_revision"] = current_revision
            st.rerun()
    st.caption("Save progress stores this version so others working on this report can continue it.")
    if not prepared.strip():
        st.caption("Enter your name in Prepared by above to save your progress.")
    if st.button("Save progress", key=prefix + "_save", disabled=conflict or not prepared.strip()):
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
    st.divider()
    with st.container():
        st.subheader("Review and download")
        from app.monthly_report_editor import review_client_images
        draft = review_client_images(draft, assets, prefix, field)
        st.session_state[draft_key] = draft
        if package and package.fingerprint != draft.fingerprint:
            st.session_state.pop(prefix + "_package", None)
            package = None
        for title, _, pages in outline(draft):
            st.write(f"{title} · at least {pages} pages")
        loader = lambda ref: assets[ref] if ref in assets else library.read_asset(contract, selected, ref)
        estimated = estimate_bytes(draft, loader)
        st.caption(f"Estimated document size: {estimated / (1024 * 1024):.1f} MB. Aim for under 15 MB; fewer attachment pages and more photos per page can help.")
        checks = [check for check in preflight(draft, estimated) if check.code != "empty"]
        if any(c.blocking for c in checks):
            st.info("Complete the items below to unlock your downloads. Sections may remain blank.")
        for check in checks:
            (st.error if check.blocking else st.warning)(review_message(check, draft))
        warnings_ok = not any(not c.blocking for c in checks)
        if not warnings_ok:
            warnings_ok = st.checkbox("I checked these specific warnings", key=prefix + "_warnings_" + draft.fingerprint)
        if st.button("Generate DOCX and PDF", key=prefix + "_generate", type="primary",
                     disabled=conflict or any(c.blocking for c in checks) or not warnings_ok):
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
