"""Synthetic CSV/XLSX source identities must not inflate legacy Activity counts."""
from dataclasses import replace
from io import BytesIO

from openpyxl import Workbook
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import work_order_evidence

PROFILE = ReportProfile("Synthetic contract", "case-identity", "Invented sites", (
    Facility("north", "Synthetic North", ("North", "North Campus")),
    Facility("south", "Synthetic South", ("South", "South Campus"))),
    scope_type="multi_site")
PERIOD = ReportPeriod(2026, 9)


def evidence(monkeypatch, tmp_path, rows, *, suffix=".csv", site_column=True, profile=PROFILE):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    headers = ("Work Order", "Date", "Status", "Facility") if site_column else (
        "Work Order", "Date", "Status")
    if suffix == ".csv":
        raw = ("\n".join((",".join(headers), *rows)) + "\n").encode()
    else:
        assert suffix == ".xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Synthetic orders"
        sheet.append(headers)
        for row in rows:
            sheet.append(tuple(row.split(",")))
        stream = BytesIO()
        workbook.save(stream)
        raw = stream.getvalue()
    content, _ = sources.ingest(profile, "synthetic-orders" + suffix, raw)
    output = work_order_evidence(content, PERIOD, profile)
    assert sources.source_bytes(profile, content.source) == raw
    return output


@pytest.mark.parametrize("suffix", (".csv", ".xlsx"))
def test_case_variants_of_one_site_are_not_independent_completions(
        monkeypatch, tmp_path, suffix):
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed,North",
        "wo-a,2026-09-10,Completed,Synthetic North",
        "WO-B,2026-09-11,Open,North",
    ), suffix=suffix)
    assert (result.total, result.completed, result.open) == (1, 0, 1)
    assert result.rows == (("WO-B", "2026-09-11", "Open"),)
    assert "1 total, 0 completed, 1 open" in result.text
    assert any("1 work-order identities conflicted" in n for n in result.notices)
    assert not result.needs_site_confirmation


@pytest.mark.parametrize("suffix", (".csv", ".xlsx"))
def test_conflicting_case_variant_statuses_do_not_pick_winner(
        monkeypatch, tmp_path, suffix):
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed,North",
        "wo-a,2026-09-10,Open,North Campus",
        "WO-B,2026-09-12,Completed,North",
    ), suffix=suffix)
    assert (result.total, result.completed, result.open) == (1, 1, 0)
    assert result.rows == (("WO-B", "2026-09-12", "Completed"),)
    assert any("conflicted and were excluded" in n for n in result.notices)


@pytest.mark.parametrize("suffix", (".csv", ".xlsx"))
def test_cross_site_case_variants_remain_two_work_orders(monkeypatch, tmp_path, suffix):
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed,North",
        "wo-a,2026-09-10,Open,South",
    ), suffix=suffix)
    assert (result.total, result.completed, result.open) == (2, 1, 1)
    assert set(result.rows) == {
        ("WO-A", "2026-09-10", "Completed"),
        ("wo-a", "2026-09-10", "Open")}
    assert not any("conflicted" in n for n in result.notices)


def test_exact_repeated_id_keeps_existing_deduplication(monkeypatch, tmp_path):
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed,North",
        "WO-A,2026-09-10,Completed,North Campus",
        "WO-B,2026-09-11,Open,North",
    ))
    assert (result.total, result.completed, result.open) == (2, 1, 1)
    assert not any("conflicted" in n for n in result.notices)


def test_unassigned_cohort_keeps_site_confirmation(monkeypatch, tmp_path):
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed",
        "wo-a,2026-09-10,Completed",
        "WO-B,2026-09-11,Open",
    ), site_column=False)
    assert (result.total, result.completed, result.open) == (1, 0, 1)
    assert result.needs_site_confirmation
    assert any("conflicted" in n for n in result.notices)


def test_punctuation_is_never_guessed_as_same_identity(monkeypatch, tmp_path):
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed,North",
        "WOA,2026-09-10,Completed,North",
        "WO-B,2026-09-11,Open,North",
    ))
    assert (result.total, result.completed, result.open) == (3, 2, 1)
    assert not any("conflicted" in n for n in result.notices)


def test_outside_site_case_variant_cannot_erase_valid_site(monkeypatch, tmp_path):
    north = replace(PROFILE, facilities=(PROFILE.facilities[0],), scope_type="individual")
    result, = evidence(monkeypatch, tmp_path, (
        "WO-A,2026-09-10,Completed,North",
        "wo-a,2026-09-10,Open,South",
    ), profile=north)
    assert (result.total, result.completed, result.open) == (1, 1, 0)
    assert result.rows == (("WO-A", "2026-09-10", "Completed"),)
    assert any("did not match" in n for n in result.notices)
    assert not any("conflicted" in n for n in result.notices)
