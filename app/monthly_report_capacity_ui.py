"""One capacity source task with explicit report and reusable-site scope."""

from dataclasses import asdict, replace
import hashlib

import pandas as pd
import streamlit as st

from app import monthly_report_capacity as capacity
from app import monthly_report_ai as ai, monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_ui_text import literal
from app.receipt_jobs import start_receipt


@st.fragment(run_every=1)
def _reading_progress(prefix):
    job = st.session_state.get(prefix + "_capacity_job")
    if job is not None and job["future"].done():
        st.rerun()
    if job is not None:
        st.info("Reading capacity tables from the uploaded file…")


def _cancel_reading(prefix):
    job = st.session_state.pop(prefix + "_capacity_job", None)
    if job is not None:
        job["future"].cancel()


def _context(draft, prefix):
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_testing import scope, generation
    return ai.digest((asdict(draft.profile), draft.period.key,
                      _rich_text_scope(prefix), scope(), generation()))


def _read_request(prefix, inspection, context):
    return {
        "context": context,
        "digest": st.session_state[prefix + "_capacity_digest"],
        "source": inspection.content.source.fingerprint,
        "revision": st.session_state[prefix + "_capacity_revision"],
    }


def _queue_read(prefix, request):
    # Capture the displayed file, report incarnation and shared base. Reusing
    # a prefix cannot turn a delayed native action into approval of a new file.
    st.session_state[prefix + "_capacity_read_request"] = dict(request)


def _finish(prefix, profile, context):
    job = st.session_state.get(prefix + "_capacity_job")
    if job is None:
        return
    inspection = st.session_state.get(prefix + "_capacity_inspection")
    if (job["context"] != context
            or job["digest"] != st.session_state.get(prefix + "_capacity_digest")
            or inspection is None
            or job["source"] != inspection.content.source.fingerprint):
        _cancel_reading(prefix)
        return
    if not job["future"].done():
        _reading_progress(prefix)
        return
    st.session_state.pop(prefix + "_capacity_job", None)
    try:
        result = job["future"].result()
        inspection = capacity.reader_result(profile, job["inspection"], result)
        # A failed reuse-cache write must not discard a completed, validated
        # reading or require another paid request to review the same result.
        st.session_state[prefix + "_capacity_inspection"] = inspection
        ai.save_cache(profile, "capacity", job["digest"], result)
    except Exception as exc:
        # Network errors leave the original file and existing data untouched.
        st.session_state[prefix + "_capacity_error"] = str(exc)


def _reload_conflict(prefix, profile):
    if st.session_state.get(prefix + "_capacity_conflict"):
        if st.button("Reload shared capacity for review", key=prefix + "_capacity_reload"):
            latest = capacity.load_capacity(profile.contract)
            st.session_state[prefix + "_capacity_revision"] = latest.revision if latest else 0
            st.session_state.pop(prefix + "_capacity_conflict", None)
            st.rerun()


def _has_values(block):
    return bool(block.text.strip() or block.asset_hashes or block.org_nodes or any(
        cell is not None and str(cell).strip()
        for rows in (block.rows, *(table.rows for table in block.extra_tables))
        for row in rows for cell in row))


def _columns(columns):
    names = []
    for i, column in enumerate(columns, 1):
        name = column or f"Column {i}"
        while name in names:
            name += f" ({i})"
        names.append(name)
    return names


def _capacity_file(prefix):
    from app.monthly_report_native_loading import reserve_empty_uploader
    reserve_empty_uploader(prefix + "_capacity_upload", "Thermal capacity file")
    return st.file_uploader(
        "Thermal capacity file",
        type=sorted(suffix.lstrip(".") for suffix in capacity.SUPPORTED),
        max_upload_size=128,
        key=prefix + "_capacity_upload",
        help="DOCX: up to 128 MB. Other supported files: up to 30 MB. "
             "Use capacity values for the relevant sites.",
    )


def _saved_capacity_caption(profile, state):
    """Describe only persisted rows matching this report's actual sites.

    This is a read-only inventory. It never promotes shared values into a
    manually edited or historical report, and never exposes another site's
    saved source filename through a contract-wide count.
    """
    if state is None:
        return "Reusable capacity · none saved for this contract"
    selected = capacity.capacity_block(profile, state)
    if selected is None:
        return "Reusable capacity · none saved for these sites"
    count = sum(len(table.rows) for table in selected.extra_tables)
    # A source reference identifies original table bytes, NOT a later saved
    # per-site subset. Two independently saved subsets may carry that same
    # reference with different filenames. Resolve the actual saved site rows
    # before exposing any source filename in this report's inventory.
    known = capacity.contract_facilities(profile)
    wanted = {facility.key for facility in profile.facilities}
    for facility in profile.facilities:
        for alias in (facility.title, *facility.aliases):
            matched = capacity.match_site(alias, known)
            if matched:
                wanted.add(matched)
    sources = tuple(dict.fromkeys(
        table.source_filename for table in state.tables
        if table.source_filename and any(site in wanted for site in table.site_keys)
    ))
    date = literal(str(state.updated_at).split("T", 1)[0])
    summary = (f"Reusable capacity · {count} saved row{'s' if count != 1 else ''} "
               f"for these sites · version {state.revision} · updated {date}")
    if sources:
        shown = ", ".join(literal(name[:80] + "…" if len(name) > 80 else name)
                          for name in sources[:2])
        summary += f" · source{'s' if len(sources) != 1 else ''}: {shown}"
        if len(sources) > 2:
            summary += f" (+{len(sources) - 2} more)"
    return summary


