"""Synthetic cover edits preserve accepted artwork and unrelated content."""

from dataclasses import replace
from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_cover_ui as ui
from app.monthly_report_model import ResolvedBlock


def picture(color="navy"):
    raw = BytesIO()
    Image.new("RGB", (100, 60), color).save(raw, "PNG")
    raw.name, raw.size = "synthetic.png", len(raw.getvalue())
    return raw


def cover_app(*, empty=False):
    return AppTest.from_string('''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_cover_ui import render_cover
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_ui import _field
raw=BytesIO(); Image.new("RGB", (100,60), "navy").save(raw, "PNG")
assets=st.session_state.setdefault("assets", {"old.png":raw.getvalue()})
blocks={}
if not EMPTY:
    for key in ("client_logo", "brand_logo", "cover_photo"):
        block=ResolvedBlock(key, "Library", asset_hashes=("old.png",), references=("original-" + key,))
        blocks[key]=replace(block, client_reviewed_fingerprint=block.fingerprint)
    blocks["footer_text"]=ResolvedBlock("footer_text", "Library", text="Synthetic address")
    blocks["activity_summary"]=ResolvedBlock("activity_summary", "This month", text="Retained work.")
blocks=st.session_state.setdefault("blocks", blocks)
draft=ReportDraft(synthetic_profiles()[0], ReportPeriod(2026,9), "Synthetic Editor", (), tuple(blocks.values()))
st.session_state.blocks=render_cover(draft, blocks, "report_test", assets, _field, lambda ref:assets[ref])
'''.replace("EMPTY", repr(empty))).run()


def button(app, label):
    return next(v for v in app.button if v.label == label)


def test_cover_opens_with_current_content_and_no_change_or_review_questions(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Shared logo picker should stay closed")
    monkeypatch.setattr("app.monthly_report_branding_ui.offer_logo", unexpected)
    app = cover_app()
    original = dict(app.session_state.blocks)
    assert not app.exception
    assert not app.get("file_uploader") and not app.checkbox and not app.radio and not app.text_area
    assert {b.label for b in app.button} == {"Change cover photo", "Change logos", "Edit footer"}
    assert any("September 2026" in v.value for v in app.markdown)
    assert any("final page layout" in v.value for v in app.caption)
    app.run()
    assert app.session_state.blocks == original


def test_empty_cover_has_no_required_image_or_new_blocks_until_an_edit():
    app = cover_app(empty=True)
    assert not app.error and not app.warning and not app.exception
    assert not app.checkbox and not app.get("file_uploader")
    assert app.session_state.blocks == {}
    assert any("optional" in v.value for v in app.caption)
    button(app, "Change cover photo").click().run()
    assert app.session_state.blocks == {}


def test_replacing_photo_preserves_both_logos_and_unrelated_content(monkeypatch):
    incoming = {}
    real_upload = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw: incoming.get(label) or real_upload(label, *a, **kw))
    app = cover_app()
    original = dict(app.session_state.blocks)
    button(app, "Change cover photo").click().run()
    assert [v.label for v in app.get("file_uploader")] == ["New cover photo"]
    incoming["New cover photo"] = picture("green")
    app.run()
    button(app, "Use this cover photo").click().run()
    assert not app.exception
    edited = app.session_state.blocks
    assert edited["cover_photo"].asset_hashes != original["cover_photo"].asset_hashes
    assert edited["cover_photo"].references == ()
    assert edited["cover_photo"].client_reviewed_fingerprint == ""
    assert all(edited[k] == v for k, v in original.items() if k != "cover_photo")
    button(app, "Done with cover changes").click().run()
    assert not app.get("file_uploader")


def test_identical_replacement_retains_prior_approval_and_provenance():
    assets = {}
    block = ui.replace_cover_picture(ResolvedBlock("client_logo", "This month"), picture().getvalue(), ".png", assets)
    block = replace(block, references=("reviewed-source",))
    block = replace(block, client_reviewed_fingerprint=block.fingerprint)
    assert ui.replace_cover_picture(block, picture().getvalue(), ".png", assets) == block


def test_bad_replacement_leaves_existing_artwork_intact(monkeypatch):
    app = cover_app()
    original = dict(app.session_state.blocks)
    button(app, "Change cover photo").click().run()
    raw = BytesIO(b"not an image")
    raw.name, raw.size = "broken.png", len(raw.getvalue())
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **kw: raw)
    app.run()
    button(app, "Use this cover photo").click().run()
    assert not app.exception and app.error
    assert app.session_state.blocks == original


def test_remove_photo_is_explicit_and_footer_edits_keep_logos_reviewed():
    app = cover_app()
    original = dict(app.session_state.blocks)
    button(app, "Change cover photo").click().run()
    button(app, "Remove cover photo").click().run()
    assert app.session_state.blocks["cover_photo"].source == "Omit"
    assert app.session_state.blocks["cover_photo"].asset_hashes == ()
    button(app, "Edit footer").click().run()
    app.text_area[0].set_value("Updated synthetic address").run()
    assert app.session_state.blocks["footer_text"] == original["footer_text"]
    button(app, "Use footer text").click().run()
    assert app.session_state.blocks["footer_text"].text == "Updated synthetic address"
    assert app.session_state.blocks["client_logo"] == original["client_logo"]
    assert app.session_state.blocks["brand_logo"] == original["brand_logo"]


def test_shared_logo_choices_only_open_with_explicit_action(monkeypatch):
    calls = []
    monkeypatch.setattr("app.monthly_report_branding_ui.offer_logo", lambda block, *a: calls.append(block.key) or block)
    app = cover_app()
    assert calls == []
    button(app, "Change logos").click().run()
    assert calls == ["client_logo", "brand_logo"]
    assert [v.label for v in app.get("file_uploader")] == ["New client logo", "New ENFRA logo"]
    button(app, "Done with cover changes").click().run()
    assert not app.get("file_uploader")


def test_replacement_does_not_inherit_picture_approval_from_its_old_slot():
    from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
    assets = {}
    old = ui.replace_cover_picture(ResolvedBlock("cover_photo", "This month"), picture().getvalue(), ".png", assets)
    old = approve_all_assets(old)
    updated = ui.replace_cover_picture(old, picture("green").getvalue(), ".png", assets)
    assert pending_asset_indexes(updated) == (0,)
    assert updated.client_asset_reviews == ()
    assert pending_asset_indexes(old) == ()
