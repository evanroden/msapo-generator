"""Profile library and source-selection UI for the second report milestone."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
from pathlib import Path
import re

import streamlit as st

from app import contracts, monthly_report_library as library
from app.config import operator_today
from app.memory import record_report_preparer, remembered_report_preparer
from app.monthly_report_checks import preflight
from app.monthly_report_docx import estimate_bytes, generate_report, normalize_report_image, outline
from app.monthly_report_model import (
    BLOCK_SOURCES, STOCK_TEXTS, BlockSpec, Facility, ReportDraft, ReportPeriod,
    ReportProfile, ResolvedBlock, default_sections, layout_blocks, profile_sections,
)
from app.ui_highlight import highlight_needed_fields


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:60]


def _signature(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _preview(block: ResolvedBlock | None, assets: dict[str, bytes], profile: ReportProfile) -> None:
    if block is None:
        st.caption("No saved content")
        return
    if block.text:
        st.text(block.text)
    if block.rows:
        st.dataframe(list(block.rows), hide_index=True)
    if len(block.asset_hashes) > 1:
        st.caption(f"{len(block.asset_hashes)} prepared images/pages; previewing the first. Review individual pages in monthly evidence.")
    for reference in block.asset_hashes[:1]:
        raw = assets.get(reference) or library.read_asset(profile.contract, profile.key, reference)
        st.image(raw, width="stretch")


def _grid(key: str, seed: list[dict], **kwargs) -> list[dict]:
    """Keep the editor's input stable while Streamlit reapplies edit deltas."""
    data_key = key + "_data"
    if key not in st.session_state:
        st.session_state[data_key + "_seed"] = st.session_state.get(data_key, seed)
    rows = st.data_editor(st.session_state[data_key + "_seed"], key=key, **kwargs)
    st.session_state[data_key] = rows
    return rows


