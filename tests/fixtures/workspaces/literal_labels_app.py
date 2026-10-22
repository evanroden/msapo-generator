"""Synthetic-only rendering fixture; no storage, network or real report inputs."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from app.monthly_report_ui_text import literal


VALUES = (
    "[Synthetic](https://example.invalid) **Account**",
    "https://example.invalid/one?q=two",
    "www.example.invalid",
    "synthetic@example.invalid",
    "**Bold** _em_ `code` & <tag> $money$ :red[text]",
)

st.title("Synthetic literal-label rendering")
for index, value in enumerate(VALUES):
    with st.container(key=f"literal_case_{index}"):
        st.subheader(literal(value), anchor=False)
        st.caption(literal(value))
        if st.button(literal(value), key=f"literal_button_{index}"):
            st.session_state["literal_selected"] = value
        st.checkbox(literal(value), key=f"literal_checkbox_{index}")
        st.text_input(literal(value), value=value, key=f"literal_input_{index}")
        st.radio("Synthetic choice", [value], format_func=literal, key=f"literal_radio_{index}")
st.text("Selected value: " + st.session_state.get("literal_selected", "none"))
