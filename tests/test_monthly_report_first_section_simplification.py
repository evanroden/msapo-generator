"""First-section simplification: explicit source evidence, one cover photo, no busywork.

No real customer data is used. Unknown source-site identity never authorizes
copying another site's work, and an omitted native object never bypasses
pricing or other output-safety checks.
"""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_import import DocxInspection, ImportItem
from app.monthly_report_model import Facility
from app.monthly_report_start_import import (
    cover_photo_candidates, source_sites, suggested_cover_photo,
)
from app import monthly_report_guided as guided
from app import monthly_report_section_ui as section_ui


def photo(name, width, height, *, slot="cover_photo", position=2):
    return ImportItem(name, "image", "word/document.xml", position, 1,
                      "cover", suggested_slot=slot, image_part=f"word/media/{name}.jpg",
                      image_width=width, image_height=height)


def test_cover_photo_defaults_to_unique_large_image_but_logs_not_a_choice():
    images = (photo("enfra-logo", 2600, 200, slot="brand_logo"),
              photo("building", 1600, 1200),
              photo("hospital-logo", 2400, 330, slot="client_logo"),
              photo("smaller", 500, 360))
    candidates = cover_photo_candidates(images)
    assert {item.id for item in candidates} == {"building", "smaller"}
    assert suggested_cover_photo(images).id == "building"
    ambiguous = (photo("equal-one", 1000, 800),
                 photo("equal-two", 1000, 800))
    assert suggested_cover_photo(ambiguous) is None
    assert suggested_cover_photo((photo("panoramic", 3000, 500, slot=""),)) is None
    # A panoramic photo remains visible as a manual option.
    assert cover_photo_candidates((photo("panoramic", 3000, 500, slot=""),))


def test_native_cover_paragraph_identifies_source_site_without_using_body():
    north = Facility("north", "United Memorial Medical Center", ("UMMC",))
    south = Facility("south", "Unity Specialty Hospital")
    inspection = DocxInspection("a" * 64, (
        ImportItem("title", "text", "word/document.xml", 8, 1, "cover",
                   text="United Memorial Medical Center"),
        ImportItem("activity", "text", "word/document.xml", 102, 7, "activity",
                   text="Unity Specialty Hospital pump service in July"),
    ), (), (), 7)
    assert source_sites(inspection, (north, south)) == (north,)
    no_cover = replace(inspection, items=(inspection.items[1],))
    assert source_sites(no_cover, (north, south)) == ()


def test_site_checkboxes_seed_only_names_observed_on_cover(monkeypatch):
    sites = (Facility("north", "United Memorial Medical Center"),
             Facility("south", "Unity Specialty Hospital"))
    monkeypatch.setattr(section_ui, "_site_options", lambda contract: sites)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_section_ui import _identity
from app.monthly_report_import import DocxInspection, ImportItem
from app.monthly_report_ui import _field
inspection=DocxInspection("a"*64, (ImportItem("title","text","word/document.xml",
    3,1,"cover",text="United Memorial Medical Center"),), (), (), 1)
profile, actor, missing=_identity("Synthetic Contract", "Synthetic Tester",
    "report_first", _field, None, inspection)
st.session_state["result_profile"] = profile
st.session_state["result_missing"] = missing
''', default_timeout=25).run()
    assert not app.exception
    assert not app.radio and not app.multiselect
    north = next(w for w in app.checkbox if w.label == "United Memorial Medical Center")
    south = next(w for w in app.checkbox if w.label == "Unity Specialty Hospital")
    assert north.value is True and south.value is False
    assert app.session_state["result_profile"].facilities == sites[:1]
    south.check().run()
    assert len(app.session_state["result_profile"].facilities) == 2
    assert app.session_state["result_profile"].scope_type == "multi_site"


def test_regular_sections_require_no_blanket_readiness_checkbox():
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_section_ui import _approve_plan
from app.monthly_report_ui import _field
plan = {"key": "activity", "selected": ["current"], "destinations": {"current":"activity_summary"}}
plans={}
_approve_plan(plan,"synthetic_review",_field,{},plans,[])
st.session_state["approved"] = plans["activity"]["approved"]
''').run()
    assert not app.exception
    assert app.session_state["approved"]
    assert not app.checkbox


def test_explicit_priced_vendor_quote_ack_cannot_override_blocker():
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_section_ui import _approve_plan
from app.monthly_report_ui import _field
plan={"key":"proposals", "selected":["quote"], "destinations":{}}
plans={}
_approve_plan(plan,"synthetic_price",_field,{},plans,
              ["A price was detected; remove it before including this page."],
              quote_price_risk=True)
st.session_state["approved"]=plans["proposals"]["approved"]
''').run()
    assert not app.exception
    assert len(app.checkbox) == 1
    assert not app.session_state["approved"]
    app.checkbox[0].check().run()
    assert not app.session_state["approved"]
    assert app.error


def test_no_redundant_cover_panel_and_cover_preview_stays_with_import():
    import inspect
    source = inspect.getsource(guided.render_guided_workflow)
    assert "render_cover(" not in source
    assert "monthly_cover_preview_sticky" in source
    assert "render_pending_cover_selection" in source
    assert "position:sticky" in source
    setup = inspect.getsource(section_ui.render_section_setup)
    assert 'st.button("Analyze report"' not in setup
    assert "st.file_uploader(\"Starting report\"" in setup
    assert "hashlib.sha256(upload.getvalue()).hexdigest()" in setup
    assert 'with st.expander("Cover photograph"' in setup
    assert '"This section is ready' not in inspect.getsource(section_ui._approve_plan)


def test_ummc_legacy_cover_abbreviation_prechecks_exact_site_once(monkeypatch, tmp_path):
    """Private September UMMC cover has 'UMMC', not a spelled-out legal name."""
    from app.contracts import RRH_CONTRACT
    from app.monthly_report_section_ui import _site_options
    from app.monthly_report_import import DocxInspection, ImportItem
    from app.monthly_report_start_import import source_sites
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    options = _site_options(RRH_CONTRACT)
    intended = next(f for f in options if f.key == "united_memorial")
    assert "UMMC" in intended.aliases
    assert len([f for f in options if f.key == intended.key]) == 1
    inspection = DocxInspection(
        "a" * 64,
        (ImportItem("cover", "text", "word/document.xml", 3, 1,
                    "cover", text="UMMC Operations and Maintenance Monthly Review"),
         ImportItem("body", "text", "word/document.xml", 125, 7,
                    "activity", text="Service coordination at Unity Hospital")),
        ("UMMC", "September 2026", "Operations and Maintenance Monthly Review"),
        (), 7,
    )
    assert source_sites(inspection, options) == (intended,)
    assert source_sites(DocxInspection(
        "a" * 64, (), ("Batavia",), (), 1), options) == ()
