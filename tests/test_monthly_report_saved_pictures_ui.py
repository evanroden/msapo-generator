"""Saved-picture edits stay associated with their captions and evidence."""
from streamlit.testing.v1 import AppTest


def app_for(count=6, references=None):
    return AppTest.from_string('''
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_saved_pictures_ui import edit_saved_pictures
raw=BytesIO(); Image.new("RGB", (160,160), "navy").save(raw, "PNG")
original=ResolvedBlock("org_chart", "Library", asset_hashes=tuple(str(n) for n in range(COUNT)), asset_captions=tuple("Caption " + str(n) for n in range(COUNT)), references=REFERENCES, client_reviewed_fingerprint="previous-review", reviewed_fingerprint="previous-ai-review")
st.session_state.setdefault("original",original)
block=st.session_state.get("draft", original)
st.session_state["draft"]=edit_saved_pictures(block, "report_saved_cards", lambda ref:raw.getvalue())
'''.replace('COUNT', str(count)).replace('REFERENCES', repr(references if references is not None else tuple('source-'+str(n) for n in range(count))))).run()


def test_saved_picture_removal_survives_navigation_and_preserves_associations(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app=app_for()
    assert not app.exception and not app.selectbox and not app.multiselect
    assert len([b for b in app.button if b.label.startswith("Remove")]) == 4
    next(b for b in app.button if b.label == "Next pictures").click().run()
    next(b for b in app.button if b.label == "Remove picture 5").click().run()
    block=app.session_state["draft"]
    assert block.asset_hashes == ("0", "1", "2", "3", "5")
    assert block.asset_captions[-1] == "Caption 5" and block.references[-1] == "source-5"
    assert not block.client_reviewed_fingerprint and not block.reviewed_fingerprint
    next(b for b in app.button if b.label == "Previous pictures").click().run()
    next(b for b in app.button if b.label == "Remove picture 1").click().run()
    app.run()
    assert app.session_state["draft"].asset_hashes == ("1", "2", "3", "5")
    assert not any(b.label in ("Previous pictures", "Next pictures") for b in app.button)
    assert app.session_state["original"].asset_hashes == tuple(str(n) for n in range(6))
    assert not app.exception


def test_single_picture_has_no_navigation_and_empty_result_stays_empty():
    app=app_for(1, ("paragraph-source", "other-source"))
    assert [b.label for b in app.button] == ["Remove this picture"]
    app.button[0].click().run()
    app.run()
    assert not app.session_state["draft"].asset_hashes
    assert app.session_state["draft"].references == ("paragraph-source", "other-source")
    assert not app.button and not app.exception


def test_stale_removal_never_removes_a_different_picture():
    app=app_for(2)
    app.session_state["report_saved_cards_remove_request"] = (("older-image",), 0)
    app.run()
    assert app.session_state["draft"].asset_hashes == ("0", "1")
