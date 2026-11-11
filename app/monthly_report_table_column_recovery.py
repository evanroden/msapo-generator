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
