"""Wording review does not accept an active source's reporting date."""
from dataclasses import asdict, replace

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_ai import evidence_fingerprint, reviewed_block
from app.monthly_report_checks import preflight
from app.monthly_report_cmms import CMMSMapping, map_cmms
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_source_readiness import content_readiness
from app.monthly_report_source_scope import contribution_receipt
from app.monthly_report_source_status import source_manager_status
from app.monthly_report_work_order_csv import work_order_evidence


PERIOD = ReportPeriod(2026, 9)
DATE_CODES = {"source_period", "source_date_unknown"}


def reviewed_text(source, key="activity_summary"):
    references = (sources.source_reference(source, 1),)
    block = ResolvedBlock(key, "This month", text="Completed a synthetic inspection.",
                          references=references, ai_written=True)
    block = replace(block, ai_evidence_fingerprint=evidence_fingerprint((source,), references))
    return reviewed_block(block, (source,))


def text_draft(monkeypatch, tmp_path, when, *, classification="Vendor service", selected=(1,)):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = b"Completed a synthetic inspection."
    content, _ = sources.ingest(profile, "synthetic-reviewed-date.txt", raw)
    source = replace(content.source, service_date=when, facility=profile.facilities[0].key,
                     classification=classification, selected_pages=selected)
    block = reviewed_text(source)
    draft = ReportDraft(profile, PERIOD, "Synthetic editor",
        (SectionSpec("activity", "2", "Monthly Activity", (BlockSpec(block.key, "rich_text"),)),),
        (block,), sources=(source,), synthetic=True)
    return draft, replace(content, source=source), raw


def unchanged_status(draft, content, raw):
    before = asdict(draft), content
    status, = source_manager_status(draft, (content,))
    assert (asdict(draft), content) == before
    restored = library.draft_from_dict(asdict(draft))
    assert source_manager_status(restored, (replace(content, source=restored.sources[0]),)) == (status,)
    assert sources.source_bytes(draft.profile, content.source) == raw
    return status


@pytest.mark.parametrize("when", ["", "unresolved", "2026-08-04", "2026-10-04"])
def test_reviewed_wording_keeps_missing_invalid_or_other_month_date_actionable(monkeypatch, tmp_path, when):
    draft, content, raw = text_draft(monkeypatch, tmp_path, when)
    assert content_readiness(draft, content.source).accepted
    expected_checks = tuple(check for check in preflight(draft) if check.code in DATE_CODES)
    assert len(expected_checks) == 1 and not expected_checks[0].blocking
    status = unchanged_status(draft, content, raw)
    assert not status.resolved and status.needs_correction
    assert status.reason == "Check the source reporting date."
    assert tuple(check for check in preflight(draft) if check.code in DATE_CODES) == expected_checks


def test_reviewed_wording_with_current_date_can_resolve(monkeypatch, tmp_path):
    draft, content, raw = text_draft(monkeypatch, tmp_path, "2026-09-04")
    status = unchanged_status(draft, content, raw)
    assert status.resolved and not status.needs_correction and not status.reason
    assert status.summary == "Content reviewed · Monthly Activity"
    assert not any(check.code in DATE_CODES for check in preflight(draft))


@pytest.mark.parametrize("when", ["", "2026-08-04"])
@pytest.mark.parametrize("classification,selected", [("Reference only", (1,)), ("Vendor service", ())])
def test_historical_reference_and_unselected_source_choices_keep_existing_date_semantics(
        monkeypatch, tmp_path, when, classification, selected):
    draft, content, raw = text_draft(monkeypatch, tmp_path, when,
                                   classification=classification, selected=selected)
    assert not any(check.code in DATE_CODES for check in preflight(draft))
    status = unchanged_status(draft, content, raw)
    assert status.resolved and not status.needs_correction and not status.reason


def accepted_contribution(monkeypatch, tmp_path, when, kind):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = b"Work Order,Date,Status,Facility\n001,2026-09-04,Completed,Demo North\n"
    content, _ = sources.ingest(profile, "synthetic-period-bound.csv", raw)
    source = replace(content.source, service_date=when, facility="", classification="CMMS export")
    content = replace(content, source=source)
    if kind == "totals":
        report, = work_order_evidence(content, PERIOD, profile)
        receipt = contribution_receipt(report.reference, profile, PERIOD, "activity_summary",
                                       text=report.text, source=source)
        blocks = (ResolvedBlock("activity_summary", "This month", text=report.text,
                                references=(report.reference, receipt)),)
        specs = (BlockSpec("activity_summary", "rich_text"),)
    else:
        result = map_cmms(content.tables[0], CMMSMapping("Date", "Work Order", facility="Facility",
            status="Status", completed_statuses=("Completed",), complete_months=(PERIOD.key,),
            complete_facilities=tuple(site.key for site in profile.facilities)),
            profile, PERIOD, sources.source_reference(source, 1), scope_source=source)
        blocks, specs = result.blocks, result.specs
    draft = ReportDraft(profile, PERIOD, "Synthetic editor",
        (SectionSpec("maintenance", "5", "Maintenance", specs),), blocks,
        sources=(source,), synthetic=True)
    return draft, content, raw


@pytest.mark.parametrize("when", ["", "unresolved", "2026-08-04"])
@pytest.mark.parametrize("kind", ["totals", "rows"])
def test_current_report_mapped_contributions_do_not_require_a_second_file_date(
        monkeypatch, tmp_path, when, kind):
    draft, content, raw = accepted_contribution(monkeypatch, tmp_path, when, kind)
    status = unchanged_status(draft, content, raw)
    assert status.resolved and not status.needs_correction and not status.reason
    assert status.summary.startswith("Totals accepted" if kind == "totals" else "Tables accepted")


def test_one_mapped_receipt_cannot_accept_the_date_of_separate_reviewed_wording(monkeypatch, tmp_path):
    draft, content, raw = accepted_contribution(monkeypatch, tmp_path, "2026-08-04", "totals")
    # An exact site is established separately, so this isolates the date task.
    source = replace(content.source, facility=draft.profile.facilities[0].key)
    reference = sources.source_reference(source, 1)
    original = draft.blocks[0]
    receipt = contribution_receipt(reference, draft.profile, PERIOD, original.key,
                                   text=original.text, source=source)
    original = replace(original, references=(reference, receipt))
    extra = reviewed_text(source, "improvements")
    draft = replace(draft, sources=(source,), blocks=(original, extra), sections=(
        replace(draft.sections[0], blocks=(*draft.sections[0].blocks, BlockSpec(extra.key, "rich_text"))),))
    content = replace(content, source=source)
    assert content_readiness(draft, source).accepted
    status = unchanged_status(draft, content, raw)
    assert not status.resolved and status.needs_correction
    assert status.reason == "Check the source reporting date."
