"""One upload and one reviewed contract-wide capacity save."""

from dataclasses import replace
import hashlib

import pandas as pd
import streamlit as st

from app import monthly_report_capacity as capacity
from app import monthly_report_ai as ai, monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from app.receipt_jobs import start_receipt


@st.fragment(run_every=1)
def _reading_progress(prefix):
    job = st.session_state.get(prefix + "_capacity_job")
    if job is not None and job["future"].done():
        st.rerun()
    if job is not None:
        st.info("Reading capacity tables from the uploaded file…")


def _finish(prefix, profile):
    job = st.session_state.get(prefix + "_capacity_job")
    if job is None:
        return
    if not job["future"].done():
        _reading_progress(prefix)
        return
    st.session_state.pop(prefix + "_capacity_job", None)
    try:
        result = job["future"].result()
        inspection = capacity.reader_result(profile, job["inspection"], result)
        ai.save_cache(profile, "capacity", job["digest"], result)
        if st.session_state.get(prefix + "_capacity_digest") == job["digest"]:
            st.session_state[prefix + "_capacity_inspection"] = inspection
    except Exception as exc:
        # Network errors leave the original file and existing data untouched.
        st.session_state[prefix + "_capacity_error"] = str(exc)


def _columns(columns):
    names = []
    for i, column in enumerate(columns, 1):
        name = column or f"Column {i}"
        while name in names:
            name += f" ({i})"
        names.append(name)
    return names


