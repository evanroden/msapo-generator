"""Explicit positional imported-table heading recovery for layout preflight.

Keep every old heading, blank, duplicate, source reference and row cell.
A new positional heading exists only after an operator confirms it.
"""
from dataclasses import replace
from hashlib import sha256

import streamlit as st

from app.monthly_report_correction_ui import native_warning_marker


def missing_positions(table):
    if not any(str(cell).strip() for row in table.rows for cell in row):
        return ()
    width = max((len(row) for row in table.rows), default=0)
    return tuple(range(len(table.columns), width))


def edit_missing_positions(table, block, index, prefix, field):
    positions = missing_positions(table)
    if not positions:
        return table
    owner = block.key + ":imported:" + str(index)
    scope = sha256((block.fingerprint + "\\0" + table.reference + "\\0" +
                    str(index)).encode()).hexdigest()
    st.warning("Imported table " + str(index + 1) + " has " +
               str(len(table.columns)) + " headings for " +
               str(len(table.columns) + len(positions)) +
               " positional columns. Supply each missing heading, or deliberately "
               "leave a heading blank; existing values and columns are retained.")
    entered = []
    for offset, position in enumerate(positions):
        key = prefix + "_missing_table_column_" + scope + "_" + str(position)
        if offset == 0:
            code = "table_missing_columns" if not table.columns else "table_columns"
            st.markdown(native_warning_marker(prefix, code, owner,
                block.fingerprint, key, kind="input"), unsafe_allow_html=True)
        entered.append(st.text_input(
            "Imported table " + str(index + 1) + " · column " +
            str(position + 1) + " heading (blank allowed)", key=field(key, "")))
    if st.button("Confirm positional columns for imported table " + str(index + 1),
                 key=prefix + "_confirm_table_columns_" + scope):
        return replace(table, columns=(*table.columns, *entered))
    return table


def fixed_width_defect(spec, block):
    if not spec.columns or not block.rows:
        return 0
    return max((len(row) for row in block.rows), default=0) - len(spec.columns)


def edit_fixed_column_schema(check, draft, prefix, field):
    """Correct only the exact fixed table's schema, never truncate source rows.

    Existing positional columns, even duplicate or blank headings, are retained.
    Native data editing is held while extra source cells are without headings.
    """
    if not check.blocking or check.code != "table_columns" or not check.message.startswith("Row "):
        return
    from app.monthly_report_model import ColumnSpec
    blocks = [block for block in draft.blocks if block.key == check.block_key]
    specs = [(section, spec) for section in draft.sections if section.included
             for spec in section.blocks if spec.key == check.block_key]
    if len(blocks) != 1 or len(specs) != 1:
        st.caption("This table has no unique schema owner. Restore the exact "
                   "original table before editing the column count.")
        return
    block, (section, spec) = blocks[0], specs[0]
    number = fixed_width_defect(spec, block)
    if number <= 0:
        return
    owner = section.key + ":fixed:" + block.key
    signature = sha256((block.fingerprint + "\\0" + repr(spec.columns)).encode()).hexdigest()
    labels = []
    for offset in range(number):
        position = len(spec.columns) + offset
        key = prefix + "_fix_fixed_column_" + signature + "_" + str(position)
        if offset == 0:
            st.markdown(native_warning_marker(prefix, "table_columns", owner,
                                               signature, key, kind="input"),
                        unsafe_allow_html=True)
        labels.append(st.text_input(
            "Table " + block.key.replace("_", " ") + " · column " +
            str(position + 1) + " heading", key=field(key, "")))
    if st.button("Confirm additional positional columns", key=prefix +
                 "_confirm_fixed_columns_" + signature):
        from app.monthly_report_correction_targets import report_identity
        original = st.session_state.get(prefix + "_draft")
        if original is None or original.fingerprint != draft.fingerprint or (
                report_identity(original) != report_identity(draft)):
            st.warning("That table changed. The original rows remain; review its current columns.")
            return
        names = {column.key for column in spec.columns}
        additions = []
        for offset, label in enumerate(labels):
            position = len(spec.columns) + offset
            key = "source_position_" + str(position + 1)
            while key in names:
                key += "_"
            names.add(key)
            additions.append(ColumnSpec(key, label))
        changed = replace(spec, columns=(*spec.columns, *additions))
        sections = tuple(replace(item, blocks=tuple(
            changed if part is spec else part for part in item.blocks))
            if item is section else item for item in original.sections)
        st.session_state[prefix + "_draft"] = replace(original, sections=sections)
        st.session_state[prefix + "_period_editor_refresh"] = True
        # This Review action runs after ordinary editors were captured. Stop
        # this render before the outer workflow writes its older local draft
        # back to session state; the next render uses the repaired schema.
        st.rerun()


