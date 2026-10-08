"""Visible choices retain their exact image associations across navigation."""
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_picture_cards as cards


def test_visual_choices_survive_navigation_and_replace_previous_logo(monkeypatch):
    raw = BytesIO()
    Image.new("RGB", (160, 160), "navy").save(raw, "PNG")
    monkeypatch.setattr(cards, "read_import_image", lambda *a, **k: SimpleNamespace(data=raw.getvalue(), width=160))
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_picture_cards import review_pictures
from app.monthly_report_import import ImportItem
from app.monthly_report_ui import _field
items = [ImportItem(str(n), "image", "word/document.xml", n, 1, "cover", suggested_slot="cover_photo", image_part=f"word/media/{n}.png") for n in range(6)]
old = st.session_state.get("plan", {})
plan = {"selected": [], "destinations": {}, "image_notes": dict(old.get("image_notes", {}))}
errors = []
review_pictures(items, "cover", "unused", "report_cards", "synthetic", _field, old, plan, errors)
st.session_state["plan"] = plan
for error in errors:
    st.error(error)
''').run()
    assert not app.exception
    assert not app.selectbox and not app.multiselect
    assert all(w.value == "" for w in app.radio)
    assert not app.error
    app.radio[0].set_value("client_logo").run()
    app.radio[1].set_value("cover_photo").run()
    next(b for b in app.button if b.label == "Next pictures").click().run()
    assert app.session_state["plan"]["destinations"] == {"0": "client_logo", "1": "cover_photo"}
    app.radio[0].set_value("client_logo").run()
    assert not app.error
    assert app.session_state["plan"]["destinations"] == {"1": "cover_photo", "4": "client_logo"}
    app.radio[0].set_value("").run()
    next(b for b in app.button if b.label == "Previous pictures").click().run()
    assert app.radio[0].value == ""
    assert app.radio[1].value == "cover_photo"
    assert not app.error and not app.exception