def render_capacity(draft, block, prefix, field):
    """Automatically persist safe first-fill rows, preserving historical pins.

    Ambiguous site matches, existing authoritative values and unreadable
    scanned-source cells still need specific review before being shared.
    """
    profile = draft.profile
    block = block or ResolvedBlock("thermal_capacity", "Library")
    state = capacity.load_capacity(profile.contract)
    changing_existing = False
    if state:
        sites = {key for table in state.tables for key in table.site_keys}
        st.caption(f"Capacity data is saved for {len(sites)} site{'s' if len(sites) != 1 else ''} on this contract. New reports reuse their site's tables.")
        changing_existing = st.toggle("Update existing capacity values", key=field(prefix + "_capacity_change", False))
    else:
        st.caption("Upload capacity information once for the contract. Tables for other sites will be ready when their reports are started.")
    uploaded = st.file_uploader(
        "Thermal capacity file",
        type=sorted(suffix.lstrip(".") for suffix in capacity.SUPPORTED),
        key=prefix + "_capacity_upload",
        help="Use a PDF, Word document, spreadsheet or image. Include every site's chilled water and steam information in the same file if available.",
    )
    _finish(prefix, profile)
    if uploaded is None:
        return draft, block
    raw = uploaded.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != st.session_state.get(prefix + "_capacity_digest"):
        previous_job = st.session_state.pop(prefix + "_capacity_job", None)
        if previous_job:
            previous_job["future"].cancel()
        st.session_state[prefix + "_capacity_digest"] = digest
        st.session_state[prefix + "_capacity_revision"] = state.revision if state else 0
        st.session_state.pop(prefix + "_capacity_inspection", None)
        st.session_state.pop(prefix + "_capacity_error", None)
        st.session_state.pop(prefix + "_capacity_saved", None)
        try:
            inspection = capacity.inspect_capacity(profile, uploaded.name, raw)
            st.session_state[prefix + "_capacity_inspection"] = inspection
            if not inspection.tables or inspection.pending_pages:
                cached = ai.cached(profile, "capacity", digest)
                if cached is not None:
                    st.session_state[prefix + "_capacity_inspection"] = capacity.reader_result(profile, inspection, cached)
                elif prefix + "_capacity_job" not in st.session_state:
                    def prepare():
                        payload = capacity.reader_request(profile, inspection)
                        ai.reserve_call(profile, draft.period)
                        return payload
                    future = start_receipt(prepare, ai.request_json)
                    if future is None:
                        st.session_state[prefix + "_capacity_error"] = "Two document readings are already running. Try reading this file again when one finishes."
                    else:
                        st.session_state[prefix + "_capacity_job"] = {"digest": digest, "inspection": inspection, "future": future}
                        _reading_progress(prefix)
        except (ValueError, OSError, RuntimeError) as exc:
            st.session_state[prefix + "_capacity_error"] = str(exc)
    if prefix + "_capacity_error" in st.session_state:
        st.warning(st.session_state[prefix + "_capacity_error"])
        if st.button("Read capacity file again", key=prefix + "_capacity_retry"):
            st.session_state.pop(prefix + "_capacity_digest", None)
            st.rerun()
    inspection = st.session_state.get(prefix + "_capacity_inspection")
    if inspection is None or prefix + "_capacity_job" in st.session_state:
        return draft, block
    if inspection.pending_pages:
        st.info("Some capacity pages still need reading. Finish reading them before saving the contract tables.")
        return draft, block
    if not inspection.tables:
        st.info("No capacity table was found. Upload a clearer copy or enter the information in this report's table below.")
        return draft, block
    facilities = capacity.contract_facilities(profile)
    names = {f.key: f.title for f in facilities}
    titles = {f.title: f.key for f in facilities}
    reviewed = []
    st.write("Capacity rows with clear site matches are kept for future reports automatically. "
             "Only uncertain or conflicting information needs your decision.")
    if inspection.used_reader:
        st.caption("Check every value and unit against the file. Unreadable cells must be corrected before saving.")
    for notice in inspection.notices:
        st.caption(notice)
    with st.expander("View original capacity file", expanded=False):
        source = inspection.content.source
        if source.suffix in capacity.SUPPORTED - {".csv", ".xlsx", ".txt", ".docx"} or inspection.content.image_items:
            from app.monthly_report_sources import page_image, image_numbers
            pages = image_numbers(inspection.content)
            page = pages[0] if len(pages) == 1 else st.selectbox("Original capacity page", pages, key=prefix + "_capacity_source_page_" + digest)
            if page:
                original_image = page_image(profile, inspection.content, page)
                st.image(original_image.data, width="stretch")
        else:
            st.text("\n\n".join(source.page_texts))
    for table in inspection.tables:
        st.markdown("**" + table.title + "**")
        editor_key = prefix + "_capacity_table_" + table.id
        edited = st.data_editor(
            pd.DataFrame(table.rows, columns=_columns(table.columns)),
            key=editor_key, hide_index=True, width="stretch", num_rows="fixed",
        )
        rows = tuple(tuple("" if pd.isna(value) else str(value) for value in row) for row in edited.itertuples(index=False, name=None))
        mappings = []
        for index, (row, key) in enumerate(zip(rows, table.site_keys)):
            if table.site_column >= 0:
                key = capacity.match_site(row[table.site_column], facilities)
            if key:
                mappings.append(key)
            else:
                label = row[table.site_column] if table.site_column >= 0 else table.title
                options = ["Choose a site", *titles, "Leave this row out"]
                selected = st.selectbox(
                    f"Site for {label or 'row ' + str(index + 1)}", options,
                    key=field(editor_key + "_site_" + str(index), "Choose a site"),
                )
                mappings.append(titles.get(selected, "__leave_out__" if selected == "Leave this row out" else ""))
        pairs = [(row, key) for row, key in zip(rows, mappings) if key != "__leave_out__"]
        if pairs:
            reviewed.append(replace(table, rows=tuple(r for r, _ in pairs), site_keys=tuple(k for _, k in pairs)))
        assigned = sorted({names[k] for k in mappings if k in names})
        if assigned:
            st.caption("Sites: " + ", ".join(assigned))
    tables = tuple(reviewed)
    fingerprint = capacity.review_fingerprint(tables)
    if st.session_state.get(prefix + "_capacity_saved") == fingerprint:
        st.success("Capacity is kept for the contract. New reports reuse the matched sites' values.")
        return draft, block
    unresolved = any(not key for table in tables for key in table.site_keys)
    actor = draft.prepared_by.strip()
    unverified_image = inspection.used_reader and any(
        table.page in inspection.content.source.needs_vision for table in tables)
    first_fill = capacity.first_fill_tables(state, tables)
    if first_fill and not unresolved and actor and not unverified_image:
        # The same reviewed values pass the existing atomic version/provenance
        # validator, without a routine "Save to contract" decision.
        try:
            saved = capacity.save_capacity(profile, first_fill,
                expected_revision=st.session_state[prefix + "_capacity_revision"],
                actor=actor, reviewed_fingerprint=capacity.review_fingerprint(first_fill),
                mode="merge")
            st.session_state[prefix + "_capacity_revision"] = saved.revision
            st.session_state[prefix + "_capacity_saved"] = fingerprint
            updated = capacity.capacity_block(profile, saved)
            if updated and capacity.can_refresh_capacity(profile, block):
                content = tuple(updated if b.key == "thermal_capacity" else b for b in draft.blocks)
                if not any(b.key == "thermal_capacity" for b in content):
                    content += (updated,)
                draft, block = replace(draft, blocks=content), updated
            st.success("New site capacity is kept for the contract and will appear in future reports.")
            if state and len(first_fill) < len(tables):
                st.info("Existing site values were not replaced. Use Update existing capacity values "
                        "only when a reviewed correction is needed.")
            return draft, block
        except library.RevisionConflict:
            st.warning("Someone changed shared capacity data. Reload it and review the affected sites; "
                       "the uploaded values are still on this page.")
            st.session_state[prefix + "_capacity_conflict"] = True
        except (ValueError, OSError):
            st.warning("The capacity data could not be kept for future reports. "
                       "Your uploaded values remain here. Correct any uncertain cells or try again.")
    if state and not changing_existing and not first_fill:
        st.caption("Those sites already have saved capacity. To change existing values, "
                   "open Update existing capacity values above.")
        return draft, block
    mode = "merge"
    conflicts = capacity.schema_conflicts(state, tables)
    if conflicts:
        choice = st.selectbox(
            "These tables use different columns from the saved capacity data",
            ["Choose how to update", "Replace capacity tables for these sites", "Keep both sets of tables"],
            key=field(prefix + "_capacity_schema_" + fingerprint, "Choose how to update"),
        )
        mode = {"Replace capacity tables for these sites": "replace_sites", "Keep both sets of tables": "keep_both"}.get(choice, "")
    if not actor:
        st.info("Enter your name before saving capacity for the contract.")
    site_count = len({key for table in tables for key in table.site_keys if key})
    if st.button(f"Apply reviewed capacity for {site_count} site{'s' if site_count != 1 else ''}",
                 key=prefix + "_capacity_save", type="primary",
                 disabled=not tables or unresolved or not actor or not mode):
        try:
            saved = capacity.save_capacity(
                profile, tables, expected_revision=st.session_state[prefix + "_capacity_revision"],
                actor=actor, reviewed_fingerprint=fingerprint, mode=mode,
            )
            st.session_state[prefix + "_capacity_revision"] = saved.revision
            st.session_state[prefix + "_capacity_saved"] = fingerprint
            updated = capacity.capacity_block(profile, saved)
            if updated and capacity.can_refresh_capacity(profile, block):
                blocks = tuple(updated if b.key == "thermal_capacity" else b for b in draft.blocks)
                if not any(b.key == "thermal_capacity" for b in blocks):
                    blocks += (updated,)
                draft, block = replace(draft, blocks=blocks), updated
            elif updated:
                st.info("The contract data is saved. Your existing report's edited capacity content has been kept.")
            st.success(f"Capacity saved for {site_count} sites. Other sites can now reuse their tables.")
        except library.RevisionConflict as exc:
            st.warning(str(exc))
            st.session_state[prefix + "_capacity_conflict"] = True
        except (ValueError, OSError) as exc:
            st.warning(str(exc))
    if st.session_state.get(prefix + "_capacity_conflict"):
        if st.button("Reload shared capacity for review", key=prefix + "_capacity_reload"):
            latest = capacity.load_capacity(profile.contract)
            st.session_state[prefix + "_capacity_revision"] = latest.revision if latest else 0
            st.session_state.pop(prefix + "_capacity_conflict", None)
            st.rerun()
    return draft, block
