"""Synthetic native images only; no source library, storage or remote services."""
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PIL import Image
import streamlit as st
from app.monthly_report_picture_accessibility import review_image
from app.monthly_report_ui_text import literal

raw = BytesIO()
Image.new("RGB", (240, 120), "navy").save(raw, "PNG")
st.title("Synthetic imported picture descriptions")
updated = st.checkbox("Use updated caption")
caption = "Updated synthetic pump inspection" if updated else "Synthetic pump inspection"
review_image(raw.getvalue(), width=240, caption=literal(caption + " · Image-only"), key="synthetic_first")
review_image(raw.getvalue(), width=240, caption="Original chart/contact page 2 · Image-only", key="synthetic_second")
with st.container(key="synthetic_unrelated_picture"):
    st.image(raw.getvalue(), width=240, caption="Unrelated native image")
st.button("Unrelated rerun")