def _profile_manager(contract: str, state: library.LibraryState | None, field) -> None:
    """All shared writes require an editor name and a revision-bound confirmation."""
    profile = state.profile if state else None
    revision = state.revision if state else 0
    prefix = f"report_manage_{_signature((contract, profile.key if profile else 'new', revision))}"
    with st.expander("Profile library · create or edit", expanded=state is None):
        st.caption("Changes are shared with everyone using this app. Versions can be restored. Editor names are recorded as entered.")
        title = st.text_input("Profile display title", key=field(prefix + "_title", profile.title if profile else ""))
        scope = st.selectbox("Report scope", ("individual", "multi_site", "regional"),
                             format_func=lambda value: {"individual": "Individual facility", "multi_site": "Multiple sites", "regional": "Region"}[value],
                             key=field(prefix + "_scope", profile.scope_type if profile else "individual"))
        members = _grid(prefix + "_members", [
            {"Identity": f.key, "Facility": f.title, "Alternate names": "; ".join(f.aliases)} for f in profile.facilities
        ] if profile else [{"Identity": "", "Facility": "", "Alternate names": ""}], num_rows="dynamic", hide_index=True,
            disabled=["Identity"], column_config={"Identity": None, "Alternate names": st.column_config.TextColumn(help="Separate aliases with semicolons. An alias does not add another facility.")})
        order_default = list(profile.section_order) if profile and profile.section_order else [s.key for s in default_sections()]
        order_text = st.text_area("Default section order", key=field(prefix + "_order", "\n".join(order_default)),
                                  help="One section name per line. Reorder these lines; all section names must remain present.")
        excluded = st.multiselect("Sections omitted by default", [s.key for s in default_sections()],
                                  key=field(prefix + "_excluded", list(profile.excluded_sections) if profile else ["rfi"]))
        existing_sources = dict(profile.default_block_sources) if profile else {}
        sources = _grid(prefix + "_sources", [
            {"Block": b.key, "Default source": existing_sources.get(b.key, "Stock text" if b.stock_text_keys else "Library")}
            for s in default_sections() for b in s.blocks
        ], disabled=["Block"], hide_index=True,
            column_config={"Default source": st.column_config.SelectboxColumn(options=BLOCK_SOURCES, required=True)})
        actor = st.text_input("Library editor name", key=field(prefix + "_actor", ""))
        try:
            facilities = tuple(Facility(
                row.get("Identity") or _key(row["Facility"]),
                row["Facility"].strip(), tuple(a.strip() for a in (row.get("Alternate names") or "").split(";") if a.strip()),
            ) for row in members if str(row.get("Facility") or "").strip())
            candidate = ReportProfile(contract, profile.key if profile else _key(title), title.strip(), facilities, scope,
                                      tuple(v.strip() for v in order_text.splitlines() if v.strip()),
                                      tuple((row["Block"], row["Default source"]) for row in sources),
                                      excluded_sections=tuple(excluded), block_overrides=profile.block_overrides if profile else (),
                                      section_titles=profile.section_titles if profile else (),
                                      section_block_order=profile.section_block_order if profile else (),
                                      imported_from=profile.imported_from if profile else "")
        except (ValueError, TypeError, KeyError) as exc:
            candidate = None
            st.caption(str(exc))
        confirmation_id = _signature((asdict(candidate) if candidate else None, actor, revision))
        confirmed = st.checkbox("I confirm this shared profile change", key=prefix + "_confirm_" + confirmation_id)
        if st.button("Save profile", key=prefix + "_save", disabled=not (candidate and actor.strip() and confirmed)):
            try:
                library.save_profile(candidate, expected_revision=revision, actor=actor, confirmed=confirmed)
                st.success("Profile saved.")
                st.rerun()
            except (library.LibraryError, OSError) as exc:
                st.error(str(exc))
        if state:
            st.caption(f"Current revision: {revision}")
            if revision > 1:
                historical = st.number_input("Profile revision to restore", 1, revision, key=prefix + "_restore_version")
                approved = st.checkbox("Restore this profile definition", key=prefix + f"_restore_confirm_{historical}")
                if st.button("Restore profile", key=prefix + "_restore", disabled=not (approved and actor.strip())):
                    try:
                        library.restore_profile(contract, profile.key, int(historical), expected_revision=revision,
                                                actor=actor, confirmed=approved)
                        st.rerun()
                    except (library.LibraryError, OSError) as exc:
                        st.error(str(exc))
            with st.expander("Library history"):
                versions = {v.id: v for v in reversed(state.versions)}
                selected_version = st.selectbox("Version to inspect", list(versions), index=0 if versions else None,
                                                format_func=lambda key: f"{versions[key].label} · {versions[key].updated_at}",
                                                key=prefix + "_history_selection", disabled=not versions)
                # Inspect one version at a time. Rendering every historical
                # image on every rerun scales badly for photo-heavy libraries.
                if selected_version:
                    version = versions[selected_version]
                    st.write(f"{version.label} · {version.updated_at} · {version.actor}")
                    for reference in version.block.asset_hashes:
                        st.caption(f"Used in {library.usage_count(contract, profile.key, reference)} reports")
                    with st.expander("Compare this version"):
                        left, right = st.columns(2)
                        with left:
                            st.caption("Current library version")
                            _preview(state.block(version.slot), {}, profile)
                        with right:
                            st.caption("Version to restore")
                            _preview(version.block, {}, profile)
                    restore_ok = st.checkbox("I confirm restoring this block version", key=prefix + "_restore_ok_" + version.id)
                    if st.button("Restore this block version", key=prefix + "_version_" + version.id,
                                 disabled=not (restore_ok and actor.strip())):
                        try:
                            library.restore_block(contract, profile.key, version.id, expected_revision=revision,
                                                  actor=actor, confirmed=True)
                            st.rerun()
                        except (library.LibraryError, OSError) as exc:
                            st.error(str(exc))
                st.dataframe(list(state.audit), hide_index=True)


