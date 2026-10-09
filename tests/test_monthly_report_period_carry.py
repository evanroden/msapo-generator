"""Monthly results retain their real period and evidence until expressly updated."""

from dataclasses import replace

import pytest

from app.monthly_report_ai import ai_references, evidence_fingerprint
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock,
                                      SectionSpec, synthetic_profiles)
from app.monthly_report_setup import carried_period, confirm_current_period, new_month_draft
from app.monthly_report_sources import source_reference


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)


def report(key, text, *, source=None):
    section = "mbcx" if key.startswith("mbcx_") else "scorecards"
    kind = "pdf_pages" if key == "mbcx_report" else "rich_text"
    block = ResolvedBlock(key, "This month", text=text)
    if source:
        reference = source_reference(source, 1)
        block = replace(block, references=(reference,), ai_written=True,
                        ai_evidence_fingerprint=evidence_fingerprint((source,), (reference,)))
        block = replace(block, reviewed_fingerprint=block.fingerprint)
    return ReportDraft(synthetic_profiles()[0], SEPTEMBER, "Synthetic Editor",
                       (SectionSpec(section, "4", "Synthetic results", (BlockSpec(key, kind),)),),
                       (block,), sources=(source,) if source else ())


def results(draft, key):
    return next(b for b in draft.blocks if b.key == key)


@pytest.mark.parametrize("key,text", [
    ("mbcx_report", "The air handlers passed this month’s functional checks."),
    ("mbcx_status", "The air handlers passed this month’s functional checks."),
    ("utility_analysis", "The utility results are within the expected operating range."),
])
def test_prior_month_results_cannot_print_as_current_without_confirmation(key, text):
    prior = report(key, text)
    following = new_month_draft(prior, OCTOBER)
    carried_key = "mbcx_status" if key == "mbcx_report" else key
    carried = results(following, carried_key)
    assert carried.text == text
    assert carried.source == "Last month"
    assert carried_period(carried, OCTOBER) == SEPTEMBER
    assert "report-origin:2026-09" in carried.references
    check = next(c for c in preflight(following) if c.code == "carried_period")
    assert check.blocking and check.block_key == carried_key
    assert "September 2026" in check.message and "October 2026" in check.message
    with pytest.raises(ValueError, match="last confirmed for September 2026"):
        assemble_docx(following)
    assert prior.period == SEPTEMBER and prior.blocks[0].text == text


def test_same_period_and_standing_org_content_need_no_new_period_review():
    prior = report("utility_analysis", "Synthetic utility result.")
    assert new_month_draft(prior, SEPTEMBER) == prior
    org = replace(prior.blocks[0], key="org_chart", asset_hashes=("synthetic.png",), text="")
    prior = replace(prior, blocks=(org,))
    following = new_month_draft(prior, OCTOBER)
    assert following.blocks[0] == org
    assert carried_period(org, OCTOBER) is None


def test_current_period_confirmation_retains_original_period_and_true_evidence():
    prior = report("utility_analysis", "Synthetic utility result.")
    source_ref = "synthetic-source:1:synthetic-hash"
    prior = replace(prior, blocks=(replace(prior.blocks[0], references=(source_ref,)),))
    following = new_month_draft(prior, OCTOBER)
    carried = results(following, "utility_analysis")
    confirmed = confirm_current_period(carried, OCTOBER)
    assert confirmed.text == carried.text
    assert confirmed.references == (source_ref, "report-origin:2026-09", "report-period:2026-10")
    assert confirmed.source == "This month"
    assert not confirmed.reviewed_fingerprint and not confirmed.client_reviewed_fingerprint
    assert carried_period(confirmed, OCTOBER) is None
    confirmed_draft = replace(following, blocks=(confirmed,))
    assert not any(c.code == "carried_period" for c in preflight(confirmed_draft))
    next_month = new_month_draft(confirmed_draft, ReportPeriod(2026, 11))
    assert carried_period(next_month.blocks[0], next_month.period) == OCTOBER
    assert "report-origin:2026-09" in next_month.blocks[0].references


def test_skipped_review_preserves_actual_older_period_across_another_rollover():
    following = new_month_draft(report("mbcx_status", "Synthetic result."), OCTOBER)
    later = new_month_draft(following, ReportPeriod(2026, 11))
    assert carried_period(results(later, "mbcx_status"), later.period) == SEPTEMBER


@pytest.mark.parametrize("change", [{"source": "Omit"}, {"text": ""}])
def test_removed_or_omitted_content_does_not_require_period_confirmation(change):
    following = new_month_draft(report("utility_analysis", "Synthetic utility result."), OCTOBER)
    changed = replace(following, blocks=(replace(following.blocks[0], **change),))
    assert not any(c.code == "carried_period" for c in preflight(changed))


def test_carried_evidence_is_retained_unchanged_without_other_monthly_uploads():
    source = ReportSource("a" * 64, "synthetic-utility.txt", "b" * 64, ".txt", "Reference only",
                           service_date="2026-09-15", page_texts=("Synthetic utility result.",), selected_pages=(1,))
    unrelated = replace(source, id="c" * 64, filename="unreferenced.txt")
    prior = report("utility_analysis", "Synthetic utility result.", source=source)
    prior = replace(prior, sources=(source, unrelated))
    following = new_month_draft(prior, OCTOBER)
    carried = results(following, "utility_analysis")
    assert following.sources == (source,)
    assert following.sources[0].service_date == "2026-09-15"
    assert ai_references(carried) == prior.blocks[0].references
    assert carried.ai_evidence_fingerprint == evidence_fingerprint(following.sources, ai_references(carried))
    assert not any(c.code == "ai_evidence" for c in preflight(following))
    assert not carried.reviewed
    assert any(c.code == "carried_period" for c in preflight(following))
