"""Content-first organization workspace with one part open for changes at a time."""

from dataclasses import replace

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_workflow_standards import WORKFLOW_KEYS


ORGANIZATION_PARTS = (
    ("org_chart", "Team chart"),
    ("business_hours_workflow", "Business-hours outage procedure"),
    ("after_hours_workflow", "After-hours outage procedure"),
    ("contact_matrix", "Facility contacts"),
)


def _preview_table(columns, rows):
    """Show every imported cell, including tables with blank/repeated headings."""
    if not rows:
        return
    width = max(len(columns), max(map(len, rows), default=0))
    names = []
    for index in range(width):
        original = columns[index] if index < len(columns) else ""
        name = original or "Column " + str(index + 1)
        while name in names:
            name += " · " + str(index + 1)
        names.append(name)
    st.dataframe(
        {name: [row[index] if index < len(row) else "" for row in rows]
         for index, name in enumerate(names)},
        hide_index=True,
        width="stretch",
    )


def _preview_part(draft, spec, block, prefix, assets, title, *, show_preview=True):
    has_content = bool(block.text.strip() or block.rows or block.extra_tables
                       or block.asset_hashes or block.org_nodes)
    if block.source == "Omit":
        st.caption("Not included in this report." + (" Saved content is shown below." if has_content else ""))
    elif has_content:
        # Report count summaries are derived from actual saved objects, not
        # a claim of substantive review or completion.
        details = []
        if block.org_nodes:
            count = len(block.org_nodes)
            details.append(f"{count} {'person' if count == 1 else 'people'}")
        if block.rows:
            count = len(block.rows)
            details.append(f"{count} {'row' if count == 1 else 'rows'}")
        if block.extra_tables:
            count = sum(len(table.rows) for table in block.extra_tables)
            if count:
                details.append(f"{count} table {'row' if count == 1 else 'rows'}")
        if block.asset_hashes:
            count = len(block.asset_hashes)
            details.append(f"{count} {'page' if count == 1 else 'pages'}")
        st.caption(" · ".join(details) if details else ("Notes included" if block.text.strip() else "No entries recorded"))
    else:
        st.caption("Not added yet")
    if not show_preview:
        return
    if block.text.strip():
        st.text(block.text)
    _preview_table(tuple(c.title for c in spec.columns), block.rows)
    for table in block.extra_tables:
        _preview_table(table.columns, table.rows)
    if block.org_nodes:
        from app.monthly_report_visuals import org_groups, org_page

        try:
            count = len(org_groups(block.org_nodes))
            page = _preview_page(prefix, block.key + "_chart", count, title)
            st.image(org_page(block.org_nodes, page), width="stretch")
        except ValueError as exc:
            st.warning("This chart needs a correction: " + str(exc))
    if block.asset_hashes:
        page = _preview_page(prefix, block.key, len(block.asset_hashes), title)
        ref = block.asset_hashes[page]
        try:
            raw = assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref)
            caption = block.asset_captions[page] if page < len(block.asset_captions) else ""
            st.image(raw, caption=caption or None, width="stretch")
        except (ValueError, OSError):
            st.warning("This saved page is unavailable. Choose Edit to replace or remove it.")


def _preview_page(prefix, key, count, title):
    if count <= 1:
        return 0
    return int(st.number_input(
        title + " page", min_value=1, max_value=count, value=1,
        key=prefix + "_organization_preview_" + key + "_" + str(count),
    )) - 1


def _edit_notes(block, prefix, field):
    """Specialized chart/contact editors must also retain their imported notes."""
    if not block.text.strip():
        return block
    if block.ai_paragraphs:
        st.caption("Source-linked notes can be changed in the wording and sources editor.")
        st.text(block.text)
        return block
    text = st.text_area(
        "Notes included with this part",
        key=field(prefix + "_organization_notes_" + block.key, block.text),
        height=120,
    )
    if text == block.text:
        return block
    return replace(block, text=text, source="This month", reviewed_fingerprint="",
                   client_reviewed_fingerprint="")


def render_organization(draft, blocks, specs, prefix, assets, field, edit_content, *, show_preview=True):
    """Return updated blocks; only an explicit Edit opens a part's editor.

    ``edit_content(spec, block)`` supplies the existing procedure/image editor.
    Original tables, pages, notes and provenance are passed through unchanged
    when a part stays closed. This wrapper never converts imported charts.
    """
    from app.monthly_report_visual_ui import edit_contacts, edit_org_chart

    if not draft.prepared_by.strip():
        st.info("Enter [Prepared by](#report-prepared-by) to view or edit saved people and contacts. Existing records remain unchanged.")
        return blocks
    updated = dict(blocks)
    active_key = prefix + "_organization_change"
    st.caption("Saved people and contacts are shown below. Edit only what changed.")

    def render_part(key, title):
        if key not in specs:
            return
        spec = specs[key]
        block = updated.get(key, ResolvedBlock(key, "This month" if spec.required else "Omit"))
        st.markdown("#### " + title)
        current_draft = replace(draft, blocks=tuple(updated.values()))
        _preview_part(current_draft, spec, block, prefix, assets, title, show_preview=show_preview)
        if st.session_state.get(active_key) != key:
            action = {
                "org_chart": "Edit chart",
                "contact_matrix": "Edit contacts",
                "business_hours_workflow": "Edit business-hours outage procedure",
                "after_hours_workflow": "Edit after-hours outage procedure",
            }[key]
            st.button(action, key=prefix + "_organization_open_" + key,
                      on_click=st.session_state.__setitem__, args=(active_key, key))
            return
        st.button("Done", key=prefix + "_organization_close_" + key,
                  on_click=st.session_state.__setitem__, args=(active_key, ""))
        if key == "contact_matrix":
            changed = edit_contacts(current_draft, spec, block, prefix, assets, field, show_preview=show_preview)
            changed = _edit_notes(changed, prefix, field)
            if changed != block:
                from app import monthly_report_directory as directory
                try:
                    shared = directory.automatically_keep_directory_contact_edits(
                        draft.profile, block, changed, draft.prepared_by)
                    if shared is not None:
                        changed = shared
                        st.caption("Updated site contacts are kept for future reports. Earlier completed reports are unchanged.")
                except (ValueError, OSError):
                    st.warning("The shared contact record could not be updated. "
                               "Your current report edits remain available; review the latest site contacts.")
        elif key == "org_chart":
            if block.org_nodes:
                changed = edit_org_chart(current_draft, block, prefix, assets, field, show_preview=show_preview)
                changed = _edit_notes(changed, prefix, field)
            else:
                changed = edit_content(spec, block)
                with st.expander("Build an editable team chart (optional)"):
                    changed = edit_org_chart(
                        replace(current_draft, blocks=tuple(changed if b.key == key else b for b in current_draft.blocks)),
                        changed, prefix, assets, field, show_preview=show_preview,
                    )
        else:
            changed = edit_content(spec, block)
        # Some older editors mark their source just by being opened. Opening
        # and closing an unchanged part must not invalidate its saved review.
        updated[key] = block if replace(changed, source=block.source) == block else changed
    for key, title in ORGANIZATION_PARTS:
        if key not in WORKFLOW_KEYS:
            render_part(key, title)
    with st.expander("ENFRA outage procedures", expanded=False):
        st.caption("Saved procedures are included when selected. Changes here affect this report.")
        for key, title in ORGANIZATION_PARTS:
            if key in WORKFLOW_KEYS:
                render_part(key, title)
    return updated