def _block_editor(spec: BlockSpec, state: library.LibraryState, previous: dict[str, ResolvedBlock],
                  default_source: str, prefix: str, assets: dict[str, bytes], field,
                  monthly_blocks: dict[str, ResolvedBlock] | None = None) -> ResolvedBlock:
    key = prefix + "_" + spec.key
    saved = state.block(spec.key)
    source = st.selectbox("Source", BLOCK_SOURCES, key=field(key + "_source", default_source))
    if source == "Omit":
        return ResolvedBlock(spec.key, source)
    if source == "This month" and monthly_blocks and spec.key in monthly_blocks:
        mode = st.radio("This month's content", ["Uploaded content", "Edit manually"],
                        key=field(key + "_monthly_mode", "Uploaded content"))
        if mode == "Uploaded content":
            _preview(monthly_blocks[spec.key], assets, state.profile)
            return monthly_blocks[spec.key]
    if source in ("Library", "Last month"):
        block = saved if source == "Library" else previous.get(spec.key)
        if source == "Library" and spec.type in ("image_page", "image_grid", "pdf_pages"):
            versions = {v.id: v for v in state.versions if v.block.asset_hashes}
            chosen = st.selectbox("Library image", ["Profile default", *versions],
                                  format_func=lambda value: value if value == "Profile default" else f"{versions[value].label} · {versions[value].updated_at}",
                                  key=field(key + "_library_image", "Profile default"))
            if chosen != "Profile default":
                block = replace(versions[chosen].block, key=spec.key)
        if block is None:
            st.info("No content available from this source. Choose another source or replace it.")
            return ResolvedBlock(spec.key, source)
        if source == "Library":
            current_id = dict(state.current).get(spec.key)
            if current_id:
                st.caption("Last updated: " + state.version(current_id).updated_at)
        _preview(block, assets, state.profile)
        return replace(block, source=source)
    if source == "Stock text":
        if not spec.stock_text_keys:
            st.info("No stock paragraph is defined for this block.")
            return ResolvedBlock(spec.key, source)
        chosen = st.selectbox("Stock paragraph", spec.stock_text_keys, format_func=lambda value: STOCK_TEXTS[value],
                              key=field(key + "_stock", spec.stock_text_keys[0]))
        return ResolvedBlock(spec.key, source, text=STOCK_TEXTS[chosen])
    starting = previous.get(spec.key) or saved or ResolvedBlock(spec.key, source)
    if spec.type in ("image_page", "image_grid", "pdf_pages"):
        label = "Replace org chart" if spec.key == "org_chart" else "Replace " + spec.key.replace("_", " ")
        uploaded = st.file_uploader(label, type=["png", "jpg", "jpeg", "webp", "heic", "heif"], key=key + "_upload",
                                    help="Choose Replace once for this report or Replace and save to library for future reports.")
        once_key = key + "_replacement"
        if uploaded:
            digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
            if st.session_state.get(once_key + "_digest") != digest:
                try:
                    normalized = normalize_report_image(uploaded.getvalue(), Path(uploaded.name).suffix,
                                                        line_art=spec.key in ("org_chart", "contact_matrix", "business_hours_workflow", "after_hours_workflow"))
                    reference = library.asset_reference(normalized.data, normalized.extension)
                    assets[reference] = normalized.data
                    st.session_state[once_key] = reference
                    st.session_state[once_key + "_digest"] = digest
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                    # An invalid replacement must not leave an older image
                    # selected behind the error message.
                    st.session_state.pop(once_key, None)
        reference = st.session_state.get(once_key)
        text = st.text_input("Caption", key=field(key + "_caption", ""))
        block = ResolvedBlock(spec.key, source, text=text, asset_hashes=(reference,) if reference else ())
    elif spec.type in ("table", "work_order_grid"):
        columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
        seed, config = _typed_table(spec, starting.rows)
        rows = _grid(key + "_grid_" + _signature(asdict(spec)), seed, num_rows="dynamic", hide_index=True, column_config=config)
        # False and zero are real entries; truthiness must not erase them.
        block = ResolvedBlock(spec.key, source, rows=tuple(
            tuple(_cell_text(row.get(col)) for col in columns) for row in rows
            if any(value is not None and value != "" for value in row.values())))
    else:
        text = st.text_area("Report text", key=field(key + "_text", starting.text), height=160)
        block = ResolvedBlock(spec.key, source, text=text)
    if source == "Replace and save to library":
        left, right = st.columns(2)
        with left:
            st.caption("Current library version")
            _preview(saved, assets, state.profile)
        with right:
            st.caption("Proposed replacement")
            _preview(block, assets, state.profile)
        actor = st.text_input("Editor name", key=field(key + "_actor", ""))
        label = st.text_input("Library label", key=field(key + "_label", spec.key.replace("_", " ")))
        confirmation_id = _signature((state.revision, block.fingerprint, actor, label))
        confirmed = st.checkbox("Save this replacement as a new shared library version", key=key + "_confirm_" + confirmation_id)
        has_content = bool(block.text.strip() or block.rows or block.asset_hashes)
        if st.button("Confirm library replacement", key=key + "_save", disabled=not (confirmed and actor.strip() and has_content)):
            try:
                library.replace_block(state.profile.contract, state.profile.key, spec.key, replace(block, source="Library"),
                                      label=label, actor=actor, confirmed=confirmed, expected_revision=state.revision,
                                      assets=tuple((ref, assets[ref]) for ref in block.asset_hashes if ref in assets))
                st.rerun()
            except (library.LibraryError, OSError) as exc:
                st.error(str(exc))
        if saved != replace(block, source="Library"):
            block = replace(block, pending_library_save=True)
    else:
        _preview(block, assets, state.profile)
    return block


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _typed_table(spec: BlockSpec, rows) -> tuple[list[dict], dict]:
    """Convert persisted strings back to typed, editable values without guessing."""
    config = {}
    converters = {}
    for column in spec.columns:
        if column.type in ("number", "currency"):
            config[column.title] = st.column_config.NumberColumn(format="%.2f" if column.type == "currency" else None)
            converters[column.title] = float
        elif column.type == "date":
            config[column.title] = st.column_config.DateColumn(format="YYYY-MM-DD")
            converters[column.title] = date.fromisoformat
        elif column.type == "boolean":
            config[column.title] = st.column_config.CheckboxColumn()
            def boolean(value):
                if value.casefold() not in ("yes", "no", "true", "false", "x", "✓"):
                    raise ValueError("Use Yes or No in a checkbox column.")
                return value.casefold() in ("yes", "true", "x", "✓")
            converters[column.title] = boolean
        else:
            config[column.title] = st.column_config.TextColumn()
            converters[column.title] = str
    columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
    seed = [{col: (converters.get(col, str)(value) if value != "" else None)
             for col, value in zip(columns, row)} for row in rows]
    return seed or [dict.fromkeys(columns)], config


