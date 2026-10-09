"""Direct person/contact/photo fields with matching report-image previews."""

from dataclasses import replace
from pathlib import Path

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


def edit_org_chart(draft, block, prefix, assets, field):
    p = prefix + "_org"
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
                "Add each person or position, then choose who they report to. The preview updates as you type. Existing image charts remain in saved history."
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
    left, right = st.columns([1, 1])
    nodes = []
    with left:
        for node in block.org_nodes:
            key = p + "_person_" + node.key
            with st.expander(
                node.name or node.role or "New position",
                expanded=len(block.org_nodes) < 3,
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
                remove = st.checkbox("Remove this position", key=key + "_remove")
                if remove and st.button("Remove position", key=key + "_remove_button"):
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
            "Add a person or position", key=p + "_add", disabled=len(nodes) >= 60
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


def _contact_rows(columns, rows, p, field):
    edited = []
    remove_index = None
    for index, row in enumerate(rows):
        title = next(
            (
                v
                for c, v in zip(columns, row)
                if any(t in c.casefold() for t in ("name", "contact", "vendor"))
                and v.strip()
            ),
            "Contact " + str(index + 1),
        )
        with st.expander(title, expanded=len(rows) <= 2):
            values = []
            for col, heading in enumerate(columns):
                value = row[col] if col < len(row) else ""
                values.append(
                    st.text_input(
                        heading or "Detail " + str(col + 1),
                        key=field(p + f"_{index}_{col}", value),
                        max_chars=500,
                    )
                )
            if st.button("Remove contact", key=p + f"_{index}_remove"):
                remove_index = index
            edited.append(tuple(values))
    return tuple(edited), remove_index


def edit_contacts(draft, spec, block, prefix, assets, field):
    block = preserve_asset_reviews(block, block)
    p = prefix + "_contacts_" + block.key
    tables = list(block.extra_tables)
    has_primary = bool(block.rows or (spec.columns and not tables))
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
                extra_tables=(ReportTable(columns, (tuple("" for c in columns),)),),
            )
            _install(draft, prefix, new, clear=p + "_table_")
        return block
    left, right = st.columns([1, 1])
    updated = []
    with left:
        st.caption(
            "Click a contact to edit its fields. Unchanged contacts stay as they are."
        )
        for n, table in enumerate(tables):
            if len(tables) > 1:
                st.write("Contact table " + str(n + 1))
            rows, removed = _contact_rows(
                table.columns, table.rows, p + f"_table_{n}", field
            )
            changed = replace(table, rows=rows)
            updated.append(changed)
            add = st.button("Add contact", key=p + f"_add_{n}")
            if add or removed is not None:
                updated[-1] = replace(
                    changed,
                    rows=(*changed.rows, tuple("" for _ in table.columns))
                    if add
                    else tuple(r for i, r in enumerate(changed.rows) if i != removed),
                )
                updated.extend(tables[n + 1 :])
                new = replace(
                    block,
                    source="This month",
                    rows=updated[0].rows if has_primary else (),
                    extra_tables=tuple(updated[1:] if has_primary else updated),
                    reviewed_fingerprint="",
                    client_reviewed_fingerprint="",
                )
                _install(draft, prefix, new, clear=p + "_table_")
    with right:
        st.write("Contacts in this report")
        for table in updated:
            st.dataframe(
                [dict(zip(table.columns, row)) for row in table.rows],
                hide_index=True,
                width="stretch",
            )
        st.caption(
            "These same values appear in the report’s contact table. Use Save progress to keep them for the next report."
        )
    changed = replace(
        block,
        rows=updated[0].rows if has_primary else (),
        extra_tables=tuple(updated[1:] if has_primary else updated),
    )
    if changed == block:
        return block
    return preserve_asset_reviews(block, replace(changed, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint=""))


