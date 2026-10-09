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


def test_reviewed_gallery_is_optional_and_removing_one_keeps_other_reviews():
    from dataclasses import replace
    from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes

    app = app_for(2)
    app.session_state["draft"] = approve_all_assets(app.session_state["draft"])
    app.run()
    assert [b.label for b in app.button] == ["View or change pictures"]
    assert not app.get("imgs")
    app.button[0].click().run()
    assert len([b for b in app.button if b.label.startswith("Remove")]) == 2
    next(b for b in app.button if b.label == "Remove picture 1").click().run()
    assert app.session_state["draft"].asset_hashes == ("1",)
    assert not pending_asset_indexes(app.session_state["draft"])
    next(b for b in app.button if b.label == "Done editing pictures").click().run()
    assert [b.label for b in app.button] == ["View or change pictures"]
    original = app.session_state["draft"]
    app.session_state["draft"] = replace(original, asset_captions=("Changed caption",))
    app.run()
    assert pending_asset_indexes(app.session_state["draft"]) == (0,)
    assert any(b.label == "Remove this picture" for b in app.button)
    assert not app.exception


def test_removal_uses_source_mapping_and_retains_shared_or_native_evidence():
    from dataclasses import replace
    from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_saved_pictures_ui import remove_saved_picture

    block = ResolvedBlock(
        "vendor_reports", "This month", asset_hashes=("one.png", "two.png"),
        references=("first-source", "second-source"),
        asset_provenance=(("one.png", ("second-source",)), ("two.png", ("first-source",))),
    )
    reviewed = approve_all_assets(block)
    removed = remove_saved_picture(reviewed, 0)
    assert removed.references == ("first-source",)
    assert not pending_asset_indexes(removed)
    shared = replace(reviewed, asset_provenance=(("one.png", ("first-source",)), ("two.png", ("first-source",))))
    assert remove_saved_picture(shared, 0).references == reviewed.references
    native = replace(reviewed, text="This narrative uses both reports.")
    assert remove_saved_picture(native, 0).references == native.references
