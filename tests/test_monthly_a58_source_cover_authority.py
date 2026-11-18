"""A58: authoritative cover provenance, with synthetic physical page boundaries."""
from dataclasses import replace
from io import BytesIO

from docx import Document
from streamlit.testing.v1 import AppTest

from app.monthly_report_import import inspect_docx, imported_draft
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_start_import import (
    analyze_starting_report, automatic_section_plans, build_starting_import,
    cover_report_periods,
)

TARGET = ReportPeriod(2026, 9)


def fixture(tmp_path, *, title, report_month="September 2026", note="", work="",
            extra_cover_month=""):
    path = tmp_path / "source.docx"
    document = Document()
    document.add_heading(title, 0)
    document.add_paragraph("Monthly Report " + report_month)
    if extra_cover_month:
        document.add_paragraph("Monthly Report " + extra_cover_month)
    document.add_page_break()
    if note:
        document.add_paragraph(note)
    document.add_heading("1 Organizational Chart", 1)
    contacts = document.add_table(rows=2, cols=2)
    contacts.cell(0, 0).text = "Role"
    contacts.cell(0, 1).text = "Name"
    contacts.cell(1, 0).text = "Site lead"
    contacts.cell(1, 1).text = "Synthetic Source Contact"
    document.add_heading("2 Monthly Activity Summary", 1)
    for paragraph in (work if isinstance(work, (tuple, list))
                      else (work or "Undated work not yet completed.",)):
        document.add_paragraph(paragraph)
    document.save(path)
    return path


def draft_from(path, profile, known=(), *, confirmed_period=None):
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(
        inspection, profile, TARGET, known, confirmed_period=confirmed_period)
    plans = automatic_section_plans(inspection, analysis)
    mapped, _ = build_starting_import(path, inspection, plans.values())
    draft = imported_draft(profile, TARGET, "Synthetic Editor", mapped)
    return inspection, analysis, draft, plans


def test_auth01_previous_month_same_site_uses_current_dated_work_without_old_completion(tmp_path):
    profile = synthetic_profiles()[0]
    path = fixture(tmp_path, title=profile.facilities[0].title, report_month="August 2026",
                   note="Other facilities are discussed on the following page.",
                   work=("August 2026 maintenance completed.",
                         "September 2026 pump follow-up completed."))
    raw = path.read_bytes()
    inspection, analysis, draft, _ = draft_from(path, profile)
    assert inspection.cover_title_candidates == (profile.facilities[0].title, "Monthly Report August 2026")
    assert analysis.site_relation == "same" and analysis.source_period == (2026, 8)
    assert analysis.current_items and analysis.older_items
    activity = next(b for b in draft.blocks if b.key == "activity_summary")
    assert "September 2026 pump follow-up" in activity.text
    assert "August 2026 maintenance completed" not in activity.text
    assert next(b for b in draft.blocks if b.key == "contact_matrix").extra_tables[0].rows
    assert path.read_bytes() == raw


def test_auth02_other_site_same_contract_never_copies_contacts_or_completed_status(tmp_path):
    north, south = synthetic_profiles()[1].facilities
    target = synthetic_profiles()[0]
    path = fixture(tmp_path, title=south.title,
                   note="North: " + north.title + " was mentioned in an appendix.",
                   work="September 2026: South site PM work completed.")
    inspection, analysis, draft, plans = draft_from(path, target, (north, south))
    assert analysis.site_relation == "other" and analysis.source_sites == (south,)
    assert north.title not in inspection.cover_title_candidates
    assert draft.profile.facilities == (north,)
    assert all(not b.text and not b.rows and not b.asset_hashes
               and not any(t.rows for t in b.extra_tables) for b in draft.blocks)
    assert all(p["approved"] for p in plans.values())


def test_auth03_incomplete_current_month_keeps_partial_actual_work_and_undated_notes(tmp_path):
    profile = synthetic_profiles()[0]
    path = fixture(tmp_path, title=profile.facilities[0].title,
                   work="September 2026 pump repair completed. Pending balance test.")
    _, analysis, draft, _ = draft_from(path, profile)
    assert analysis.site_relation == "same" and analysis.source_period == (2026, 9)
    activity = next(b for b in draft.blocks if b.key == "activity_summary")
    assert "pump repair completed" in activity.text and "Pending balance test" in activity.text


def test_foreign_site_on_later_unheaded_page_never_becomes_a_cover_site(tmp_path):
    north, south = synthetic_profiles()[1].facilities
    target = synthetic_profiles()[0]
    path = fixture(tmp_path, title=north.title,
                   note=south.title + " is an external reference. " + south.title + " only.",
                   work="September 2026 North inspection completed.")
    inspection, analysis, draft, _ = draft_from(path, target, (north, south))
    assert analysis.site_relation == "same" and analysis.source_sites == (north,)
    assert south.title not in inspection.cover_title_candidates
    assert any(south.title in item.text for item in inspection.items)
    assert "North inspection completed" in next(b.text for b in draft.blocks if b.key == "activity_summary")


