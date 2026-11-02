"""Edit retained Training source tables without inventing canonical sessions."""
from dataclasses import replace

import streamlit as st

from app.monthly_report_editor import _signature
from app.monthly_report_work_order_rows_ui import edit_imported_work_order_table


def render_source_tables(draft, block, prefix):
    """Reuse the snapshot-bound native row editor for report-only source values.

    Reserved Training tables belong to the matrix/session editors (including
    annual matrices); source headings alone never grant either role. The shared
    row editor keeps cell edits mounted, handles structural edits once and
    refuses stale deltas after source/scope/incarnation changes.
    """
    indexes = tuple(index for index, table in enumerate(block.extra_tables)
                    if not table.reference.startswith("training:"))
    if not indexes:
        return block
    from app.monthly_report_guided import _rich_text_scope
    scope = (
        _rich_text_scope(prefix), draft.profile.contract, draft.profile.key,
        tuple((site.key, site.title, site.aliases) for site in draft.profile.facilities),
        draft.period.key, block.source == "Omit", block.references,
        tuple((index, block.extra_tables[index].reference, block.extra_tables[index].columns)
              for index in indexes),
    )
    tables = list(block.extra_tables)
    with st.expander("Imported Training tables", expanded=True,
                     key=prefix + "_training_source_tables_" + _signature(scope)):
        st.caption("Edit source values for this report only. Shared requirements and monthly sessions stay separate; blank dates and hours stay blank.")
        if block.source == "Omit":
            st.caption("These tables remain left out until you choose Include in this report.")
        for number, index in enumerate(indexes, 1):
            table = tables[index]
            st.text(f"Imported Training source {number} of {len(indexes)} · {len(table.rows)} source rows")
            if (not table.columns or len(set(table.columns)) != len(table.columns)
                    or any(len(row) != len(table.columns) for row in table.rows)):
                # A dictionary-backed grid cannot faithfully represent duplicate
                # headers or ragged rows. Preserve the complete canonical table
                # instead of silently losing cells merely by opening Training.
                st.warning("This source table has an ambiguous column structure. Its values are retained; correct its mapping in the Starting Report review before editing here.")
                st.text(" | ".join(table.columns))
                for row in table.rows[:12]:
                    st.text(" | ".join(str(value) for value in row))
                if len(table.rows) > 12:
                    st.caption(f"Showing 12 of {len(table.rows)} retained rows.")
                continue
            tables[index] = edit_imported_work_order_table(
                table, prefix + f"_training_source_table_{index}", scope, prefix)
    if tuple(tables) == block.extra_tables:
        return block
    # Correcting retained values does not override an explicit exclusion or
    # write a shared matrix. Ordinary included edits become report-only work.
    return replace(block, extra_tables=tuple(tables),
                   source="Omit" if block.source == "Omit" else "This month",
                   reviewed_fingerprint="", client_reviewed_fingerprint="")
