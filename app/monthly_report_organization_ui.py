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
            details.append(f"{count} {'position' if count == 1 else 'positions'}")
        if block.rows:
            count = sum(any(value.strip() for value in row) for row in block.rows)
            if count:
                unit = ("contact" if count == 1 else "contacts") if block.key == "contact_matrix" else ("row" if count == 1 else "rows")
                details.append(f"{count} {unit}")
        if block.extra_tables:
            count = sum(any(value.strip() for value in row)
                        for table in block.extra_tables for row in table.rows)
            if count:
                unit = ("contact" if count == 1 else "contacts") if block.key == "contact_matrix" else ("table row" if count == 1 else "table rows")
                details.append(f"{count} {unit}")
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


def _notes_baseline(block):
    return ResolvedBlock(block.key, "Omit" if block.source == "Omit" else "This month",
                         text=block.text, references=block.references)


def _delivered_notes(block, prefix):
    """Include a delivered note before a sibling Add/Remove/Done can rerun."""
    if block.ai_paragraphs:
        return block
    from app.monthly_report_guided import _edited_rich_text, _rich_text_editor_key, _rich_text_scope
    key = _rich_text_editor_key(prefix, block)
    receipt = st.session_state.get(key + "_explicitly_edited")
    if (isinstance(receipt, dict) and receipt.get("scope") == _rich_text_scope(prefix)
            and receipt.get("baseline") == _notes_baseline(block).fingerprint
            and isinstance(receipt.get("text"), str)
            and receipt["text"] == st.session_state.get(key)):
        return _edited_rich_text(block, receipt["text"])
    return block


def _edit_notes(block, prefix, field, *, canonical_before):
    """Specialized chart/contact editors must also retain their imported notes."""
    if block.ai_paragraphs:
        st.caption("Source-linked notes can be changed in the wording and sources editor.")
        st.text(block.text)
        return block
    from app.monthly_report_guided import (
        _edited_rich_text, _mark_explicit_rich_text_edit, _rich_text_editor_key,
        _rich_text_scope, _render_rich_text_recovery,
    )
    # A contact row or chart position can change in the same native submission.
    # Bind the note receipt to its own wording/source/incarnation, so those
    # independent edits cannot invalidate an accepted note or be overwritten.
    baseline = _notes_baseline(canonical_before)
    key = _rich_text_editor_key(prefix, block)
    marker = key + "_explicitly_edited"
    scope = _rich_text_scope(prefix)
    displayed = st.session_state.get(key, block.text)
    receipt = st.session_state.get(marker)
    valid = (isinstance(receipt, dict) and isinstance(receipt.get("text"), str)
             and receipt.get("scope") == scope)
    if valid and receipt.get("result") == baseline.fingerprint:
        st.session_state.pop(marker, None)
        valid = False
    submitted = (valid and receipt.get("baseline") == baseline.fingerprint
                 and receipt["text"] == displayed)
    if valid and not submitted:
        st.session_state[marker + "_recovery"] = receipt
    if displayed != block.text and not submitted:
        st.session_state[key] = block.text
    text = st.text_area(
        "Notes included with this part",
        value=receipt["text"] if submitted else block.text,
        key=field(key, block.text),
        height=120,
        on_change=_mark_explicit_rich_text_edit,
        args=(marker, key, baseline, scope),
    )
    if submitted:
        if text != block.text:
            block = _edited_rich_text(block, text)
    else:
        st.session_state.pop(marker, None)
    _render_rich_text_recovery(marker, key, baseline, scope)
    return block


def render_organization(draft, blocks, specs, prefix, assets, field, edit_content, *, show_preview=True):
    """Return updated blocks; only an explicit Edit opens a part's editor.

    ``edit_content(spec, block)`` supplies the existing procedure/image editor.
    Original tables, pages, notes and provenance are passed through unchanged
    when a part stays closed. This wrapper never converts imported charts.
    """
    from app.monthly_report_visual_ui import edit_contacts, edit_org_chart

    if not draft.prepared_by.strip():
        st.info("Enter your name above to view or edit saved people and contacts.")
        return blocks
    updated = dict(blocks)
    active_key = prefix + "_organization_change"

    def render_part(key, title):
        if key not in specs:
            return
        spec = specs[key]
        canonical_before = updated.get(key, ResolvedBlock(key, "This month" if spec.required else "Omit"))
        block = _delivered_notes(canonical_before, prefix) if key in ("contact_matrix", "org_chart") else canonical_before
        if block != canonical_before:
            updated[key] = block
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
        # These editors bypass the shared content editor, so they offer its
        # explicit Include for a left-out part here (once per part).
        from app.monthly_report_guided import _include_left_out
        if key == "contact_matrix":
            changed = _include_left_out(spec, block, prefix)
            changed = edit_contacts(current_draft, spec, changed, prefix, assets, field, show_preview=show_preview)
            changed = _edit_notes(changed, prefix, field, canonical_before=canonical_before)
        elif key == "org_chart":
            if block.org_nodes:
                changed = _include_left_out(spec, block, prefix)
                changed = edit_org_chart(current_draft, changed, prefix, assets, field, show_preview=show_preview)
                changed = _edit_notes(changed, prefix, field, canonical_before=canonical_before)
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
        # and closing an unchanged part must not invalidate its saved review;
        # an explicit Include of a left-out part is a real change.
        from app.monthly_report_guided import included_left_out
        updated[key] = (changed if included_left_out(prefix, key)
                        or replace(changed, source=block.source) != block else block)
    for key, title in ORGANIZATION_PARTS:
        if key not in WORKFLOW_KEYS:
            render_part(key, title)
    with st.expander("ENFRA outage procedures", expanded=False):
        st.caption("Saved procedures are included when selected. Changes here affect this report.")
        for key, title in ORGANIZATION_PARTS:
            if key in WORKFLOW_KEYS:
                render_part(key, title)
    return updated