def test_unknown_site_with_only_body_alias_is_not_approved(tmp_path):
    profile = synthetic_profiles()[0]
    path = fixture(tmp_path, title="Unidentified source location",
                   note="Maintenance appendix references " + profile.facilities[0].title,
                   work="September 2026 repair completed.")
    inspection, analysis, draft, plans = draft_from(path, profile)
    assert analysis.site_relation == "unknown" and analysis.source_sites == ()
    # Empty column headings may survive as design; no source rows or site
    # activity/contacts can become approved target-site content.
    assert all(not b.text and not b.rows and not b.asset_hashes
               and not any(t.rows for t in b.extra_tables) for b in draft.blocks)
    assert all("Unidentified" in title or "Monthly Report" in title
               for title in inspection.cover_title_candidates)


def test_foreign_site_unverified_brand_logo_is_not_cross_site_design():
    from app.monthly_report_import import DocxInspection, ImportItem
    from app.monthly_report_start_import import StartingReportAnalysis

    unverified = ImportItem(
        "unverified-logo", "image", "word/document.xml", 2, 1, "cover",
        "brand_logo", image_part="word/media/fake.png", image_digest="a" * 64)
    inspection = DocxInspection("b" * 64, (unverified,), (), (), 1,
                                cover_title_candidates=("Synthetic South",))
    analysis = StartingReportAnalysis((), "other", (), (), ())
    plans = automatic_section_plans(inspection, analysis)
    assert unverified.id not in plans["cover"]["selected"]
    assert not any(unverified.id in p.get("automatic_logo_skips", {}).get("brand_logo", ())
                   for p in plans.values())


def test_standalone_cover_month_is_authority_but_issue_date_is_not(tmp_path):
    profile = synthetic_profiles()[0]
    for title in ("Sept 2026", "09/2026", "September 2026"):
        path = fixture(tmp_path, title=profile.facilities[0].title)
        source = Document(path)
        source.paragraphs[1].text = title
        source.save(path)
        assert cover_report_periods(inspect_docx(path)) == ((2026, 9),)
    path = fixture(tmp_path, title=profile.facilities[0].title)
    source = Document(path)
    source.paragraphs[1].text = "Issued Date: September 11, 2026"
    source.save(path)
    assert cover_report_periods(inspect_docx(path)) == ()


def test_two_conflicting_report_month_titles_demand_one_source_bound_choice(tmp_path):
    profile = synthetic_profiles()[0]
    path = fixture(tmp_path, title=profile.facilities[0].title,
                   report_month="August 2026", extra_cover_month="September 2026",
                   work="August 2026 old completed work.")
    inspection = inspect_docx(path)
    assert cover_report_periods(inspection) == ((2026, 8), (2026, 9))
    analysis = analyze_starting_report(inspection, profile, TARGET)
    assert analysis.source_period is None
    assert analyze_starting_report(inspection, profile, TARGET,
                                  confirmed_period=(2026, 8)).source_period == (2026, 8)
    try:
        analyze_starting_report(inspection, profile, TARGET, confirmed_period=(2026, 7))
    except ValueError as exc:
        assert "not on this original cover" in str(exc)
    else:
        raise AssertionError("Unlisted month must not authorize report work")


APP = """
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_source_sites_ui import choose_source_report_month
p = synthetic_profiles()[0]
scope = st.selectbox("Current report", ("September", "October"))
inspection = SimpleNamespace(
    sha256="f" * 64,
    title_candidates=("Monthly Report August 2026", "Monthly Report September 2026"),
    cover_title_candidates=("Monthly Report August 2026", "Monthly Report September 2026"))
result, pending = choose_source_report_month(
    inspection, p, ReportPeriod(2026, 9 if scope == "September" else 10),
    "a58", lambda key, value: key)
st.session_state["source_period"] = result
st.session_state["source_month_pending"] = pending
"""


def test_one_source_month_choice_and_target_change_clears_old_receipt():
    app = AppTest.from_string(APP).run()
    assert not app.exception and app.session_state["source_month_pending"]
    choice = next(s for s in app.selectbox if s.label == "Reporting month shown by the uploaded source cover")
    choice.set_value((2026, 8)).run()
    assert app.session_state["source_period"] == (2026, 8)
    app.selectbox[0].set_value("October").run()
    assert app.session_state["source_month_pending"] and app.session_state["source_period"] is None
