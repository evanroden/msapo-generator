"""Source-specific issue evidence checkboxes and on-demand PDF thumbnails.

All files are synthetic; no genuine monthly reports or client references are
committed. The existing issue multiselect and its stale-edit receipt remain
the single authoritative way to commit supporting-page associations.
"""
from dataclasses import replace

import pymupdf as fitz
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportFollowUp, ReportPeriod, synthetic_profiles
from tests.test_monthly_report_issue_cards import draft_for


SCRIPT = """
import streamlit as st
from app.monthly_report_issues import render_issue_cards
from app.monthly_report_ui import _field
st.session_state["draft"] = render_issue_cards(
    st.session_state["draft"], "evidence_gallery", _field)
"""


def synthetic_pdf(name, pages=3, *, rotated=False):
    with fitz.open() as document:
        for n in range(1, pages + 1):
            page = document.new_page(width=792 if rotated else 612,
                                     height=612 if rotated else 792)
            page.insert_text((80, 90),
                f"Synthetic {name} inspection page {n}. Equipment review only.")
            page.draw_rect(fitz.Rect(30, 130, 105, 185), fill=(n / (pages + 1), 0.2, 0.7))
        return document.tobytes()


def setup_app(tmp_path, monkeypatch, *, missing=False):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    first_raw = synthetic_pdf("alpha", pages=5)
    second_raw = synthetic_pdf("beta", pages=2, rotated=True)
    alpha, _ = sources.ingest(profile, "alpha-equipment.pdf", first_raw)
    beta, _ = sources.ingest(profile, "beta-equipment.pdf", second_raw)
    a, b = alpha.source, beta.source
    first = ReportFollowUp(
        "pump", "issue", "Synthetic pump vibration.", "2026-09",
        update="Additional survey planned.", references=(sources.source_reference(a, 1),))
    second = ReportFollowUp(
        "valve", "issue", "Synthetic valve maintenance.", "2026-09",
        status="resolved", evidence_note="Reviewed the valve repair.",
        references=(sources.source_reference(b, 2),))
    draft = replace(draft_for(""), sources=(a, b), follow_ups=(first, second))
    if missing:
        sources._path(profile, a.sha256, a.suffix).unlink()
    app = AppTest.from_string(SCRIPT, default_timeout=20)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    return app, (a, b), (first_raw, second_raw)


def gallery_checkbox(app, label):
    return next(item for item in app.checkbox if item.label == label)


def preview_button(app, label):
    return next(item for item in app.button if item.label == label)


def gallery_file_choice(app):
    return next(item for item in app.selectbox if item.label == "Source file to inspect")


def test_repeated_page_numbers_are_distinct_and_choices_keep_other_issues(tmp_path, monkeypatch):
    app, (alpha, beta), originals = setup_app(tmp_path, monkeypatch)
    start = app.session_state["draft"]
    assert gallery_checkbox(app, "Include alpha-equipment.pdf · page 1 as issue evidence").value
    assert not gallery_checkbox(app, "Include alpha-equipment.pdf · page 2 as issue evidence").value
    assert len([item for item in app.multiselect if item.label == "Supporting source pages"]) == 2
    gallery_checkbox(app, "Include alpha-equipment.pdf · page 2 as issue evidence").set_value(True).run()
    assert not app.exception
    updated = app.session_state["draft"]
    assert updated.follow_ups[0].references == (
        sources.source_reference(alpha, 1), sources.source_reference(alpha, 2))
    assert updated.follow_ups[1] == start.follow_ups[1]
    assert updated.sources == start.sources
    app.run()
    assert gallery_checkbox(app, "Include alpha-equipment.pdf · page 2 as issue evidence").value

    gallery_file_choice(app).set_value(beta.id).run()
    assert not app.exception
    assert not gallery_checkbox(app, "Include beta-equipment.pdf · page 1 as issue evidence").value
    gallery_checkbox(app, "Include beta-equipment.pdf · page 1 as issue evidence").set_value(True).run()
    final = app.session_state["draft"]
    assert final.follow_ups[0].references == (
        sources.source_reference(alpha, 1), sources.source_reference(alpha, 2),
        sources.source_reference(beta, 1))
    assert final.follow_ups[1] == start.follow_ups[1]
    assert sources.source_bytes(final.profile, alpha) == originals[0]
    assert sources.source_bytes(final.profile, beta) == originals[1]


def test_page_range_and_on_demand_preview_are_bound_to_correct_original(tmp_path, monkeypatch):
    app, (alpha, beta), originals = setup_app(tmp_path, monkeypatch)
    before = app.session_state["draft"]
    # First render has not decoded any preview. Only explicit Preview does.
    assert not list(tmp_path.rglob("*-preview.json"))
    ranges = [item for item in app.selectbox if item.label == "Pages to review"]
    assert ranges
    ranges[0].set_value(4).run()
    assert not app.exception
    assert gallery_checkbox(app, "Include alpha-equipment.pdf · page 5 as issue evidence")
    preview_button(app, "Preview alpha-equipment.pdf · page 5").click().run()
    assert not app.exception
    assert any("alpha-equipment.pdf · page 5 · Preview only" in caption.value
               for caption in app.get("caption"))
    assert app.session_state["draft"] == before
    gallery_file_choice(app).set_value(beta.id).run()
    preview_button(app, "Preview beta-equipment.pdf · page 1").click().run()
    assert not app.exception
    assert any("beta-equipment.pdf · page 1 · Preview only" in caption.value
               for caption in app.get("caption"))
    assert sources.source_bytes(before.profile, alpha) == originals[0]
    assert sources.source_bytes(before.profile, beta) == originals[1]


def test_missing_original_keeps_selection_and_warns_without_rewriting(tmp_path, monkeypatch):
    app, (alpha, beta), originals = setup_app(tmp_path, monkeypatch, missing=True)
    before = app.session_state["draft"]
    preview_button(app, "Preview alpha-equipment.pdf · page 1").click().run()
    assert not app.exception
    assert app.session_state["draft"] == before
    assert any("Preview unavailable for alpha-equipment.pdf" in item.value for item in app.warning)
    assert sources.source_bytes(before.profile, beta) == originals[1]


def test_stale_gallery_checkbox_does_not_retarget_a_new_month(tmp_path, monkeypatch):
    app, (alpha, beta), _ = setup_app(tmp_path, monkeypatch)
    old = app.session_state["draft"]
    # A stale native checkbox from September arrives after another report
    # period replaced its row; the existing callback journal must reject it.
    current = replace(old, period=ReportPeriod(2026, 10),
                      follow_ups=tuple(replace(item, carried_from="2026-10")
                                       for item in old.follow_ups))
    app.session_state["draft"] = current
    gallery_checkbox(app, "Include alpha-equipment.pdf · page 3 as issue evidence").set_value(True).run()
    assert not app.exception
    assert app.session_state["draft"].follow_ups[0].references == old.follow_ups[0].references
    assert app.session_state["draft"].follow_ups[1].references == old.follow_ups[1].references
