"""Novice import changes preserve named replacements and original chart pages."""
from io import BytesIO
import hashlib

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_section_ui as ui
from app import monthly_report_word_pages_ui as page_ui
from app.monthly_report_import import DocxInspection, ImportItem
from app.monthly_report_sections import build_section_import
from app.monthly_report_word_pages import WordPage


def picture(color="navy"):
    raw = BytesIO()
    Image.new("RGB", (400, 500), color).save(raw, "PNG")
    raw.name, raw.size = "synthetic.png", len(raw.getvalue())
    return raw


def app_for(section):
    return AppTest.from_string('''
import streamlit as st
from pathlib import Path
from app.monthly_report_import import ImportItem
from app.monthly_report_sections import ImportSection
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
items=(ImportItem("unsupported", "unsupported", "word/document.xml", 1, 2, SECTION),)
section=ImportSection(SECTION, "Synthetic section", items)
plans=st.session_state.setdefault("plans", {})
_section_card(section, Path("synthetic.docx"), None, ReportPeriod(2026,9), "report_novice", _field, plans, True)
'''.replace('SECTION', repr(section)), default_timeout=20).run()


def test_cover_uploads_are_named_retained_and_make_replacement_choice_possible(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    incoming = {}
    real_upload = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw: incoming.get(label) or real_upload(label, *a, **kw))
    app = app_for("cover")
    next(w for w in app.radio if w.label == "What would you like to do?").set_value("Edit text or change pictures").run()
    assert [w.label for w in app.get("file_uploader")] == ["New cover photograph"]
    incoming["New cover photograph"] = picture("green")
    app.run()
    next(w for w in app.radio if w.label.startswith("Some content could not")).set_value("I uploaded clear replacements").run()
    assert not app.error and not app.exception
    assert {slot for slot, _ in app.session_state["plans"]["cover"]["new_assets"]} == {"cover_photo"}
    incoming.clear()
    next(w for w in app.radio if w.label == "What would you like to do?").set_value("Keep and review").run()
    assert len(app.session_state["plans"]["cover"]["new_assets"]) == 1
    next(w for w in app.checkbox if w.label.startswith("This section is ready")).check().run()
    plan = app.session_state["plans"]["cover"]
    inspection = DocxInspection("synthetic", (ImportItem("unsupported", "unsupported", "word/document.xml", 1, 2, ""),), (), (), 2)
    mapped, _ = build_section_import("unused", inspection, (plan,))
    assert {block.key for block in mapped.blocks} == {"cover_photo"}


def test_kept_complete_chart_and_new_outage_picture_both_reach_saved_design(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = picture().getvalue()
    monkeypatch.setattr(page_ui, "preserve_word_pages", lambda *a: (WordPage(1, raw, 400, 500, "Synthetic organization chart", False),))
    incoming = {}
    real_upload = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw: incoming.get(label) or real_upload(label, *a, **kw))
    app = app_for("organization")
    next(w for w in app.button if w.label == "Show original chart pages").click().run()
    next(w for w in app.checkbox if w.label == "Use complete pages for this section").check().run()
    next(w for w in app.radio if w.label == "What would you like to do?").set_value("Edit text or change pictures").run()
    assert "New daytime outage procedure" in [w.label for w in app.get("file_uploader")]
    next(w for w in app.checkbox if w.label == "Include page 1").check().run()
    next(w for w in app.checkbox if w.label.startswith("Page 1 matches")).check().run()
    incoming["New daytime outage procedure"] = picture("green")
    app.run()
    incoming.clear()
    app.run()
    next(w for w in app.checkbox if w.label.startswith("This section is ready")).check().run()
    assert not app.exception and not app.error
    plan = app.session_state["plans"]["organization"]
    inspection = DocxInspection("synthetic", (ImportItem("unsupported", "unsupported", "word/document.xml", 1, 2, "organization"),), (), (), 2)
    mapped, _ = build_section_import("unused", inspection, (plan,))
    assert {block.key for block in mapped.blocks} == {"org_chart", "business_hours_workflow"}
    chart = next(block for block in mapped.blocks if block.key == "org_chart")
    assert chart.asset_hashes == (hashlib.sha256(raw).hexdigest() + ".png",)
    assert chart.references


def test_new_cover_logo_changes_only_that_picture_and_preserves_footer(monkeypatch):
    from app import monthly_report_sections as sections
    from app.monthly_report_docx import normalize_report_image
    old_image = normalize_report_image(picture().getvalue(), ".png", line_art=True)
    new_image = normalize_report_image(picture("green").getvalue(), ".png", line_art=True)
    monkeypatch.setattr(sections, "read_import_image", lambda *a, **kw: old_image)
    items = (ImportItem("logo", "image", "word/document.xml", 1, 1, "", suggested_slot="client_logo", image_part="word/media/logo.png"),
             ImportItem("footer", "text", "word/footer1.xml", 2, 1, "", suggested_slot="footer_text", text="Synthetic site address"))
    inspection = DocxInspection("synthetic", items, (), (), 1)
    plan = {"key": "cover", "target": "cover", "approved": True, "selected": ["logo", "footer"],
            "destinations": {"logo": "client_logo", "footer": "footer_text"}, "new_assets": [("client_logo", new_image)]}
    mapped, _ = build_section_import("unused", inspection, (plan,))
    logo = next(block for block in mapped.blocks if block.key == "client_logo")
    assert logo.asset_hashes == (hashlib.sha256(new_image.data).hexdigest() + "." + new_image.extension,)
    assert next(block for block in mapped.blocks if block.key == "footer_text").text == "Synthetic site address"


def test_import_cover_retains_identified_logos_without_manager_logo_choices():
    app = AppTest.from_string('''
import streamlit as st
from pathlib import Path
from app.monthly_report_import import ImportItem
from app.monthly_report_sections import ImportSection
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
items=tuple(ImportItem(slot, "image", "word/document.xml", 1, 1, "cover", suggested_slot=slot, image_part=slot+".png") for slot in ("brand_logo", "client_logo"))
plans=st.session_state.setdefault("plans", {})
_section_card(ImportSection("cover", "Cover", items), Path("unused.docx"), None, ReportPeriod(2026,9), "test", _field, plans, True)
''', default_timeout=20).run()
    assert not app.exception
    assert set(app.session_state["plans"]["cover"]["selected"]) == {"brand_logo", "client_logo"}
    assert not any(w.label == "Use this picture" for w in app.radio)
    next(w for w in app.radio if w.label == "What would you like to do?").set_value("Edit text or change pictures").run()
    assert [w.label for w in app.get("file_uploader")] == ["New cover photograph"]
    assert not any(w.label == "Use this picture" for w in app.radio)
