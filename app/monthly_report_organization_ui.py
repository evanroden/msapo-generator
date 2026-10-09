"""Content-first organization workspace with one part open for changes at a time."""

from dataclasses import replace

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_workflow_standards import WORKFLOW_KEYS


ORGANIZATION_PARTS = (
    ("org_chart", "Team chart"),
    ("business_hours_workflow", "Daytime outage procedure"),
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
        st.caption("Current report content")
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
            st.warning("This saved page is unavailable. Choose Change to replace or remove it.")


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
    """Return updated blocks; only an explicit Change opens a part's editor.

    ``edit_content(spec, block)`` supplies the existing procedure/image editor.
    Original tables, pages, notes and provenance are passed through unchanged
    when a part stays closed. This wrapper never converts imported charts.
    """
    from app.monthly_report_visual_ui import edit_contacts, edit_org_chart

    updated = dict(blocks)
    active_key = prefix + "_organization_change"
    st.caption("People and contacts carry forward. Open Change only when details need updating.")

    def render_part(key, title):
        if key not in specs:
            return
        spec = specs[key]
        block = updated.get(key, ResolvedBlock(key, "This month" if spec.required else "Omit"))
        st.markdown("#### " + title)
        current_draft = replace(draft, blocks=tuple(updated.values()))
        _preview_part(current_draft, spec, block, prefix, assets, title, show_preview=show_preview)
        if st.session_state.get(active_key) != key:
            st.button("Change " + title.lower(), key=prefix + "_organization_open_" + key,
                      on_click=st.session_state.__setitem__, args=(active_key, key))
            return
        st.button("Done changing " + title.lower(), key=prefix + "_organization_close_" + key,
                  on_click=st.session_state.__setitem__, args=(active_key, ""))
        if key == "contact_matrix":
            changed = edit_contacts(current_draft, spec, block, prefix, assets, field, show_preview=show_preview)
            changed = _edit_notes(changed, prefix, field)
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
        st.caption("The daytime and after-hours procedures are reused across contracts. Saved report procedures stay in place; changes here apply to this report.")
        for key, title in ORGANIZATION_PARTS:
            if key in WORKFLOW_KEYS:
                render_part(key, title)
    return updated
