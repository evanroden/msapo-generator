"""Prior-source acceptance composes with explicit annual Training identities."""
from dataclasses import replace
from datetime import date

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, ResolvedBlock, ReportTable
from app.monthly_report_training import (
    EVENT_REF, MATRIX_REF, add_event, session_row_tokens, year_matrix_reference,
)
from app.monthly_report_training_import import (
    training_tables, review_training_table, accepted_training_block,
)


PROFILE = ReportProfile("Synthetic training", "north", "Synthetic North",
                        (Facility("north", "Synthetic North"),), "individual")
PERIOD = ReportPeriod(2026, 9)
RAW = b"Team member,Site,Safety\nAlice,Synthetic North,Completed\n"


@pytest.fixture
def review(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    content, _ = sources.ingest(PROFILE, "requirements.csv", RAW)
    source, = training_tables(content, PROFILE)
    return review_training_table(source, PROFILE, PERIOD, source_year=2026)


def accept(review, block, **kwargs):
    return accepted_training_block(review, block,
        expected_block_fingerprint=block.fingerprint, **kwargs)


def test_imported_requirements_have_the_explicit_source_year(review):
    block = accept(review, ResolvedBlock("training_summary", "This month"))
    matrix, = block.extra_tables
    assert matrix.reference == year_matrix_reference(2026)
    assert matrix.rows == (("Alice", "Synthetic North", "Completed"),)


def test_requirements_import_preserves_monthly_sessions_and_tokens(review):
    events = add_event(None, title="Actual attendance", when=date(2026, 9, 7),
                       mode="Virtual", participants=("Alice",), hours="", period=PERIOD)
    block = ResolvedBlock("training_summary", "This month", text="Manual note",
                          extra_tables=(events,), references=("manual-evidence",))
    result = accept(review, block)
    kept = next(table for table in result.extra_tables if table.reference == EVENT_REF)
    assert kept == events
    assert session_row_tokens(kept) == session_row_tokens(events)
    assert result.text == "Manual note"
    assert result.references[0] == "manual-evidence"


@pytest.mark.parametrize("reference", [MATRIX_REF, year_matrix_reference(2025), year_matrix_reference(2026)])
def test_import_cannot_replace_an_existing_matrix_without_review(review, reference):
    existing = ReportTable(("Team member", "Site", "Different requirement"),
                           (("Bob", "Synthetic North", "Pending"),), reference)
    block = ResolvedBlock("training_summary", "This month", extra_tables=(existing,))
    with pytest.raises(ValueError, match="different standing requirements"):
        accept(review, block)
    assert block.extra_tables == (existing,)


def test_equal_year_matrix_is_repeat_safe_and_preserves_sessions(review):
    block = accept(review, ResolvedBlock("training_summary", "This month"))
    assert accept(review, block) == block


def test_future_year_requirements_never_seed_an_earlier_year(review):
    with pytest.raises(ValueError, match="future"):
        accept(replace(review, source_year=2027),
               ResolvedBlock("training_summary", "This month"), carry_prior_requirements=True)


def test_deliberate_prior_year_carry_resets_known_statuses_and_labels_current_year(review):
    old = replace(review, source_year=2025)
    block = accept(old, ResolvedBlock("training_summary", "This month"),
                   carry_prior_requirements=True)
    matrix, = block.extra_tables
    assert matrix.reference == year_matrix_reference(2026)
    assert matrix.rows == (("Alice", "Synthetic North", "Not recorded"),)
