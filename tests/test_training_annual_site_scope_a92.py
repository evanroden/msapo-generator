"""A92: annual Training saves must not enroll another site in its requirements.

Synthetic only. A flat cross-site editor shows a union of headings; an
untouched "Not recorded" placeholder is not a newly assigned requirement.
"""
from dataclasses import replace
from datetime import date
from io import BytesIO

import pytest
from docx import Document

from app import monthly_report_library as library, monthly_report_training as training
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock,
    default_sections,
)
from app.monthly_report_setup import new_month_draft


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "a92-synthetic"))
    return ReportProfile(
        "A92 Synthetic Training", "two_sites", "Synthetic Training Group",
        (Facility("north", "Synthetic North"), Facility("south", "Synthetic South")),
        "multi_site",
    )


def seed_distinct_sites(profile):
    """Two independently verified site/year matrices, not a shared course list."""
    for index, (heading, person, status) in enumerate((
        ("North-only Safety", "North Learner", "Completed"),
        ("South-only Protocol", "South Learner", "Pending"),
    )):
        site = profile.facilities[index]
        individual = replace(profile, facilities=(site,), scope_type="individual")
        table = ReportTable(
            ("Team member", "Site", heading), ((person, site.title, status),),
            training.year_matrix_reference(2026),
        )
        training.save_training(individual, table, expected_revision=index, actor="Synthetic Reviewer")
    current = training.load_training(profile.contract)
    merged = training.seed_matrix(
        profile, ResolvedBlock("training_summary", "This month"), current, year=2026)
    assert merged.columns[2:] == ("North-only Safety", "South-only Protocol")
    assert merged.rows == (
        ("North Learner", "Synthetic North", "Completed", "Not recorded"),
        ("South Learner", "Synthetic South", "Not recorded", "Pending"),
    )
    return current, merged


def site_columns(snapshot, year=2026):
    return {key: row["columns"] for key, row in snapshot["years"][str(year)]["sites"].items()}


def test_same_year_combined_edit_does_not_spread_site_only_requirements(profile):
    initial, merged = seed_distinct_sites(profile)
    changed = replace(merged, rows=(
        ("North Learner", "Synthetic North", "Pending", "Not recorded"),
        merged.rows[1],
    ))
    saved = training.save_training(
        profile, changed, expected_revision=initial["revision"], actor="Synthetic Reviewer")
    assert site_columns(saved) == {
        "north": ["North-only Safety"], "south": ["South-only Protocol"]}
    reloaded = training.load_training(profile.contract)
    assert reloaded == saved
    assert training.seed_matrix(
        profile, ResolvedBlock("training_summary", "This month"), reloaded, year=2026) == changed
    assert site_columns(initial) == site_columns(saved)


def test_cross_year_save_uses_each_facility_prior_schema_without_old_completions(profile):
    initial, merged = seed_distinct_sites(profile)
    january = training.matrix_for_year(profile, merged, initial, 2027)
    assert january.rows == (
        ("North Learner", "Synthetic North", "Not recorded", "Not recorded"),
        ("South Learner", "Synthetic South", "Not recorded", "Not recorded"),
    )
    saved = training.save_training(
        profile, january, expected_revision=initial["revision"], actor="Synthetic Reviewer")
    assert site_columns(saved, 2027) == {
        "north": ["North-only Safety"], "south": ["South-only Protocol"]}
    assert site_columns(saved, 2026) == site_columns(initial)
    again = training.seed_matrix(
        profile, ResolvedBlock("training_summary", "This month"), saved, year=2027)
    assert again == january
    assert training.load_training(profile.contract) == saved


def test_explicit_nondefault_status_can_assign_existing_course_to_other_site(profile):
    initial, merged = seed_distinct_sites(profile)
    reassigned = replace(merged, rows=(
        merged.rows[0],
        ("South Learner", "Synthetic South", "Not required", "Pending"),
    ))
    result = training.save_training(
        profile, reassigned, expected_revision=initial["revision"], actor="Synthetic Reviewer")
    assert site_columns(result) == {
        "north": ["North-only Safety"],
        "south": ["North-only Safety", "South-only Protocol"],
    }
    assert training.seed_matrix(
        profile, ResolvedBlock("training_summary", "This month"), result, year=2026) == reassigned


def test_two_session_collision_rebase_and_monthly_report_integrity(profile):
    initial, merged = seed_distinct_sites(profile)
    north = replace(merged, rows=(
        ("North Learner", "Synthetic North", "Pending", "Not recorded"), merged.rows[1]))
    south = replace(merged, rows=(
        merged.rows[0], ("South Learner", "Synthetic South", "Not recorded", "Completed")))
    first = training.save_training(
        profile, north, expected_revision=initial["revision"], actor="Editor A")
    with pytest.raises(library.RevisionConflict, match="updated elsewhere"):
        training.save_training(
            profile, south, expected_revision=initial["revision"], actor="Editor B")
    assert training.load_training(profile.contract) == first
    second = training.seed_matrix(
        profile, ResolvedBlock("training_summary", "This month"), first, year=2026)
    resolved = replace(second, rows=(second.rows[0],
        ("South Learner", "Synthetic South", "Not recorded", "Completed")))
    final = training.save_training(
        profile, resolved, expected_revision=first["revision"], actor="Editor B")
    assert final["revision"] == initial["revision"] + 2
    assert site_columns(final) == {
        "north": ["North-only Safety"], "south": ["South-only Protocol"]}

    period = ReportPeriod(2026, 11)
    event = training.add_event(
        None, title="Actual completed training", when=date(2026, 11, 12),
        mode="Virtual", participants=("South Learner",), hours="1", period=period)
    block = training.apply_tables(
        ResolvedBlock("training_summary", "This month", text="Monthly note"),
        resolved, event)
    section = next(item for item in default_sections() if item.key == "training")
    draft = ReportDraft(profile, period, "Synthetic Reviewer", (section,), (block,))
    snapshot = library.save_snapshot(draft, expected_revision=0)
    assert library.load_snapshot(profile.contract, profile.key, period) == snapshot
    december = new_month_draft(draft, ReportPeriod(2026, 12))
    january = new_month_draft(december, ReportPeriod(2027, 1))
    assert all(training.events_for_period(next(b for b in next_draft.blocks
        if b.key == "training_summary"), next_draft.period) is None
        for next_draft in (december, january))
    assert all(any(t.reference == training.year_matrix_reference(2026)
        for t in next(b for b in next_draft.blocks
        if b.key == "training_summary").extra_tables)
        for next_draft in (december, january))
    from app.monthly_report_docx import assemble_docx
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    document = Document(BytesIO(raw))
    all_cells = "\n".join(cell.text for tbl in document.tables for row in tbl.rows for cell in row.cells)
    assert "Actual completed training" in all_cells
    assert "North-only Safety" in all_cells and "South-only Protocol" in all_cells
    assert all_cells.count("Actual completed training") == 1
    assert training.load_training(profile.contract) == final