def render_profile_workflow(browser_token: str, browser_timezone: str, field, move) -> None:
    st.subheader("1. Choose the report")
    names = contracts.contract_names()
    contract = st.selectbox("Contract", names, key=field("report_contract", names[0]))
    try:
        profiles = library.list_profiles(contract)
    except library.LibraryError as exc:
        st.error(str(exc))
        return
    if not profiles:
        st.info("Create a profile below. Each profile can cover one facility, several sites, or a region.")
        st.caption("Once the profile is saved, Import an existing DOCX can reuse report images, tables and text through confirmed mappings (up to 128 MB).")
        _profile_manager(contract, None, field)
        return
    selected = st.selectbox("Report profile", [p.key for p in profiles],
                            format_func=lambda key: next(p.title for p in profiles if p.key == key),
                            key=field(f"report_profile_{_key(contract)}", profiles[0].key))
    state = library.load_profile(contract, selected)
    profile = state.profile
    st.write("Facilities: " + "; ".join(f.title for f in profile.facilities))
    st.caption("Scope: " + profile.scope_type.replace("_", " "))
    from app.monthly_report_setup import month_selector, suggested_period
    period = month_selector(field, "report", suggested_period(operator_today(browser_timezone)))
    st.caption("To import an older or partially completed report, return to the guided report’s first step. Save any current advanced edits first.")
    prefix = "report_draft_" + _signature((contract, profile.key, period.key))
    current = library.load_snapshot(contract, profile.key, period)
    prior = current or library.load_snapshot(contract, profile.key, ReportPeriod.previous(period.start))
    if prior and not current:
        from app.monthly_report_setup import new_month_draft
        prior = replace(prior, draft=new_month_draft(prior.draft, period))
    start_choices = (["Saved work for this month" if current else "Last month's report for this profile"] if prior else []) + ["The profile's library template"]
    start = st.radio("Start from", start_choices, key=field(prefix + "_start", start_choices[0]))
    from_prior = bool(prior and start == start_choices[0])
    previous = {b.key: b for b in prior.draft.blocks} if prior else {}
    prepared_key = field(prefix + "_prepared", remembered_report_preparer(browser_token, contract, profile.key)
                         or (prior.draft.prepared_by if prior else "ENFRA Asset Management Team"))
    prepared = st.text_input("Prepared by", key=prepared_key)
    from app.monthly_report_upload_ui import render_uploads
    report_sources, monthly_blocks, monthly_specs = render_uploads(profile, period, prefix, field)
    st.caption("AI drafts and Copilot context are coming next. Review the extracted facts and enter narrative text in the report blocks now.")

    st.subheader("5. Assemble the report")
    base_sections = prior.draft.sections if from_prior else profile_sections(profile)
    if not from_prior:
        overrides = {b.key: b for b in profile.block_overrides}
        base_sections = tuple(replace(s, blocks=tuple(overrides.get(b.key, b) for b in s.blocks)) for s in base_sections)
    by_key = {s.key: s for s in base_sections}
    start_key = prefix + "_" + _signature(start)
    order_key = field(start_key + "_order", [s.key for s in base_sections] if from_prior else list(profile.section_order) or [s.key for s in base_sections])
    assets = st.session_state.setdefault(prefix + "_assets", {})
    sections, blocks = [], []
    defaults = dict(profile.default_block_sources)
    layout = {b.key: b for b in layout_blocks()}
    with st.expander("Cover, logos and address footer"):
        st.caption("Brand artwork and site photos are stored with this profile on the persistent disk.")
        for key in ("brand_logo", "client_logo", "cover_photo", "footer_text"):
            st.markdown("**" + key.replace("_", " ").capitalize() + "**")
            default = "Last month" if from_prior and key in previous else "Library" if state.block(key) else "Omit"
            blocks.append(_block_editor(layout[key], state, previous, default, start_key, assets, field))
    for index, key in enumerate(st.session_state[order_key]):
        section = by_key[key]
        section_prefix = start_key + "_" + key
        with st.expander(section.title):
            included = st.toggle("Include section", key=field(section_prefix + "_include", section.included if from_prior else key not in profile.excluded_sections))
            left, right = st.columns(2)
            left.button("Move up", key=section_prefix + "_up", disabled=index == 0, on_click=move, args=(order_key, key, -1))
            right.button("Move down", key=section_prefix + "_down", disabled=index == len(by_key) - 1, on_click=move, args=(order_key, key, 1))
            title = st.text_input("Section title", key=field(section_prefix + "_title", section.title))
            with st.expander("Divider photo"):
                divider_key = "divider_" + key
                default = "Last month" if from_prior and divider_key in previous else "Library" if state.block(divider_key) else "Omit"
                divider = _block_editor(layout[divider_key], state, previous, default, start_key, assets, field)
                blocks.append(divider)
            block_order_key = field(section_prefix + "_block_order", [b.key for b in section.blocks])
            specs = {b.key: b for b in section.blocks}
            ordered_specs = []
            for position, block_key in enumerate(st.session_state[block_order_key]):
                spec = specs[block_key]
                st.markdown("**" + spec.key.replace("_", " ").capitalize() + "**")
                left, right = st.columns(2)
                left.button("Move block up", key=section_prefix + "_" + block_key + "_up", disabled=position == 0,
                            on_click=move, args=(block_order_key, block_key, -1))
                right.button("Move block down", key=section_prefix + "_" + block_key + "_down", disabled=position == len(specs) - 1,
                             on_click=move, args=(block_order_key, block_key, 1))
                default_source = "Last month" if from_prior and spec.key in previous else defaults.get(spec.key, "Stock text" if spec.stock_text_keys else "Library")
                block = _block_editor(spec, state, previous, default_source, start_key, assets, field, monthly_blocks)
                blocks.append(block)
                ordered_specs.append(monthly_specs.get(spec.key, spec) if block is monthly_blocks.get(spec.key) else spec)
            sections.append(replace(section, title=title, included=included, blocks=tuple(ordered_specs),
                                    divider_asset=divider.asset_hashes[0] if divider.asset_hashes and divider.source != "Omit" else ""))
    footer = next(b for b in blocks if b.key == "footer_text")
    draft = ReportDraft(profile, period, prepared, tuple(sections), tuple(blocks),
                        address_line=footer.text if footer.source != "Omit" else "", sources=report_sources)
    loader = lambda ref: assets[ref] if ref in assets else library.read_asset(contract, profile.key, ref)
    with st.expander("Live outline"):
        for title, block_keys, pages in outline(draft):
            st.write(title)
            st.caption(f"{', '.join(block_keys)} · at least {pages} pages")
    st.subheader("6. Check and generate")
    estimated = estimate_bytes(draft, loader)
    st.caption(f"Estimated document size: {estimated / (1024 * 1024):.1f} MB. Target: under 15 MB.")
    checks = preflight(draft, estimated)
    for check in checks:
        (st.error if check.blocking else st.warning)(check.message)
    warning_ack = not any(not c.blocking for c in checks)
    if not warning_ack:
        warning_ack = st.checkbox("I've checked these warnings", key=prefix + "_ack_" + draft.fingerprint)
    needed = [prepared_key] if not prepared.strip() else []
    needed.extend(start_key + "_" + c.block_key + "_source" for c in checks if c.blocking and c.block_key)
    highlight_needed_fields(needed)
    package = st.session_state.get(prefix + "_package")
    if package and package.fingerprint != draft.fingerprint:
        st.session_state.pop(prefix + "_package", None)
        package = None
    current_snapshot = library.load_snapshot(contract, profile.key, period)
    revision_key = prefix + "_snapshot_revision"
    st.session_state.setdefault(revision_key, current_snapshot.revision if current_snapshot else 0)
    current_revision = current_snapshot.revision if current_snapshot else 0
    if st.session_state[revision_key] != current_revision:
        st.warning("Another report was saved for this month. Your draft is preserved; review the saved version before replacing it.")
        with st.expander("Compare the saved report with this draft"):
            left, right = st.columns(2)
            with left:
                st.caption("Saved report")
                for title, _, _ in outline(current_snapshot.draft):
                    st.write(title)
                st.json({b.key: {"text": b.text, "rows": b.rows, "images": b.asset_hashes} for b in current_snapshot.draft.blocks})
            with right:
                st.caption("This draft")
                st.json({b.key: {"text": b.text, "rows": b.rows, "images": b.asset_hashes} for b in draft.blocks})
        approved = st.checkbox("I've reviewed the saved report and want to generate a new version", key=prefix + f"_conflict_{current_revision}")
        if st.button("Use this draft for the next version", disabled=not approved, key=prefix + "_reload_revision"):
            st.session_state[revision_key] = current_revision
            st.rerun()
    if st.button("Generate DOCX and PDF", key=prefix + "_generate", type="primary",
                 disabled=any(c.blocking for c in checks) or not warning_ack or st.session_state[revision_key] != current_revision):
        try:
            with st.spinner("Assembling DOCX and PDF…"):
                package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
            st.session_state[prefix + "_package"] = package
            saved = library.save_snapshot(draft, expected_revision=st.session_state[revision_key],
                                           open_issues=prior.open_issues if prior else (), pending_proposals=prior.pending_proposals if prior else (),
                                           assets=tuple(assets.items()), entered_editor=prepared)
            st.session_state[revision_key] = saved.revision
            record_report_preparer(browser_token, contract, profile.key, prepared)
        except (ValueError, OSError) as exc:
            st.error(f"Report or snapshot could not be saved: {exc}")
    if package:
        st.download_button("Download DOCX", package.docx, file_name=package.docx_name, key=prefix + "_docx")
        if package.pdf:
            st.download_button("Download PDF", package.pdf, file_name=package.pdf_name, mime="application/pdf", key=prefix + "_pdf")
        if package.pdf_error:
            st.warning(package.pdf_error)
    _profile_manager(contract, state, field)
    with st.expander("Create another profile"):
        _profile_manager(contract, None, field)
