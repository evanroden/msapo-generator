"""Valid independently saved site requirements remain usable together.

Public saves create synthetic records. AppTest delivers native editor deltas;
it is not browser acceptance. DOCX checks inspect actual generated cells, and
the PDF test requires the existing LibreOffice capability gate.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_training as training
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock,
    default_sections,
)
from app.monthly_report_setup import new_month_draft
from tests.conftest import requires_libreoffice


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    return ReportProfile("Synthetic Training Identity", "combined", "Synthetic combined report",
        (Facility("north", "Synthetic North"), Facility("south", "Synthetic South")), "multi_site")


def _save_site(profile, site_index, columns, rows, *, year=2026, revision=0):
    site = profile.facilities[site_index]
    selected = replace(profile, facilities=(site,), scope_type="individual")
    reference = training.MATRIX_REF if year is None else training.year_matrix_reference(year)
    table = ReportTable(("Team member", "Site", *columns),
        tuple((name, site.title, *values) for name, *values in rows), reference)
    return training.save_training(selected, table, expected_revision=revision, actor="Synthetic Reviewer")


def _save_pair(profile, headings=("Fire Safety", "fire safety"), *, year=2026,
               statuses=("Completed", "Pending"), revision=0):
    _save_site(profile, 0, (headings[0],), (("North Learner", statuses[0]),), year=year, revision=revision)
    return _save_site(profile, 1, (headings[1],), (("South Learner", statuses[1]),),
                      year=year, revision=revision + 1)


def _seed(profile, stored, year=2026):
    return training.seed_matrix(profile, ResolvedBlock("training_summary", "This month"), stored, year=year)


def _history():
    return {path: path.read_bytes() for path in library._root().rglob("history/*.json")}


def _unchanged(history):
    assert all(path.read_bytes() == raw for path, raw in history.items())


def _report(profile, matrix=None, *, period=ReportPeriod(2026, 11), notes="", events=None):
    section = next(section for section in default_sections() if section.key == "training")
    block = training.apply_tables(ResolvedBlock("training_summary", "This month", text=notes), matrix, events)
    return ReportDraft(profile, period, "Synthetic Reviewer", (section,), (block,))


@pytest.mark.parametrize("second", ["fire safety", " Fire  Safety ", "FIRE SAFETY"])
@pytest.mark.parametrize("year", [None, 2026])
def test_independent_valid_site_saves_share_requirement_identity(profile, second, year):
    stored = _save_pair(profile, ("Fire Safety", second), year=year)
    history = _history()
    matrix = _seed(profile, stored, year)
    assert matrix.columns == ("Team member", "Site", "Fire Safety")
    assert matrix.rows == (("North Learner", "Synthetic North", "Completed"),
                           ("South Learner", "Synthetic South", "Pending"))
    assert training.load_training(profile.contract) == stored
    _unchanged(history)


def test_each_person_site_status_and_missing_course_remains_independent(profile):
    _save_site(profile, 0, ("Fire Safety", "Lockout"),
        (("Shared Name", "Completed", ""), ("North Colleague", "Not required", "Completed")))
    stored = _save_site(profile, 1, (" fire  safety ", "Orientation"),
        (("Shared Name", "Pending", "Not recorded"), ("South Colleague", "", "Not required")), revision=1)
    matrix = _seed(profile, stored)
    assert matrix.columns == ("Team member", "Site", "Fire Safety", "Lockout", "Orientation")
    assert matrix.rows == (
        ("Shared Name", "Synthetic North", "Completed", "", "Not recorded"),
        ("North Colleague", "Synthetic North", "Not required", "Completed", "Not recorded"),
        ("Shared Name", "Synthetic South", "Pending", "Not recorded", "Not recorded"),
        ("South Colleague", "Synthetic South", "", "Not recorded", "Not required"),
    )
    assert training.load_training(profile.contract) == stored


def test_course_wording_and_punctuation_do_not_become_aliases(profile):
    _save_site(profile, 0, ("Fire Safety", "Fire-Safety"), (("North Learner", "Completed", "Pending"),))
    stored = _save_site(profile, 1, ("Fire Safety (annual)",), (("South Learner", "Not required"),), revision=1)
    matrix = _seed(profile, stored)
    assert matrix.columns[2:] == ("Fire Safety", "Fire-Safety", "Fire Safety (annual)")
    assert matrix.rows[0][2:] == ("Completed", "Pending", "Not recorded")
    assert matrix.rows[1][2:] == ("Not recorded", "Not recorded", "Not required")


def test_display_order_follows_selected_sites_without_reassigning_values(profile):
    stored = _save_pair(profile)
    reversed_profile = replace(profile, facilities=tuple(reversed(profile.facilities)))
    matrix = _seed(reversed_profile, stored)
    assert matrix.columns == ("Team member", "Site", "fire safety")
    assert matrix.rows == (("South Learner", "Synthetic South", "Pending"),
                           ("North Learner", "Synthetic North", "Completed"))


def test_explicit_year_change_reuses_exact_saved_year_and_preserves_prior_report(profile):
    prior = ReportTable(("Team member", "Site", "Old requirement"),
        (("North Learner", "Synthetic North", "Completed"),
         ("South Learner", "Synthetic South", "")), training.year_matrix_reference(2026))
    stored = _save_pair(profile, ("Fire Safety", " FIRE   SAFETY "), year=2027,
                        statuses=("Not required", "Pending"))
    history = _history()
    chosen = training.matrix_for_year(profile, prior, stored, 2027)
    assert chosen.reference == training.year_matrix_reference(2027)
    assert chosen.columns == ("Team member", "Site", "Fire Safety")
    assert tuple(row[-1] for row in chosen.rows) == ("Not required", "Pending")
    assert prior.columns[-1] == "Old requirement"
    assert tuple(row[-1] for row in prior.rows) == ("Completed", "")
    assert training.load_training(profile.contract) == stored
    _unchanged(history)


def test_unsaved_new_year_resets_nonblank_statuses_and_ignores_future_year(profile):
    _save_pair(profile, statuses=("Completed", ""))
    stored = _save_site(profile, 0, ("Future-only requirement",), (("Future Learner", "Completed"),),
                        year=2028, revision=2)
    matrix = _seed(profile, stored, 2027)
    assert matrix.reference == training.year_matrix_reference(2027)
    assert matrix.columns == ("Team member", "Site", "Fire Safety")
    assert matrix.rows == (("North Learner", "Synthetic North", "Not recorded"),
                           ("South Learner", "Synthetic South", ""))
    assert training.load_training(profile.contract) == stored


def test_exact_year_for_one_site_does_not_reuse_old_completion_at_other_site(profile):
    _save_pair(profile, statuses=("Completed", "Pending"))
    stored = _save_site(profile, 0, (" FIRE  SAFETY ",), (("North Learner", "Not required"),),
                        year=2027, revision=2)
    matrix = _seed(profile, stored, 2027)
    assert len(matrix.columns) == 3
    assert tuple(row[-1] for row in matrix.rows) == ("Not required", "Not recorded")
    assert matrix.reference == training.year_matrix_reference(2027)
    assert training.load_training(profile.contract) == stored


def test_legacy_year_stays_unknown_and_future_year_cannot_relabel_it(profile):
    _save_pair(profile, year=None)
    stored = _save_site(profile, 0, ("Future-only requirement",), (("Future Learner", "Completed"),),
                        year=2028, revision=2)
    matrix = _seed(profile, stored, 2027)
    assert matrix.reference == training.MATRIX_REF
    assert matrix.columns == ("Team member", "Site", "Fire Safety")
    assert tuple(row[-1] for row in matrix.rows) == ("Completed", "Pending")
    assert training.load_training(profile.contract) == stored


def test_report_pinned_matrix_is_not_rewritten_by_shared_heading_normalization(profile):
    stored = _save_pair(profile)
    pinned = ReportTable(("Team member", "Site", "REPORT-only safety"),
        (("Report Learner", "Synthetic North", "Not required"),), training.year_matrix_reference(2026))
    block = ResolvedBlock("training_summary", "This month", extra_tables=(pinned,))
    assert training.seed_matrix(profile, block, stored, year=2027) == pinned
    assert training.matrix_for_year(profile, pinned, stored, 2026) == pinned
    report = _report(profile, pinned)
    saved = library.save_snapshot(report, expected_revision=0)
    assert new_month_draft(report, ReportPeriod(2027, 1)).blocks[0].extra_tables == (pinned,)
    assert library.load_snapshot(profile.contract, profile.key, report.period) == saved


def test_unselected_site_columns_are_neither_loaded_nor_validated(profile):
    stored = _save_pair(profile)
    altered = deepcopy(stored)
    altered["years"]["2026"]["sites"]["south"] = {
        "columns": ["Site", "SITE"], "rows": [["Unselected Learner", "Completed", "Pending"]]}
    selected = replace(profile, facilities=profile.facilities[:1], scope_type="individual")
    matrix = _seed(selected, altered)
    assert matrix.columns == ("Team member", "Site", "Fire Safety")
    assert matrix.rows == (("North Learner", "Synthetic North", "Completed"),)
    assert training.load_training(profile.contract) == stored


@pytest.mark.parametrize("columns", [("Fire Safety", "fire  safety"), ("Fire Safety", "Fire Safety"), (" SITE ",)])
@pytest.mark.parametrize("entry", ["legacy", "annual", "year_switch"])
def test_invalid_same_site_columns_are_not_silently_combined(profile, columns, entry):
    year = None if entry == "legacy" else 2026
    stored = _save_pair(profile, year=year)
    altered = deepcopy(stored)
    sites = altered["sites"] if year is None else altered["years"][str(year)]["sites"]
    sites["north"] = {"columns": list(columns),
                       "rows": [["North Learner", *("Completed" for _ in columns)]]}
    selected = replace(profile, facilities=profile.facilities[:1], scope_type="individual")
    with pytest.raises(ValueError, match="(?i)(unique|heading|requirement)"):
        if entry == "year_switch":
            prior = ReportTable(("Team member", "Site"), (), training.year_matrix_reference(2025))
            training.matrix_for_year(selected, prior, altered, 2026)
        else:
            _seed(selected, altered, year)
    assert training.load_training(profile.contract) == stored


def test_fifty_equivalent_courses_fit_the_existing_course_limit(profile):
    courses = tuple(f"Safety course {index:02}" for index in range(50))
    _save_site(profile, 0, courses, (("North Learner", *("Completed" for _ in courses)),))
    stored = _save_site(profile, 1, tuple(title.upper() for title in courses),
        (("South Learner", *("Pending" for _ in courses)),), revision=1)
    matrix = _seed(profile, stored)
    assert matrix.columns[2:] == courses
    assert matrix.rows[0][2:] == ("Completed",) * 50
    assert matrix.rows[1][2:] == ("Pending",) * 50


def test_fifty_one_distinct_courses_still_exceed_the_existing_limit(profile):
    courses = tuple(f"Safety course {index:02}" for index in range(50))
    _save_site(profile, 0, courses, (("North Learner", *("Completed" for _ in courses)),))
    stored = _save_site(profile, 1, ("Additional course",), (("South Learner", "Pending"),), revision=1)
    with pytest.raises(ValueError, match="50 trainings"):
        _seed(profile, stored)
    assert training.load_training(profile.contract) == stored


@pytest.mark.parametrize("south_count", [250, 251])
def test_combined_team_member_limit_is_unchanged(profile, south_count):
    _save_site(profile, 0, ("Safety",), tuple((f"North Learner {index}", "Completed") for index in range(250)))
    stored = _save_site(profile, 1, ("Safety",),
        tuple((f"South Learner {index}", "Pending") for index in range(south_count)), revision=1)
    if south_count == 251:
        with pytest.raises(ValueError, match="500 team members"):
            _seed(profile, stored)
    else:
        assert len(_seed(profile, stored).rows) == 500


APP = '''
import streamlit as st
from app.monthly_report_training_ui import render_training
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state['blocks'] = render_training(
    st.session_state['draft'], st.session_state['blocks'], 'requirement_identity', field)
'''


def _open_app(report):
    app = AppTest.from_string(APP, default_timeout=25)
    app.session_state["draft"] = report
    app.session_state["blocks"] = {block.key: block for block in report.blocks}
    return app.run()


def _working_report(app):
    return replace(app.session_state["draft"], blocks=tuple(app.session_state["blocks"].values()))


def test_native_editor_edit_save_reopen_rerun_and_rollover_keep_status_ownership(profile):
    stored = _save_pair(profile)
    history = _history()
    period = ReportPeriod(2026, 11)
    event = training.add_event(None, title="Synthetic briefing", when=date(2026, 11, 3),
        mode="Virtual", participants=["North Learner"], hours="", period=period)
    app = _open_app(_report(profile, period=period, notes="Original monthly note", events=event))
    assert not app.exception and not app.error
    assert training.load_training(profile.contract) == stored
    first = _working_report(app)
    saved_before = library.save_snapshot(first, expected_revision=0)
    grid = next(grid for grid in app.dataframe if "_grid_" in grid.key)
    assert list(grid.value.columns) == ["Team member", "Site", "Fire Safety"]
    assert list(grid.value["Fire Safety"]) == ["Completed", "Pending"]
    # Deliver the native data_editor edit packet, without replacing the grid
    # renderer or save function. Row 1 is the South learner only.
    app.session_state[grid.key] = {
        "edited_rows": {1: {"Fire Safety": "Not required"}}, "added_rows": [], "deleted_rows": []}
    next(widget for widget in app.text_area if widget.label == "Training notes").set_value("Human monthly correction").run()
    assert not app.exception and not app.error
    edited = _working_report(app)
    matrix = next(table for table in edited.blocks[0].extra_tables if training.is_matrix_reference(table.reference))
    assert tuple(row[-1] for row in matrix.rows) == ("Completed", "Not required")
    assert event in edited.blocks[0].extra_tables
    assert edited.blocks[0].text == "Human monthly correction"
    latest = training.load_training(profile.contract)
    assert latest["revision"] == stored["revision"] + 1
    _unchanged(history)
    app.run()
    assert not app.exception and not app.error
    assert _working_report(app) == edited
    assert training.load_training(profile.contract) == latest
    library.save_snapshot(edited, expected_revision=1)
    reopened = library.load_snapshot(profile.contract, profile.key, period).draft
    assert reopened == edited
    fresh = _open_app(reopened)
    assert not fresh.exception and not fresh.error
    fresh.run()
    assert _working_report(fresh) == reopened
    assert training.load_training(profile.contract) == latest
    december = new_month_draft(reopened, ReportPeriod(2026, 12))
    january = new_month_draft(december, ReportPeriod(2027, 1))
    assert december.blocks[0].extra_tables == january.blocks[0].extra_tables == (matrix,)
    assert matrix.reference == training.year_matrix_reference(2026)
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1) == saved_before
    assert library.load_snapshot(profile.contract, profile.key, period).draft == reopened
    _unchanged(history)


def test_explicit_ui_year_action_loads_both_sites_without_losing_monthly_note(profile):
    old = ReportTable(("Team member", "Site", "Prior requirement"),
        (("North Learner", "Synthetic North", "Completed"),
         ("South Learner", "Synthetic South", "")), training.year_matrix_reference(2026))
    stored = _save_pair(profile, year=2027, statuses=("Completed", "Not required"))
    history = _history()
    app = _open_app(_report(profile, old, period=ReportPeriod(2027, 1), notes="Prior note"))
    assert not app.exception and not app.error
    next(widget for widget in app.text_area if widget.label == "Training notes").set_value("Year switch note")
    next(button for button in app.button if button.label == "Start 2027 requirements").click().run()
    assert not app.exception and not app.error
    report = _working_report(app)
    matrix, = report.blocks[0].extra_tables
    assert matrix.reference == training.year_matrix_reference(2027)
    assert matrix.columns == ("Team member", "Site", "Fire Safety")
    assert tuple(row[-1] for row in matrix.rows) == ("Completed", "Not required")
    assert report.blocks[0].text == "Year switch note"
    latest = training.load_training(profile.contract)
    assert latest["revision"] == stored["revision"] + 1
    _unchanged(history)
    app.run()
    assert not app.exception and not app.error
    assert _working_report(app) == report
    assert training.load_training(profile.contract) == latest


def _output_report(profile):
    _save_site(profile, 0, ("Fire Safety",), (("North Complete", "Completed"), ("North Blank", "")))
    stored = _save_site(profile, 1, (" fire  safety ",),
        (("South Pending", "Pending"), ("South Exempt", "Not required")), revision=1)
    return _report(profile, _seed(profile, stored)), stored


def test_actual_docx_has_one_requirement_and_each_original_status(profile):
    from app.monthly_report_docx import assemble_docx

    report, stored = _output_report(profile)
    matrix, = report.blocks[0].extra_tables
    history = _history()
    raw = assemble_docx(report, acknowledged_fingerprint=report.fingerprint)
    document = Document(BytesIO(raw))
    table, = document.tables
    assert tuple(cell.text for cell in table.rows[0].cells) == matrix.columns
    assert tuple(tuple(cell.text for cell in row.cells) for row in table.rows[1:]) == matrix.rows
    assert sum(paragraph.text == "Training requirements — 2026" for paragraph in document.paragraphs) == 1
    assert training.load_training(profile.contract) == stored
    _unchanged(history)


@requires_libreoffice
def test_actual_pdf_keeps_site_statuses_and_shared_history(profile, tmp_path, monkeypatch):
    import fitz
    from app import pdf_converter
    from app.monthly_report_docx import assemble_docx

    report, stored = _output_report(profile)
    history = _history()
    raw = assemble_docx(report, acknowledged_fingerprint=report.fingerprint)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    path = tmp_path / "synthetic-training-requirements.docx"
    path.write_bytes(raw)
    pdf_bytes = pdf_converter.convert_to_pdf(path).read_bytes()
    target = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "training-requirement-identity"
    target.mkdir(parents=True, exist_ok=True)
    (target / "requirements.docx").write_bytes(raw)
    (target / "requirements.pdf").write_bytes(pdf_bytes)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
        for row in report.blocks[0].extra_tables[0].rows:
            assert " ".join(" ".join(row).split()) in text
        assert text.count("Training requirements — 2026") == 1
        for number, page in enumerate(document, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(target / f"requirements-page-{number}.png")
        pages = len(document)
    (target / "manifest.json").write_text(json.dumps({
        "synthetic_only": True, "pages": pages,
        "docx_sha256": sha256(raw).hexdigest(), "pdf_sha256": sha256(pdf_bytes).hexdigest(),
        "scenario": "independent site requirement spellings with preserved learner statuses",
    }, indent=2))
    assert training.load_training(profile.contract) == stored
    _unchanged(history)
