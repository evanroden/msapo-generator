"""An empty native table is an entry slot, not a report row."""
import streamlit as st


EMPTY_TABLES = {
    "rfi_matrix": ("No requests added.", "Add request"),
    "capital_renewal": ("No capital items added.", "Add capital item"),
    "end_of_life": ("No end-of-life items added.", "Add asset"),
}


def has_rows(block):
    return any(has_values(rows) for rows in (block.rows, *(table.rows for table in block.extra_tables)))


def has_values(rows):
    return any(value is not None and str(value).strip() for row in rows for value in row)


def _open(key):
    st.session_state[key] = True


def entry_open(block, key):
    """Opening is a display choice; keep the original block and native keys."""
    opened = has_rows(block) or bool(st.session_state.get(key + "_table_entry_open"))
    if not opened:
        st.button(EMPTY_TABLES[block.key][1], key=key + "_add_entry",
                  on_click=_open, args=(key + "_table_entry_open",))
    return opened


def empty_text_seed(seed, spec=None):
    """Blank text cells render blank, while unknown numeric/date values stay typed."""
    text_columns = None if spec is None else {
        column.title for column in spec.columns
        if column.type not in {"number", "currency", "date", "boolean"}
        or column.type == "date" and spec.key == "end_of_life"
        or column.type == "boolean" and spec.key == "rfi_matrix"
    }
    return [{key: "" if value is None and (text_columns is None or key in text_columns) else value
             for key, value in row.items()} for row in seed]
