"""A targeted correction when imported table headings ran together."""

from dataclasses import replace

import streamlit as st

from app.monthly_report_content_policy import ambiguous_price_columns, table_price_columns
from app.monthly_report_editor import _signature


def review_table_headings(table, key, field):
    """Preserve every cell until the operator confirms unambiguous headings."""
    if not ambiguous_price_columns(table.columns, table.rows):
        return table
    st.warning("Some column headings ran together in the uploaded report. Check the table below and name each column. No equipment or recommendation has been removed.")
    st.dataframe([dict(zip(table.columns, row)) for row in table.rows[:12]], hide_index=True)
    key += "_headings_" + _signature(table.columns)
    headings = tuple(st.text_input(f"Column {n + 1} heading", key=field(key + f"_{n}", title))
                     .strip() for n, title in enumerate(table.columns))
    valid = all(headings) and len(set(headings)) == len(headings) and not ambiguous_price_columns(headings, table.rows)
    st.caption("Use the meaning of the values, such as Equipment, Replacement timing, Cost and Recommendation. Confirmed price columns will be left out of the client report; the uploaded original remains available.")
    if st.button("Use these column names", key=key + "_apply", disabled=not valid):
        removed = set(table_price_columns(headings, table.rows))
        keep = tuple(n for n in range(len(headings)) if n not in removed)
        return replace(table, columns=tuple(headings[n] for n in keep),
                       rows=tuple(tuple(row[n] if n < len(row) else "" for n in keep) for row in table.rows))
    return table
