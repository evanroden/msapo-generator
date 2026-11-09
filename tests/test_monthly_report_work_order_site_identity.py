"""Site-qualified work-order IDs must not erase unrelated selected-site facts."""
from dataclasses import replace

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import work_order_evidence


PERIOD = ReportPeriod(2026, 9)
PROFILE = ReportProfile("Invented contract", "site-identities", "Synthetic only", (
    Facility("north", "North", ("North Campus", "Shared-label")),
    Facility("south", "South", ("South Campus", "Shared label"))), scope_type="multi_site")


def evidence(tmp_path, monkeypatch, rows, *, profile=PROFILE, site_column=True):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    header = "Work Order,Date,Status,Facility" if site_column else "Work Order,Date,Status"
    raw = (header + "\n" + "\n".join(rows) + "\n").encode()
    content, _ = sources.ingest(profile, "invented-sites.csv", raw)
    result = work_order_evidence(content, PERIOD, profile)
    assert sources.source_bytes(profile, content.source) == raw
    return result


def test_same_id_in_two_explicit_sites_counts_each_site_even_when_facts_match(tmp_path, monkeypatch):
    result, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed,North",
        "001,2026-09-10,Completed,South",
    ))
    assert (result.total, result.completed, result.open) == (2, 2, 0)
    assert len(result.rows) == 2
    assert not result.needs_site_confirmation


def test_same_id_different_site_status_is_not_a_conflict(tmp_path, monkeypatch):
    result, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed,North",
        "001,2026-09-11,Open,South",
        "002,2026-09-12,Open,South",
    ))
    assert (result.total, result.completed, result.open) == (3, 1, 2)
    assert not any("conflicted" in notice for notice in result.notices)


def test_within_site_aliases_still_deduplicate_and_conflicts_only_remove_that_site(tmp_path, monkeypatch):
    result, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed,North",
        "001,2026-09-10,Completed,North Campus",
        "001,2026-09-10,Open,North Campus",
        "001,2026-09-11,Completed,South",
        "002,2026-09-12,Open,South",
        "002,2026-09-12,Open,South Campus",
    ))
    assert (result.total, result.completed, result.open) == (2, 1, 1)
    assert any("1 work-order identities conflicted" in notice for notice in result.notices)


def test_ambiguous_alias_never_becomes_last_selected_site_and_siblings_survive(tmp_path, monkeypatch):
    result, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed,Shared label",
        "002,2026-09-10,Open,North",
        "003,2026-09-10,Completed,Foreign campus",
    ))
    assert (result.total, result.completed, result.open) == (1, 0, 1)
    assert any("ambiguous site" in notice for notice in result.notices)
    assert any("did not match" in notice for notice in result.notices)
    swapped = replace(PROFILE, facilities=tuple(reversed(PROFILE.facilities)))
    reverse, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed,Shared label",
        "002,2026-09-10,Open,North",
        "003,2026-09-10,Completed,Foreign campus",
    ), profile=swapped)
    assert reverse.rows == result.rows and reverse.notices == result.notices


def test_missing_site_does_not_invent_per_site_copies_and_keeps_confirmation(tmp_path, monkeypatch):
    result, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed",
        "001,2026-09-10,Completed",
        "002,2026-09-11,Open",
    ), site_column=False)
    assert (result.total, result.completed, result.open) == (2, 1, 1)
    assert result.needs_site_confirmation


def test_selected_site_scope_keeps_exact_same_id_rows_local(tmp_path, monkeypatch):
    north = replace(PROFILE, facilities=(PROFILE.facilities[0],))
    result, = evidence(tmp_path, monkeypatch, (
        "001,2026-09-10,Completed,North",
        "001,2026-09-10,Open,South",
        "002,2026-10-01,Completed,North",
        "003,2026-09-10,Unknown,North",
    ), profile=north)
    assert (result.total, result.completed, result.open) == (1, 1, 0)
    assert result.rows == (("001", "2026-09-10", "Completed"),)
