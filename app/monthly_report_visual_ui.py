"""Direct person/contact/photo fields with matching report-image previews."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_asset_review import pending_asset_indexes, preserve_asset_reviews
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_editor import _signature
from app.monthly_report_model import OrgChartNode, ReportTable
from app.monthly_report_visuals import contact_positions, validate_org, org_groups, org_page, photo_count, photo_page


def _install(draft, prefix, block, *, spec=None, clear=""):
    blocks = {b.key: b for b in draft.blocks}
    blocks[block.key] = preserve_asset_reviews(blocks[block.key], block) if block.key in blocks else block
    sections = tuple(
        replace(
            s, blocks=tuple(spec if spec and b.key == spec.key else b for b in s.blocks)
        )
        for s in draft.sections
    )
    if clear:
        st.session_state["report_draft_mirror"] = {
            k: v
            for k, v in st.session_state.get("report_draft_mirror", {}).items()
            if not k.startswith(clear)
        }
        for key in list(st.session_state):
            if key.startswith(clear):
                del st.session_state[key]
    st.session_state[prefix + "_draft"] = replace(
        draft, blocks=tuple(blocks.values()), sections=sections
    )
    st.rerun()


def _page_number(label, count, prefix, field):
    if count <= 1:
        return 0
    return (
        int(
            st.number_input(
                label,
                min_value=1,
                max_value=count,
                key=field(prefix + "_page_" + str(count), 1),
            )
        )
        - 1
    )


def edit_org_chart(draft, block, prefix, assets, field, *, show_preview=True):
    p = prefix + "_org"
    st.caption("Team chart for these report sites. Saved report versions keep it for future months.")
    if not block.org_nodes:
        if block.asset_hashes:
            st.caption(
                "Your uploaded chart is retained. You can keep it, upload a replacement, or build an editable chart below."
            )
        with st.expander(
            "Build a chart with editable names and reporting lines",
            expanded=not block.asset_hashes,
        ):
            st.write(
                "Add positions and choose their reporting lines. Existing image charts remain in saved history."
            )
            candidates = contact_positions(draft)
            nodes = (OrgChartNode("position-1", role="Asset manager"),)
            if candidates:
                method = st.radio(
                    "Start the chart with",
                    ["People already in this report’s contacts", "An empty chart"],
                    key=field(p + "_method", "People already in this report’s contacts"),
                )
                if method == "People already in this report’s contacts":
                    choices = {n.key: n for n in candidates}
                    signature = _signature(candidates)
                    selected = st.multiselect(
                        "People to include in the org chart",
                        list(choices),
                        format_func=lambda key: " · ".join(v for v in (choices[key].name, choices[key].role, choices[key].team) if v),
                        key=field(p + "_people_" + signature, list(choices) if len(choices) <= 60 else []),
                        max_selections=60,
                    )
                    nodes = tuple(choices[key] for key in selected)
                    st.caption("Choose up to 60 people or positions. Next, choose who each person reports to. Phone numbers and email fields are not copied into the chart.")
            else:
                st.caption("To reuse people already saved for these sites, add or update this report’s contacts first. You can also start with an empty chart.")
            problem = ""
            try:
                validate_org(nodes)
            except ValueError as exc:
                problem = str(exc)
                st.info(problem + " You can change the contact fields or start with an empty chart.")
            confirm = not block.asset_hashes or st.checkbox(
                "Replace this report’s uploaded chart with the editable chart",
                key=p + "_replace_ok",
            )
            if st.button(
                "Start an editable org chart", key=p + "_start", disabled=not confirm or bool(problem)
            ):
                new = replace(
                    block,
                    source="Replace once",
                    org_nodes=nodes,
                    asset_hashes=(),
                    asset_captions=(),
                    references=(),
                    text="",
                    rows=(),
                    extra_tables=(),
                    client_reviewed_fingerprint="",
                )
                _install(draft, prefix, new, clear=p + "_person_")
        return block
    left, right = st.columns([1, 1]) if show_preview else (st.container(), None)
    nodes = []
    with left:
        for node in block.org_nodes:
            key = p + "_person_" + node.key
            with st.expander(
                node.name or node.role or "New position",
                # Existing people start as summaries, even in a small chart.
                # A newly added blank position opens so its required fields
                # remain immediately discoverable and keyboard accessible.
                expanded=not (node.name or node.role),
            ):
                name = st.text_input(
                    "Name", key=field(key + "_name", node.name), max_chars=100
                )
                role = st.text_input(
                    "Role / position",
                    key=field(key + "_role", node.role),
                    max_chars=100,
                )
                team = st.text_input(
                    "Site or team (optional)",
                    key=field(key + "_team", node.team),
                    max_chars=100,
                )
                choices = ["", *[n.key for n in block.org_nodes if n.key != node.key]]
                labels = {
                    n.key: " · ".join(v for v in (n.name, n.role) if v)
                    or "New position"
                    for n in block.org_nodes
                }
                parent = st.selectbox(
                    "Reports to",
                    choices,
                    format_func=lambda k: labels.get(k, "No manager in this chart"),
                    key=field(
                        key + "_manager",
                        node.reports_to if node.reports_to in choices else "",
                    ),
                )
                nodes.append(
                    replace(node, name=name, role=role, team=team, reports_to=parent)
                )
                if st.button("Remove position", key=key + "_remove_button"):
                    kept = tuple(
                        replace(n, reports_to="") if n.reports_to == node.key else n
                        for n in (*nodes[:-1], *block.org_nodes[len(nodes) :])
                    )
                    _install(
                        draft,
                        prefix,
                        replace(block, org_nodes=kept),
                        clear=p + "_person_",
                    )
        block = replace(block, source="This month", org_nodes=tuple(nodes))
        if st.button(
            "Add position", key=p + "_add", disabled=len(nodes) >= 60
        ):
            number = 1
            while f"position-{number}" in {n.key for n in nodes}:
                number += 1
            _install(
                draft,
                prefix,
                replace(block, org_nodes=(*nodes, OrgChartNode(f"position-{number}"))),
                clear=p + "_person_",
            )
    if show_preview:
        with right:
            st.write("Org chart preview")
            try:
                count = len(org_groups(block.org_nodes))
                page = _page_number("Chart page", count, p, field)
                st.image(org_page(block.org_nodes, page), width="stretch")
                if count > 1:
                    st.caption(
                        f"{count} pages keep larger teams readable. Reporting lines are exactly the ones you selected."
                    )
            except ValueError as exc:
                st.info(str(exc))
    return block


def _contact_label(columns, row, index):
    """Identify people by name, role and site before opening an editor."""
    fields = tuple((str(heading).strip().casefold(), str(value).strip())
                   for heading, value in zip(columns, row))
    def pick(identifiers):
        return next((value for name, value in fields
                     if name in identifiers and value), "")
    person = pick({"name", "contact name", "contact", "person", "employee"})
    role = pick({"role", "title", "position", "job title", "discipline"})
    site = pick({"site", "facility", "building", "location", "hospital"})
    if not person:
        person = pick({"vendor", "contractor", "company", "supplier"})
    return " · ".join(dict.fromkeys(v for v in (person, role, site) if v)) or f"Contact {index + 1}"


def _contact_rows(columns, rows, p, field, *, vendor=False):
    edited = []
    remove_index = None
    for index, row in enumerate(rows):
        title = _contact_label(columns, row, index)
        # Existing vendor records are already identifiable by their compact
        # name/discipline/site summary. Do not expand a full six-field form
        # merely because a table contains one or two saved contacts.
        # A newly created blank vendor entry opens for immediate input.
        populated = any(str(value).strip() for value in row)
        with st.expander(title, expanded=(not populated if vendor else len(rows) <= 2)):
            values = []
            for col, heading in enumerate(columns):
                value = row[col] if col < len(row) else ""
                agreement = vendor and heading.strip().casefold() == "msa"
                values.append(
                    st.text_input(
                        "Agreement status (MSA)" if agreement else (heading or "Detail " + str(col + 1)),
                        key=field(p + f"_{index}_{col}", value),
                        help=("Master Service Agreement status. Leave blank when unknown."
                              if agreement else None),
                        max_chars=500,
                    )
                )
            if st.button("Remove contact", key=p + f"_{index}_remove"):
                remove_index = index
            edited.append(tuple(values))
    return tuple(edited), remove_index


def _contact_widget_prefix(prefix, block_key):
    """Mount report fields under the current report incarnation, not an old one.

    Source import and QA reset can replace a report while keeping the same
    contract, site and month. Reusing the old native text_input IDs lets a
    delayed browser widget echo an earlier contact into the new immutable
    draft during an unrelated Generate rerun. Reuse the established, stable
    per-incarnation scope already used by Activity; ordinary edits and preview
    fragments retain their IDs, while import/reset changes them.
    """
    from app.monthly_report_guided import _rich_text_scope
    return prefix + "_contacts_" + block_key + "_" + _rich_text_scope(prefix)


def _contact_table_block(block, tables, has_primary):
    return replace(block, rows=tables[0].rows if has_primary else (),
                   extra_tables=tuple(tables[1:] if has_primary else tables))


def _contact_block_tables(block, spec, has_primary):
    return ((ReportTable(tuple(column.title for column in spec.columns), block.rows),)
            if has_primary else ()) + tuple(block.extra_tables)


def _contact_pending_marker(draft):
    return "directory-pending-correction:" + draft.profile.key


def _readback_contact_correction(draft, before, after):
    """Recognize an already committed full correction without another write."""
    from collections import Counter
    from app import monthly_report_directory as directory
    import re
    intent = f"directory-add-intent:{draft.profile.key}"
    refs = tuple(ref for ref in before.references if ref != intent)
    versions = [re.fullmatch(r"directory:([^:]+):([1-9][0-9]*)", ref) for ref in refs]
    versions = [value for value in versions if value]
    bindings = dict(ref.removeprefix("directory-site:").split(":", 1)
                    for ref in refs if ref.startswith("directory-site:") and ref.count(":") == 2)
    if len(versions) != 1 or len(bindings) != len(draft.profile.facilities) or before.extra_tables or after.extra_tables:
        return None
    historical = directory.load_directory(draft.profile.contract, int(versions[0][2]))
    latest = directory.load_directory(draft.profile.contract)
    if historical is None or latest is None or latest.archived:
        return None
    original, missing = directory.contact_block(historical, draft.profile.facilities, bindings)
    current, current_missing = directory.contact_block(latest, draft.profile.facilities, bindings)
    # Full historical identity and complete row multiset, not names, prove the
    # intended correction. Directory grouping may relocate appended contacts.
    if (missing or current_missing or original.references != refs
            or (before.rows[:len(original.rows)] != original.rows if intent in before.references else before.rows != original.rows)
            or Counter(current.rows) != Counter(after.rows)):
        return None
    return replace(after, source="Library", rows=current.rows, references=current.references,
                   reviewed_fingerprint="", client_reviewed_fingerprint="")


def _contact_add_ready(draft, before, after, prefix):
    """Incomplete explicit additions remain editable, not failed shared writes."""
    from app import monthly_report_directory as directory
    import re
    intent = f"directory-add-intent:{draft.profile.key}"
    if intent not in before.references and intent not in after.references:
        return True
    refs = tuple(ref for ref in before.references if ref != intent)
    key = prefix + "_add_baseline"
    receipt = st.session_state.get(key)
    if before.source == "Library" and intent not in before.references:
        receipt = (refs, len(before.rows))
        st.session_state[key] = receipt
    if receipt is None or receipt[0] != refs:
        # A reloaded unfinished Add has no UI receipt. Read only its immutable
        # historical baseline; unavailable storage defers promotion, not input.
        version = next((match for ref in refs if (match := re.fullmatch(r"directory:([^:]+):([1-9][0-9]*)", ref))), None)
        bindings = dict(ref.removeprefix("directory-site:").split(":", 1)
                        for ref in refs if ref.startswith("directory-site:") and ref.count(":") == 2)
        try:
            saved = directory.load_directory(draft.profile.contract, int(version[2])) if version else None
            original, missing = directory.contact_block(saved, draft.profile.facilities, bindings) if saved else (None, True)
            if original is None or missing or original.references != refs:
                return False
            receipt = (refs, len(original.rows))
            st.session_state[key] = receipt
        except (ValueError, OSError):
            return None
    titles = {facility.title for facility in draft.profile.facilities}
    return all(len(row) == 5 and row[0] in titles and row[1].strip() and row[2].strip()
               for row in after.rows[receipt[1]:])


def _keep_contact_correction(draft, before, after, prefix):
    from app import monthly_report_directory as directory
    intent = f"directory-add-intent:{draft.profile.key}"
    if (before.key != "contact_matrix" or before.rows == after.rows or before.extra_tables
            or after.extra_tables or len(after.rows) < len(before.rows)
            or before.source != "Library" and intent not in before.references and intent not in after.references):
        return None, False
    try:
        shared = directory.automatically_keep_directory_contact_edits(
            draft.profile, before, after, draft.prepared_by)
        return shared, False
    except (ValueError, OSError):
        try:
            shared = _readback_contact_correction(draft, before, after)
        except (ValueError, OSError):
            shared = None
        if shared is not None:
            st.info("The contact correction is verified in the shared directory. The removal was not applied; review the contact before removing it.")
            return shared, True
        return _pending_contact_correction(draft, before, after, prefix), True


def _pending_contact_correction(draft, before, after, prefix):
    marker = _contact_pending_marker(draft)
    pending = replace(after, references=tuple(dict.fromkeys((*after.references, marker))),
                      reviewed_fingerprint="", client_reviewed_fingerprint="")
    st.session_state[prefix + "_standing_recovery"] = {"before": before, "after": after}
    st.warning("The shared contact correction is pending. Your fields are retained and the contact was not removed. Retry or explicitly keep this correction report-only.")
    return pending


def _queue_contact_recovery(prefix, expected, action):
    st.session_state[prefix + "_standing_action"] = (expected, action)


def _recover_contact_correction(draft, block, prefix):
    """Pending intent survives report reload; retry is always an explicit action."""
    from app import monthly_report_directory as directory
    marker = _contact_pending_marker(draft)
    action = st.session_state.pop(prefix + "_standing_action", None)
    if action is not None and action[0] != block:
        st.warning("Contacts changed after this recovery choice was shown. Review the current correction before choosing again.")
        action = None
    if marker not in block.references:
        return block, False
    after = replace(block, references=tuple(ref for ref in block.references if ref != marker))
    key = prefix + "_standing_recovery"
    receipt = st.session_state.get(key)
    if receipt is None or receipt['after'].rows != after.rows or receipt['after'].references != after.references:
        # Restore the exact immutable baseline from its retained directory version.
        import re
        version = next((re.fullmatch(r"directory:([^:]+):([1-9][0-9]*)", ref)
                        for ref in after.references if re.fullmatch(r"directory:([^:]+):([1-9][0-9]*)", ref)), None)
        bindings = dict(ref.removeprefix("directory-site:").split(":", 1)
                        for ref in after.references if ref.startswith("directory-site:") and ref.count(":") == 2)
        try:
            saved = directory.load_directory(draft.profile.contract, int(version[2])) if version else None
            original, missing = directory.contact_block(saved, draft.profile.facilities, bindings) if saved else (None, True)
            if original is not None and not missing:
                before = replace(after, source="Library", rows=original.rows)
                receipt = {"before": before, "after": after}
                st.session_state[key] = receipt
        except (ValueError, OSError):
            receipt = None
    if receipt is not None:
        try:
            shared = _readback_contact_correction(draft, receipt['before'], after)
        except (ValueError, OSError):
            shared = None
        if shared is not None:
            st.session_state.pop(key, None)
            return shared, False
    st.warning("This shared contact correction is still pending; no automatic retry or removal has been performed.")
    st.button("Retry shared contact correction", key=prefix + "_retry_standing", disabled=receipt is None,
              on_click=_queue_contact_recovery, args=(prefix, block, "retry"))
    st.button("Keep correction in this report only", key=prefix + "_report_only_standing",
              on_click=_queue_contact_recovery, args=(prefix, block, "report_only"))
    if action is not None and action[1] == "retry" and receipt is not None:
        readiness = _contact_add_ready(draft, receipt['before'], after, prefix)
        if readiness is False:
            st.session_state.pop(key, None)
            st.info("Finish the new contact's site, role and name before it can be kept for future reports. Your Add intent is retained.")
            return after, False
        if readiness is None:
            st.warning("The saved contact baseline is still unavailable. No shared write was attempted; your correction remains pending.")
            return block, True
        shared, failed = _keep_contact_correction(draft, receipt['before'], after, prefix)
        if shared is not None and (not failed or shared.source == "Library"):
            st.session_state.pop(key, None)
            return shared, False
        if shared is not None:
            return shared, True
        st.warning("The correction could not be applied to the current directory. It remains pending for comparison.")
    if action is not None and action[1] == "report_only":
        st.session_state.pop(key, None)
        intent = f"directory-add-intent:{draft.profile.key}"
        return replace(after, references=tuple(ref for ref in after.references if ref != intent)), False
    return block, True


def edit_contacts(draft, spec, block, prefix, assets, field, *, show_preview=True, standing_source=None):
    if not draft.prepared_by.strip():
        st.info("Enter your name above to view or edit saved contacts.")
        return block
    block = preserve_asset_reviews(block, block)
    p = _contact_widget_prefix(prefix, block.key)
    st.session_state.pop(p + "_compact_editor_key", None)
    recovered, pending = _recover_contact_correction(draft, block, p)
    if pending:
        return recovered
    block = recovered
    tables = list(block.extra_tables)
    # Output headings do not make an image-capable block an editable table.
    # Preserve its explicit image replacement/conversion path until rows exist;
    # true table blocks still expose an initially empty editable table.
    has_primary = bool(block.rows or (spec.type == "table" and spec.columns and not tables))
    if has_primary:
        tables.insert(0, ReportTable(tuple(c.title for c in spec.columns), block.rows))
    if tables and block.asset_hashes:
        # A vendor matrix may be a preserved page, native rows, or both.
        # Having editable columns must not hide the pages that will be printed.
        from app.monthly_report_saved_pictures_ui import edit_saved_pictures

        label = "View or change saved vendor pages" if block.key == "subcontractor_matrix" else "View or change saved contact pages"
        with st.expander(label):
            block = edit_saved_pictures(
                block,
                p + "_pages",
                lambda ref: assets.get(ref)
                or library.read_asset(draft.profile.contract, draft.profile.key, ref),
                show_preview=show_preview,
            )
    if not tables:
        with st.expander("View or change saved contact pages", expanded=not block.asset_hashes):
            if block.asset_hashes:
                from app.monthly_report_saved_pictures_ui import edit_saved_pictures

                block = edit_saved_pictures(
                    block,
                    p + "_pages",
                    lambda ref: assets.get(ref)
                    or library.read_asset(draft.profile.contract, draft.profile.key, ref),
                    show_preview=show_preview,
                )
            upload = st.file_uploader(
                "Replacement facility contact page",
                type=["png", "jpg", "jpeg", "heic", "heif", "webp"],
                max_upload_size=30,
                key=p + "_page_upload",
            )
            st.caption("A replacement changes all contact-page pictures in this report. The org chart and outage procedures stay as they are.")
            if st.button("Use this contact page", key=p + "_page_replace", disabled=upload is None):
                try:
                    image = normalize_report_image(upload.getvalue(), Path(upload.name).suffix, line_art=True)
                    reference = library.asset_reference(image.data, image.extension)
                    assets[reference] = image.data
                    new = replace(
                        block,
                        source="Replace once",
                        asset_hashes=(reference,),
                        asset_provenance=((reference, ()),),
                        asset_captions=(),
                        references=(),
                        reviewed_fingerprint="",
                        client_reviewed_fingerprint="",
                    )
                    _install(draft, prefix, new)
                except (ValueError, OSError):
                    st.error("This contact page could not be read. Choose another image; your current pages are retained.")
        st.caption(
            "Create editable contact fields, or keep the uploaded contact page. Saved originals remain available in history."
        )
        ok = not block.asset_hashes or st.checkbox(
            "Replace this contact page with editable fields", key=p + "_replace"
        )
        if st.button("Create editable contacts", key=p + "_create", disabled=not ok):
            from app.monthly_report_directory import CONTACT_SPEC

            columns = tuple(c.title for c in CONTACT_SPEC.columns)
            new = replace(
                block,
                source="This month",
                asset_hashes=(),
                asset_captions=(),
                references=(),
                text="",
                rows=(),
                extra_tables=(ReportTable(columns, ()),),
            )
            card_key = p + "_compact_" + _signature((tuple(table.columns for table in new.extra_tables), new.references))
            st.session_state[card_key] = {"tables": new.extra_tables, "active": (0, 0)}
            _install(draft, prefix, new, clear=p + "_table_")
        return block
    left, right = st.columns([1, 1]) if show_preview else (st.container(), None)
    updated = []
    with left:
        st.caption(
            "Vendor contacts for this report. Removing one leaves earlier report versions intact."
            if block.key == "subcontractor_matrix"
            else "Verified site-contact corrections are kept for future reports; unmatched entries stay in this report. Removing a contact here leaves the shared directory intact."
        )
        from app.monthly_report_contact_cards_ui import edit_contact_tables

        def prepare(current, corrected):
            nonlocal block
            # A note delivered in the same event relabels the part "This month"
            # before these rows are seen. The rows' standing scope is still the
            # part's source before that event, so judge shared writes by it.
            scoped = (block if standing_source in (None, block.source)
                      else replace(block, source=standing_source))
            proposed = _contact_table_block(block, current, has_primary)
            if (sum(len(table.rows) for table in current) > sum(len(table.rows) for table in tables)
                    and block.key == "contact_matrix" and has_primary
                    and (scoped.source == "Library" or f"directory-add-intent:{draft.profile.key}" in block.references)
                    and any(ref.startswith("directory:") for ref in block.references)
                    and any(ref.startswith("directory-site:") for ref in block.references)):
                marker = f"directory-add-intent:{draft.profile.key}"
                proposed = replace(proposed, references=tuple(dict.fromkeys((*proposed.references, marker))))
            if proposed == block:
                return current
            proposed = replace(proposed, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
            correction = (_contact_table_block(block, corrected, has_primary)
                          if corrected is not None else proposed)
            correction = replace(correction, source="This month")
            readiness = _contact_add_ready(draft, scoped, correction, p)
            if readiness is False:
                block = proposed
                return current
            if readiness is None:
                block = _pending_contact_correction(draft, scoped, correction, p)
                block, _ = _recover_contact_correction(draft, block, p)
                return _contact_block_tables(block, spec, has_primary)
            shared, failed = _keep_contact_correction(draft, scoped, correction, p)
            if failed:
                # Removal is cancelled, not silently replayed after recovery.
                block = shared if shared is not None else correction
                if _contact_pending_marker(draft) in block.references:
                    block, _ = _recover_contact_correction(draft, block, p)
                return _contact_block_tables(block, spec, has_primary)
            if shared is not None:
                if corrected is None:
                    block = shared
                    return _contact_block_tables(block, spec, has_primary)
                # A saved correction does not authorize deleting shared contacts.
                block = replace(proposed, references=shared.references)
                return current
            block = proposed
            return current

        editor_key = p + "_compact_" + _signature((tuple(table.columns for table in tables), tuple(ref for ref in block.references if not ref.startswith(("directory:", "directory-add-intent:")))))
        st.session_state[p + "_compact_editor_key"] = editor_key
        updated, _ = edit_contact_tables(
            tables, editor_key,
            field, _contact_label, vendor=block.key == "subcontractor_matrix", prepare=prepare,
            can_edit=lambda: _contact_pending_marker(draft) not in block.references)
    if show_preview:
        from app.monthly_report_row_cards_ui import _comparison_rows
        with right:
            st.write("Contacts in this report")
            for table in updated:
                st.dataframe(
                    _comparison_rows(table.columns, table.rows),
                    hide_index=True,
                    width="stretch",
                )
    changed = _contact_table_block(block, updated, has_primary)
    if changed == block:
        return block
    return preserve_asset_reviews(block, replace(changed, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint=""))


def _queue_photo_action(key, request):
    # The native callback carries only the revision displayed with the action.
    # Widget values are consumed by their ordinary fields in the full editor.
    st.session_state[key] = request


def edit_photos(draft, block, prefix, assets, field, *, show_preview=True):
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_photo_controls import photo_caption_identity, photo_order_identity, photo_move_request, move_photo, remove_photo
    from app.monthly_report_asset_instances import append_human_asset, has_human_asset
    block = preserve_asset_reviews(block, block)
    p = prefix + "_photos_" + block.key
    scope = _rich_text_scope(prefix)
    cycle_key, request_key = p + "_order_cycle", p + "_action"
    cycle = st.session_state.get(cycle_key)
    if (not isinstance(cycle, dict) or cycle.get("scope") != scope
            or not isinstance(cycle.get("token"), str) or not cycle["token"]):
        cycle = {"scope": scope, "token": uuid4().hex}
        st.session_state[cycle_key] = cycle
    baseline = photo_order_identity(draft, block, scope=scope, cycle=cycle["token"])
    request = st.session_state.pop(request_key, None)
    if request and (not isinstance(request, dict) or request.get("identity") != baseline
                    or request.get("kind") not in {"add", "done", "move", "remove"}):
        st.warning("The photos changed after this action was opened. Your photos are unchanged. Review the current photos and choose the action again.")
        request = None
    kind = request.get("kind") if request else None
    editing_key = p + "_editing"
    editing = bool(st.session_state.get(editing_key))
    if kind in {"done", "move"} and not editing:
        request, kind = None, None

    def clear_photo_fields():
        starts = (p + "_caption_", p + "_count_")
        st.session_state["report_draft_mirror"] = {
            key: value for key, value in st.session_state.get("report_draft_mirror", {}).items()
            if not key.startswith(starts)}
        for key in list(st.session_state):
            if key.startswith(starts):
                del st.session_state[key]

    def refresh_after_commit():
        st.session_state[cycle_key] = {"scope": scope, "token": uuid4().hex}
        st.session_state[prefix + "_period_editor_refresh"] = True

    with st.expander("Add photos", expanded=False):
        uploads = st.file_uploader(
            "Progress photos", label_visibility="collapsed",
            type=["jpg", "jpeg", "png", "heic", "heif", "webp"],
            accept_multiple_files=True, max_upload_size=30, key=p + "_files")
    add_slot = st.empty()
    additions = {}
    if uploads and kind == "add":
        if len(uploads) + len(block.asset_hashes) > 60 or sum(u.size for u in uploads) > 120 * 1024 * 1024:
            st.error("Add at most 60 photos per section and 120 MB in one batch.")
        else:
            pending = {}
            try:
                for upload in uploads:
                    normalized = normalize_report_image(upload.getvalue(), Path(upload.name).suffix)
                    reference = library.asset_reference(normalized.data, normalized.extension)
                    if not has_human_asset(block, reference):
                        pending[reference] = normalized.data
                additions = pending
            except (ValueError, OSError) as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else
                         "One of these photos could not be read. Choose another file; your existing photos and captions are unchanged.")

    def render_add(current):
        if uploads:
            identity = photo_order_identity(draft, current, scope=scope, cycle=st.session_state[cycle_key]["token"])
            add_slot.button("Add these photos", key=p + "_add_" + identity,
                on_click=_queue_photo_action,
                args=(request_key, {"kind": "add", "identity": identity}))

    def append_delivered_photos(current):
        if not additions:
            return current
        updated = current
        for reference in additions:
            updated = append_human_asset(updated, reference)
        assets.update(additions)
        clear_photo_fields()
        refresh_after_commit()
        return updated

    if not block.asset_hashes:
        block = append_delivered_photos(block)
        render_add(block)
        return block
    pending_indexes = pending_asset_indexes(block)
    if not pending_indexes and not editing:
        if additions:
            block = append_delivered_photos(block)
        else:
            st.caption(f"{len(block.asset_hashes)} photos ready. Captions and reviews are saved.")
            if st.button("Edit photos or captions", key=p + "_edit"):
                st.session_state[editing_key] = True
                st.session_state[prefix + "_period_editor_refresh"] = True
        render_add(block)
        return block
    done_slot = st.empty()
    edit_all = False
    if not editing and len(pending_indexes) < len(block.asset_hashes):
        st.caption(f"{len(pending_indexes)} new or changed photos. Earlier photos keep their captions and reviews.")
        edit_all = st.button("Edit all photos or captions", key=p + "_edit_all")
    visible = tuple(range(len(block.asset_hashes))) if editing else pending_indexes
    left, right = st.columns([1, 1]) if show_preview else (st.container(), None)
    slots = []
    original = block
    with left:
        field_identity = photo_caption_identity(draft, block, scope=scope)
        number = st.select_slider("Photos per page", options=list(range(1, 7)),
            key=field(p + "_count_" + field_identity, block.photos_per_page))
        existing_captions = tuple(block.asset_captions[n] if n < len(block.asset_captions) else ""
                                  for n in range(len(block.asset_hashes)))
        captions = list(existing_captions)
        for n in visible:
            with st.expander("Photo " + str(n + 1), expanded=len(block.asset_hashes) <= 2):
                captions[n] = st.text_area("Caption", key=field(p + f"_caption_{field_identity}_{n}", existing_captions[n]),
                                          max_chars=600, height=90)
                earlier, later = (st.empty(), st.empty()) if editing and len(block.asset_hashes) > 1 else (None, None)
                slots.append((n, earlier, later, st.empty()))
        changed = None
        if kind in {"move", "remove"}:
            apply = remove_photo if kind == "remove" else move_photo
            try:
                changed = apply(draft, original, request.get("action"), tuple(captions), number,
                                scope=scope, cycle=cycle["token"])
            except ValueError as exc:
                st.warning(str(exc))
            else:
                clear_photo_fields()
                refresh_after_commit()
        if changed is not None:
            block = changed
        else:
            candidate = replace(block,
                asset_captions=block.asset_captions if tuple(captions) == existing_captions else tuple(captions),
                photos_per_page=number)
            if candidate != block:
                block = preserve_asset_reviews(block, replace(candidate,
                    source="Omit" if block.source == "Omit" else "This month"))
        block = append_delivered_photos(block)
        if kind == "done" or edit_all:
            st.session_state[editing_key] = bool(edit_all and kind != "done")
            refresh_after_commit()
        # Bind callbacks to the values actually delivered in this render. A
        # later ordinary caption/density commit must not strand the next click.
        # The callback runs before the next full editor, which validates this
        # original revision before applying any newly delivered values.
        identity = photo_order_identity(draft, block, scope=scope, cycle=st.session_state[cycle_key]["token"])
        if changed is None and not additions and kind != "done" and not edit_all:
            if editing:
                done_slot.button("Done editing photos", key=p + "_done_" + identity,
                    on_click=_queue_photo_action, args=(request_key, {"kind": "done", "identity": identity}))
            for n, earlier, later, remove in slots:
                if earlier is not None:
                    for slot, label, offset in ((earlier, "Move earlier", -1), (later, "Move later", 1)):
                        slot.button(label, key=p + f"_move_{identity}_{n}_{offset}",
                            disabled=not 0 <= n + offset < len(block.asset_hashes),
                            on_click=_queue_photo_action,
                            args=(request_key, {"kind": "move", "identity": identity,
                                "action": photo_move_request(identity, block, n, offset)}))
                remove.button("Remove photo", key=p + f"_remove_{identity}_{n}",
                    on_click=_queue_photo_action,
                    args=(request_key, {"kind": "remove", "identity": identity,
                        "action": {"identity": identity, "index": n, "asset": block.asset_hashes[n]}}))
        render_add(block)
    if show_preview:
        with right:
            st.write("Photo page preview")
            try:
                count = photo_count(block)
                if count:
                    page = _page_number("Photo page", count, p, field)
                    loader = lambda ref: assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref)
                    st.image(photo_page(block, loader, page), width="stretch")
                    st.caption(f"{count} photo pages. Images keep their original proportions.")
                else:
                    st.info("No photos are included.")
            except (ValueError, OSError, KeyError) as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else
                         "This photo preview could not load. Your photos and captions are still here.")
    return block