_LOAD_SHARED_CAPACITY = object()


def render_capacity_scope(profile, block, state=_LOAD_SHARED_CAPACITY):
    """Distinguish report values from the latest persisted site inventory.

    The production ordered-section flow renders the report grid before its
    shared source task and calls this scope renderer separately. An omitted
    state argument therefore means read the just-settled shared revision,
    not 'none saved'. The embedded flow passes its already-loaded state.
    """
    if state is _LOAD_SHARED_CAPACITY:
        state = capacity.load_capacity(profile.contract)
    if _has_values(block):
        reused = capacity.can_refresh_capacity(profile, block)
        st.caption("Capacity · reused for these sites" if reused else "Capacity · this report only")
        st.caption("Table edits apply to this report. Reusable-site corrections are below.")
    else:
        st.caption("Capacity · this report only")
        st.caption("Enter report-only values, or add a capacity source for reuse below.")
    st.caption(_saved_capacity_caption(profile, state))


def render_capacity(draft, block, prefix, field, *, show_scope=True):
    """Automatically persist safe first-fill rows, preserving historical pins.

    Ambiguous site matches, existing authoritative values and unreadable
    scanned-source cells still need specific review before being shared.
    """
    profile = draft.profile
    block = block or ResolvedBlock("thermal_capacity", "Library")
    context = _context(draft, prefix)
    if st.session_state.get(prefix + "_capacity_context") != context:
        _cancel_reading(prefix)
        for suffix in ("digest", "upload_identity", "inspection", "error", "saved", "conflict"):
            st.session_state.pop(prefix + "_capacity_" + suffix, None)
        st.session_state[prefix + "_capacity_context"] = context
    state = capacity.load_capacity(profile.contract)
    scope_slot = st.container() if show_scope else None
    # Keep the file action visible even when capacity rows already exist. A
    # previously saved grid must not hide the route for this month’s source.
    st.caption("Edit this report’s capacity values in the table above, or upload a thermal capacity file below. Existing reusable-site values change only after an explicit correction.")
    with st.expander("Capacity source and reusable data", expanded=True,
                     key=prefix + "_capacity_source_panel"):
        result = _render_capacity_source(draft, block, prefix, field, context, state)
    if scope_slot is not None:
        # A first fill or reviewed correction may have committed a newer
        # standing revision during this very render. Do not show "none saved"
        # for a save already acknowledged on the same action.
        revision = st.session_state.get(prefix + "_capacity_revision")
        if type(revision) is int and revision > (state.revision if state else 0):
            latest = capacity.load_capacity(profile.contract)
            if latest is not None and latest.revision == revision:
                state = latest
        with scope_slot:
            render_capacity_scope(profile, result[1], state)
    return result


