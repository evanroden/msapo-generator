"""Synthetic work-order coverage tests: no client source data."""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace as NS

import pytest

from app.monthly_report_work_order_coverage import (
    CoverageDecision, month_window, restore_decision, summarize_coverage,
)


def review(*rows, source="sha-one", sites=("north", "south"), questions=()):
    return NS(kind="records", source_sha256=source, source_fingerprint="fp-" + source,
              table_number=1, allowed_sites=tuple((s, (s,)) for s in sites),
              rows=rows, questions=questions)


def row(number, site, month, *, wo="T-1", state="Completed", kind="PM", issues=(), excluded=False):
    return NS(origin=NS(row_number=number), key="r" + str(number), site=site,
              work_date=month + "-03" if month else "", work_order=wo,
              status=state, work_type=kind, issues=issues, excluded=excluded)


def decision(r, *, contract="Example-01", profile="regional", site="north", start="2026-01", end="2026-12"):
    return CoverageDecision(contract, profile, site, r.source_sha256,
                            r.source_fingerprint, 1, start, end, "am_confirmed",
                            "AM verified that this export covers each month in range")


def summary(r, decisions, site="north", months=("2026-01", "2026-02"), contract="Example-01"):
    return summarize_coverage(r, tuple(decisions), contract=contract,
                              profile_key="regional", site=site, months=months,
                              as_of=date(2026, 11, 12))


def test_unknown_month_stays_blank_even_when_rows_exist():
    r = review(row(1, "north", "2026-01"))
    result = summary(r, [], months=("2026-01",))[0]
    assert result.total is None and not result.covered


def test_explicitly_covered_empty_month_is_zero_not_unknown():
    r = review(row(1, "north", "2026-01"))
    results = summary(r, [decision(r)])
    assert (results[0].total, results[1].total) == (1, 0)
    assert results[1].covered and results[1].pm == 0


def test_partial_twelve_month_window_is_blank_outside_attested_range():
    r = review(row(1, "north", "2026-04"))
    result = summary(r, [decision(r, start="2026-03", end="2026-07")],
                     months=month_window("2026-11"))
    assert len(result) == 12
    assert [v.month for v in result if v.covered] == [f"2026-{m:02d}" for m in range(3, 8)]
    assert all(v.total is None for v in result if not v.covered)
    assert next(v for v in result if v.month == "2026-04").total == 1


def test_same_work_order_id_across_two_sites_is_not_a_collision():
    r = review(row(1, "north", "2026-04", wo="abC"), row(2, "south", "2026-04", wo="ABC"))
    a = summary(r, [decision(r)], months=("2026-04",))[0]
    b = summary(r, [decision(r, site="south")], site="south", months=("2026-04",))[0]
    assert (a.total, b.total) == (1, 1)
    assert a.row_keys != b.row_keys


def test_same_site_case_variant_duplicate_stays_unknown():
    conflict = ("duplicate work-order identity",)
    r = review(row(1, "north", "2026-04", wo="w-9", issues=conflict),
               row(2, "north", "2026-04", wo="W-9", issues=conflict))
    result = summary(r, [decision(r)], months=("2026-04",))[0]
    assert result.total is None and len(result.issues) == 2


def test_missing_dates_and_ambiguous_site_block_covered_zero():
    r = review(row(1, "", "2026-04"), row(2, "north", ""))
    result = summary(r, [decision(r)], months=("2026-05",))[0]
    assert result.covered and result.total is None
    assert len(result.issues) == 2


def test_future_work_date_is_not_counted_as_approved():
    r = review(row(1, "north", "2026-12"))
    result = summary(r, [decision(r)], months=("2026-12",))[0]
    assert result.total is None and "future" in result.issues[0]


def test_unknown_pm_is_not_misreported_as_zero():
    r = review(row(1, "north", "2026-04", kind=""))
    result = summary(r, [decision(r)], months=("2026-04",))[0]
    assert (result.total, result.completed, result.open) == (1, 1, 0)
    assert result.pm is None and result.non_pm is None


def test_contract_profile_site_source_and_table_cannot_leak():
    r = review(row(1, "north", "2026-04"))
    good = decision(r)
    for corrupted in (replace(good, contract="Example-02"),
                      replace(good, profile_key="different"),
                      replace(good, site="south"),
                      replace(good, source_sha256="other"),
                      replace(good, source_fingerprint="new"),
                      replace(good, table_number=2)):
        with pytest.raises(ValueError, match="different"):
            summary(r, [corrupted], months=("2026-04",))


def test_source_title_rows_cannot_disappear_into_zero():
    r = review(row(1, "north", "2026-04", issues=("summary/title row needs review",)))
    assert summary(r, [decision(r)], months=("2026-04",))[0].total is None


def test_exclusion_is_visible_and_not_equivalent_to_no_rows():
    r = review(row(1, "north", "2026-04", excluded=True))
    assert summary(r, [decision(r)], months=("2026-04",))[0].total is None


def test_decision_round_trip_and_rejects_unverified_basis_and_invalid_month():
    r = review(row(1, "north", "2026-04"))
    c = decision(r)
    assert restore_decision(c.to_record()) == c
    with pytest.raises(ValueError):
        replace(c, basis="row_range")
    with pytest.raises(ValueError):
        replace(c, start_month="2026-13")
    with pytest.raises(ValueError):
        replace(c, start_month="2026-11", end_month="2026-10")
    with pytest.raises(ValueError):
        restore_decision({"schema": 1})