def edit_unsafe_primary_heading(check, draft, prefix, field):
    """One exact source-schema heading per correction; no value relabeling.

    Unsafe mixed pricing headings require the operator to remove any numeric
    price-like values first. A harmless rename cannot disguise amounts.
    """
    if not check.blocking or check.code not in (
            "pricing", "placeholder", "text_character"):
        return
    from app.monthly_report_non_narrative_recovery import unsafe
    from app.monthly_report_content_policy import ambiguous_price_columns
    matches = [(section, spec) for section in draft.sections if section.included
               for spec in section.blocks if spec.key == check.block_key]
    blocks = [block for block in draft.blocks if block.key == check.block_key]
    if len(matches) != 1 or len(blocks) != 1:
        return
    section, spec = matches[0]
    block = blocks[0]
    if not spec.columns or block.source == "Omit":
        return
    ambiguous = set(ambiguous_price_columns(
        tuple(column.title for column in spec.columns), block.rows))
    flagged = [index for index, column in enumerate(spec.columns)
               if unsafe(column.title, check.code) or
               (check.code == "pricing" and index in ambiguous)]
    if not flagged:
        return
    for index in flagged:
        column = spec.columns[index]
        # Each original physical column, not its possibly duplicate label, is
        # one correction target. Unchanged row values and key/type are retained.
        owner = section.key + ":heading:" + block.key + ":" + str(index)
        revision = sha256((block.fingerprint + "\\0" +
                           repr(spec.columns)).encode()).hexdigest()
        key = prefix + "_repair_schema_heading_" + check.code + "_" + revision + "_" + str(index)
        st.markdown(native_warning_marker(prefix, check.code, owner,
                                          revision, key, kind="input"),
                    unsafe_allow_html=True)
        changed = st.text_input("Column " + str(index + 1) + " heading",
                                value=column.title, key=field(key, column.title))
        if st.button("Confirm heading for physical column " + str(index + 1),
                     key=prefix + "_repair_schema_confirm_" + check.code +
                     "_" + revision + "_" + str(index)):
            current = st.session_state.get(prefix + "_draft")
            if current is None or current.fingerprint != draft.fingerprint:
                st.warning("The table changed; no heading was replaced. "
                           "Review its current columns.")
                return
            if changed == column.title or not changed.strip():
                st.warning("Enter the corrected heading before confirming.")
                continue
            if check.code == "pricing" and (
                    column.type == "currency" or
                    any(index < len(row) and
                        any(character.isdigit() for character in str(row[index]))
                        for row in block.rows)):
                st.warning("This column still contains possible monetary values. "
                           "Correct its exact cells or exclude the financial "
                           "column first; renaming alone cannot approve it.")
                continue
            new_columns = tuple(replace(item, title=changed)
                                if pos == index else item
                                for pos, item in enumerate(spec.columns))
            revised_spec = replace(spec, columns=new_columns)
            revised = tuple(replace(item, blocks=tuple(
                revised_spec if part is spec else part for part in item.blocks))
                if item is section else item for item in current.sections)
            st.session_state[prefix + "_draft"] = replace(current, sections=revised)
            st.session_state[prefix + "_period_editor_refresh"] = True
            st.rerun()
