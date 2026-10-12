"""Cover photographs use one clickable gallery, not six independent radios."""
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_picture_cards as cards


def test_cover_gallery_selects_exactly_one_picture_and_can_choose_none(monkeypatch):
    raw = BytesIO()
    Image.new("RGB", (600, 400), "navy").save(raw, "PNG")
    monkeypatch.setattr(cards, "read_import_image",
                        lambda *a, **k: SimpleNamespace(data=raw.getvalue(), width=600))
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_picture_cards import review_pictures
from app.monthly_report_import import ImportItem
from app.monthly_report_ui import _field
items = [ImportItem(str(n), "image", "word/document.xml", n, 1, "cover",
                    suggested_slot="cover_photo", image_part=f"word/media/{n}.png",
                    image_width=600, image_height=400) for n in range(6)]
old = st.session_state.get("plan", {})
plan = {"selected": list(old.get("selected", ())),
        "destinations": dict(old.get("destinations", {})),
        "image_notes": dict(old.get("image_notes", {}))}
errors = []
review_pictures(items, "cover", "unused", "report_cards", "synthetic",
                _field, old, plan, errors, allow_branding=False)
st.session_state["plan"] = plan
for error in errors:
    st.error(error)
''').run()
    assert not app.exception and not app.error
    assert not app.radio
    assert len([button for button in app.button if button.label.startswith("Choose picture")]) == 6
    assert app.session_state["plan"]["picture_choices"] == []
    next(button for button in app.button if button.label == "Choose picture 2").click().run()
    assert app.session_state["plan"]["destinations"] == {"1": "cover_photo"}
    assert app.session_state["plan"]["selected"] == ["1"]
    next(button for button in app.button if button.label == "Choose picture 5").click().run()
    assert app.session_state["plan"]["destinations"] == {"4": "cover_photo"}
    assert app.session_state["plan"]["selected"] == ["4"]
    next(button for button in app.button if button.label == "No cover photograph").click().run()
    assert app.session_state["plan"]["destinations"] == {}
    assert app.session_state["plan"]["selected"] == []