def edit_photos(draft, block, prefix, assets, field):
    block = preserve_asset_reviews(block, block)
    p = prefix + "_photos_" + block.key
    with st.expander("Add progress photos", expanded=not block.asset_hashes):
        uploads = st.file_uploader(
            "Progress photos",
            type=["jpg", "jpeg", "png", "heic", "heif", "webp"],
            accept_multiple_files=True,
            max_upload_size=30,
            key=p + "_files",
        )
    if uploads and st.button("Add these photos", key=p + "_add"):
        if (
            len(uploads) + len(block.asset_hashes) > 60
            or sum(u.size for u in uploads) > 120 * 1024 * 1024
        ):
            st.error("Add at most 60 photos per section and 120 MB in one batch.")
        else:
            refs, captions = list(block.asset_hashes), list(block.asset_captions)
            provenance = dict(block.asset_provenance)
            captions.extend("" for _ in range(len(refs) - len(captions)))
            try:
                for upload in uploads:
                    normalized = normalize_report_image(
                        upload.getvalue(), Path(upload.name).suffix
                    )
                    ref = library.asset_reference(normalized.data, normalized.extension)
                    if ref not in refs:
                        refs.append(ref)
                        provenance[ref] = ()
                        captions.append("")
                        assets[ref] = normalized.data
                _install(
                    draft,
                    prefix,
                    replace(
                        block,
                        source="This month",
                        asset_hashes=tuple(refs),
                        asset_provenance=tuple(provenance.items()),
                        asset_captions=tuple(captions),
                    ),
                )
            except ValueError as exc:
                st.error(str(exc))
    if not block.asset_hashes:
        st.info("Add photos when you have them. You can work on another section first.")
        return block
    editing_key = p + "_editing"
    if not pending_asset_indexes(block) and not st.session_state.get(editing_key):
        st.caption(f"{len(block.asset_hashes)} photos ready. Captions and reviews are saved.")
        if st.button("Edit photos or captions", key=p + "_edit"):
            st.session_state[editing_key] = True
            st.rerun()
        return block
    if st.session_state.get(editing_key) and st.button("Done editing photos", key=p + "_done"):
        st.session_state[editing_key] = False
        st.rerun()
    left, right = st.columns([1, 1])
    with left:
        number = st.select_slider(
            "Photos per page",
            options=list(range(1, 7)),
            key=field(p + "_count", block.photos_per_page),
        )
        captions = []
        identity = _signature(block.asset_hashes)
        for n, ref in enumerate(block.asset_hashes):
            with st.expander(
                "Photo " + str(n + 1), expanded=len(block.asset_hashes) <= 2
            ):
                caption = st.text_area(
                    "Caption",
                    key=field(
                        p + f"_caption_{identity}_{n}",
                        block.asset_captions[n]
                        if n < len(block.asset_captions)
                        else "",
                    ),
                    max_chars=600,
                    height=90,
                )
                captions.append(caption)
                if st.button("Remove photo", key=p + f"_remove_{identity}_{n}"):
                    current_captions = (*captions, *block.asset_captions[n + 1 :])
                    indexes = tuple(i for i in range(len(block.asset_hashes)) if i != n)
                    replacement = replace(
                        block,
                        source="This month",
                        asset_hashes=tuple(block.asset_hashes[i] for i in indexes),
                        asset_captions=tuple(current_captions[i] if i < len(current_captions) else "" for i in indexes),
                        photos_per_page=number,
                    )
                    _install(draft, prefix, preserve_asset_reviews(block, replacement), clear=p + "_caption_")
        existing_captions = tuple(block.asset_captions[n] if n < len(block.asset_captions) else "" for n in range(len(block.asset_hashes)))
        candidate = replace(block, asset_captions=block.asset_captions if tuple(captions) == existing_captions else tuple(captions), photos_per_page=number)
        if candidate != block:
            block = preserve_asset_reviews(block, replace(candidate, source="This month"))
        candidate = block
    with right:
        st.write("Photo page preview")
        try:
            count = photo_count(candidate)
            if count:
                page = _page_number("Photo page", count, p, field)
                loader = lambda ref: (
                    assets.get(ref)
                    or library.read_asset(
                        draft.profile.contract, draft.profile.key, ref
                    )
                )
                st.image(photo_page(candidate, loader, page), width="stretch")
                st.caption(
                    f"{count} photo pages. Images keep their original proportions."
                )
            else:
                st.info("No photos are included.")
        except ValueError as exc:
            st.error(str(exc))
    return block
