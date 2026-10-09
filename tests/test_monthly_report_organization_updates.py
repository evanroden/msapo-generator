"""Change one organization part while retaining the rest of the report."""

import hashlib
from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_visual_ui as visual_ui
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_import import DocxInspection, ImportItem
from app.monthly_report_sections import build_section_import


def picture(color="navy"):
    raw = BytesIO()
    Image.new("RGB", (400, 300), color).save(raw, "PNG")
    raw.name, raw.size = "contacts.png", len(raw.getvalue())
    return raw


def contact_app():
    return AppTest.from_string('''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_model import BlockSpec, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
from app.monthly_report_visual_ui import edit_contacts
raw=BytesIO(); Image.new("RGB", (120,120), "navy").save(raw, "PNG")
assets=st.session_state.setdefault("assets", {"first.png":raw.getvalue(), "second.png":raw.getvalue()})
contacts=ResolvedBlock("contact_matrix", "Library", asset_hashes=("first.png", "second.png"), asset_captions=("First page", "Second page"), references=("source-first", "source-second"), client_reviewed_fingerprint="old-review")
chart=ResolvedBlock("org_chart", "Library", text="Existing organization chart")
initial=replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026,9)), blocks=(chart, contacts))
st.session_state.setdefault("original", initial)
draft=st.session_state.setdefault("report_contacts_draft", initial)
current=next(b for b in draft.blocks if b.key=="contact_matrix")
changed=edit_contacts(draft, BlockSpec("contact_matrix", "image_page"), current, "report_contacts", assets, _field)
st.session_state["report_contacts_draft"]=replace(draft, blocks=tuple(changed if b.key==changed.key else b for b in draft.blocks))
''').run()


def contact_block(app):
    return next(b for b in app.session_state["report_contacts_draft"].blocks if b.key == "contact_matrix")


def test_uploaded_contacts_show_all_pages_and_remove_only_selected_page():
    app = contact_app()
    assert not app.exception
    assert "View or change saved contact pages" in [e.label for e in app.expander]
    assert "Replacement facility contact page" in [w.label for w in app.get("file_uploader")]
    assert {b.label for b in app.button} >= {"Remove picture 1", "Remove picture 2"}
    next(b for b in app.button if b.label == "Remove picture 1").click().run()
    app.run()
    block = contact_block(app)
    assert block.asset_hashes == ("second.png",)
    assert block.asset_captions == ("Second page",)
    assert block.references == ("source-second",)
    assert not block.client_reviewed_fingerprint
    assert app.session_state["original"].blocks[1].asset_hashes == ("first.png", "second.png")
    assert app.session_state["report_contacts_draft"].blocks[0] == app.session_state["original"].blocks[0]


def test_contact_image_replacement_persists_and_does_not_change_org_chart(monkeypatch):
    incoming = {}
    real_upload = visual_ui.st.file_uploader
    monkeypatch.setattr(visual_ui.st, "file_uploader", lambda label, *a, **kw: incoming.get(label) or real_upload(label, *a, **kw))
    app = contact_app()
    incoming["Replacement facility contact page"] = picture("green")
    app.run()
    next(b for b in app.button if b.label == "Use this contact page").click().run()
    incoming.clear()
    app.run()
    block = contact_block(app)
    assert not app.exception
    assert len(block.asset_hashes) == 1 and block.asset_hashes[0] not in ("first.png", "second.png")
    assert block.asset_hashes[0] in app.session_state["assets"]
    assert not block.references and not block.asset_captions and not block.client_reviewed_fingerprint
    assert app.session_state["report_contacts_draft"].blocks[0] == app.session_state["original"].blocks[0]
    assert "first.png" in app.session_state["assets"]  # Existing originals remain available.


def test_invalid_contact_image_retains_current_pages(monkeypatch):
    incoming = {}
    real_upload = visual_ui.st.file_uploader
    monkeypatch.setattr(visual_ui.st, "file_uploader", lambda label, *a, **kw: incoming.get(label) or real_upload(label, *a, **kw))
    app = contact_app()
    invalid = BytesIO(b"not a valid image")
    invalid.name, invalid.size = "invalid.png", len(invalid.getvalue())
    incoming["Replacement facility contact page"] = invalid
    app.run()
    next(b for b in app.button if b.label == "Use this contact page").click().run()
    assert not app.exception
    assert any("current pages are retained" in e.value for e in app.error)
    assert contact_block(app).asset_hashes == ("first.png", "second.png")


def test_named_organization_replacement_preserves_native_text_and_other_parts(monkeypatch):
    from app import monthly_report_sections as sections

    original = normalize_report_image(picture().getvalue(), ".png", line_art=True)
    replacement = normalize_report_image(picture("green").getvalue(), ".png", line_art=True)
    monkeypatch.setattr(sections, "read_import_image", lambda *a, **kw: original)
    items = (
        ImportItem("chart", "image", "word/document.xml", 1, 1, "organization", "org_chart", image_part="word/media/chart.png"),
        ImportItem("procedure", "image", "word/document.xml", 2, 1, "organization", "after_hours_workflow", image_part="word/media/procedure.png"),
        ImportItem("note", "text", "word/document.xml", 3, 1, "organization", "org_chart", text="Reporting lines confirmed with the site manager."),
    )
    inspection = DocxInspection("synthetic", items, (), (), 1)
    plan = {"key": "organization", "target": "organization", "approved": True,
            "selected": [i.id for i in items], "new_assets": [("org_chart", replacement)]}
    mapped, _ = build_section_import("unused", inspection, (plan,))
    chart = next(b for b in mapped.blocks if b.key == "org_chart")
    procedure = next(b for b in mapped.blocks if b.key == "after_hours_workflow")
    assert chart.asset_hashes == (hashlib.sha256(replacement.data).hexdigest() + ".png",)
    assert chart.text == items[2].text and chart.references == ("docx:synthetic:note",)
    assert procedure.asset_hashes == (hashlib.sha256(original.data).hexdigest() + ".png",)
    assert procedure.references == ("docx:synthetic:procedure",)


def test_named_chart_replacement_replaces_all_preserved_chart_pages_only():
    images = [normalize_report_image(picture(color).getvalue(), ".png", line_art=True)
              for color in ("navy", "red", "green", "yellow")]
    preserved = list(zip(("org_chart", "org_chart", "business_hours_workflow"), images[:3]))
    records = [{"page": n, "slot": slot, "sections": (1,), "sha256": hashlib.sha256(image.data).hexdigest(),
                "text": "Current staffing and operations", "blank": False, "reviewed": True}
               for n, (slot, image) in enumerate(preserved, 1)]
    inspection = DocxInspection("synthetic", (), (), (), 1)
    plan = {"key": "organization", "target": "organization", "approved": True, "page_layout": True,
            "preserved_assets": preserved, "word_page_records": records,
            "new_assets": [("org_chart", images[3])]}
    mapped, _ = build_section_import("unused", inspection, (plan,))
    chart = next(b for b in mapped.blocks if b.key == "org_chart")
    procedure = next(b for b in mapped.blocks if b.key == "business_hours_workflow")
    assert chart.asset_hashes == (hashlib.sha256(images[3].data).hexdigest() + ".png",)
    assert not chart.references
    assert procedure.asset_hashes == (hashlib.sha256(images[2].data).hexdigest() + ".png",)
    assert procedure.references == ("docx:synthetic:word-sections:1:page:3",)