def _render_capacity_source(draft, block, prefix, field, context, state):
    profile = draft.profile
    st.caption("Clear site matches fill missing reusable capacity automatically. "
               "Corrections affect future reports for the matched sites; report-only edits stay in this report.")
    # Keep the uploader at one native delta path when a first fill creates a
    # standing version. Only the contents of this reserved controls slot vary.
    changing_existing = False
    with st.container(key=prefix + "_capacity_shared_controls"):
        if state:
            changing_existing = st.toggle(
                "Correct existing reusable capacity",
                key=field(prefix + "_capacity_change", False),
                help="Applies reviewed source corrections to matched sites for future reports. "
                     "Previously saved report versions stay unchanged.",
            )
    uploaded = _capacity_file(prefix)
    if uploaded is None:
        _cancel_reading(prefix)
        for suffix in ("digest", "upload_identity", "inspection", "error", "read_request"):
            st.session_state.pop(prefix + "_capacity_" + suffix, None)
        return draft, block
    raw = uploaded.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    upload_identity = (uploaded.name, digest)
    if upload_identity != st.session_state.get(prefix + "_capacity_upload_identity"):
        _cancel_reading(prefix)
        st.session_state[prefix + "_capacity_digest"] = digest
        st.session_state[prefix + "_capacity_upload_identity"] = upload_identity
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
        except (ValueError, OSError, RuntimeError) as exc:
            st.session_state[prefix + "_capacity_error"] = str(exc)
    _finish(prefix, profile, context)
    inspection = st.session_state.get(prefix + "_capacity_inspection")
    needs_reading = inspection is not None and (not inspection.tables or inspection.pending_pages)
    request = _read_request(prefix, inspection, context) if needs_reading else None
    submitted = st.session_state.pop(prefix + "_capacity_read_request", None)
    if submitted is not None:
        if submitted != request:
            st.warning("The capacity file or report changed before reading started. Nothing was sent. Review the current file and select Read capacity file.")
        elif submitted["revision"] != (state.revision if state else 0):
            st.warning("Shared capacity changed before reading started. Nothing was sent. Reload it for review; your uploaded file is kept.")
            st.session_state[prefix + "_capacity_conflict"] = True
        elif prefix + "_capacity_job" not in st.session_state:
            try:
                from app.monthly_report_testing import scope
                if scope() is not None:
                    raise ValueError("External reading is off in isolated testing. Use native file review or enter the synthetic values below.")
                def prepare():
                    payload = capacity.reader_request(profile, inspection)
                    ai.reserve_call(profile, draft.period)
                    return payload
                future = start_receipt(prepare, ai.request_json)
                if future is None:
                    raise ValueError("Two document readings are already running. Your file is kept; try Read capacity file again when one finishes.")
                st.session_state.pop(prefix + "_capacity_error", None)
                st.session_state[prefix + "_capacity_job"] = dict(request, inspection=inspection, future=future)
                _finish(prefix, profile, context)
            except (ValueError, OSError, RuntimeError) as exc:
                st.session_state[prefix + "_capacity_error"] = str(exc)
    if prefix + "_capacity_error" in st.session_state:
        st.warning(st.session_state[prefix + "_capacity_error"])
        if inspection is None and st.button("Try opening capacity file again", key=prefix + "_capacity_retry"):
            st.session_state.pop(prefix + "_capacity_upload_identity", None)
            st.rerun()
    inspection = st.session_state.get(prefix + "_capacity_inspection")
    if inspection is None or prefix + "_capacity_job" in st.session_state:
        return draft, block
    if not inspection.tables or inspection.pending_pages:
        from app.monthly_report_testing import scope
        st.info("Some capacity pages need reading. Your existing report and saved capacity have been kept. You can also enter values in this report's table below.")
        if scope() is None:
            st.caption("Reading sends the capacity pages to the external document reader and uses this report's reading allowance. Charges may apply.")
            request = _read_request(prefix, inspection, context)
            st.button("Read capacity file", key=prefix + "_capacity_read_" + ai.digest(request),
                      on_click=_queue_read, args=(prefix, request))
        else:
            st.caption("External reading is off in isolated testing. Use native file review or enter the synthetic values below.")
        _reload_conflict(prefix, profile)
        return draft, block
    facilities = capacity.contract_facilities(profile)
    names = {f.key: f.title for f in facilities}
    titles = {f.title: f.key for f in facilities}
    reviewed = []
    st.caption("Leave unknown capacity values blank or NR; never treat them as zero.")
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
        st.caption("Reusable capacity is up to date for the matched sites.")
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
            # Only the newly added rows were accepted. A mixed file may
            # still contain a correction to an existing service; keep its
            # explicit correction action reachable without another upload.
            st.session_state[prefix + "_capacity_saved"] = capacity.review_fingerprint(first_fill)
            updated = capacity.capacity_block(profile, saved)
            if updated and capacity.can_refresh_capacity(profile, block):
                content = tuple(updated if b.key == "thermal_capacity" else b for b in draft.blocks)
                if not any(b.key == "thermal_capacity" for b in content):
                    content += (updated,)
                draft, block = replace(draft, blocks=content), updated
            st.success("New site capacity is kept for the contract and will appear in future reports.")
            if state and sum(len(t.rows) for t in first_fill) < sum(len(t.rows) for t in tables):
                st.info("Existing capacity values were not replaced. Use Correct existing reusable capacity "
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
                   "turn on Correct existing reusable capacity above.")
        _reload_conflict(prefix, profile)
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
    # Bind approval to the displayed source/result/base, while accepting cell
    # corrections delivered with this same native click. Hashing the edited
    # grid here would change its action ID and silently discard that click.
    approval = ai.digest((_read_request(prefix, inspection, context),
                          tuple(asdict(table) for table in inspection.tables)))
    if st.button(f"Apply reviewed capacity for {site_count} site{'s' if site_count != 1 else ''}",
                 key=prefix + "_capacity_save_" + approval, type="primary",
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
    _reload_conflict(prefix, profile)
    return draft, block
