"""Synthetic source roles must not bypass prior-month review routing."""
from app.monthly_report_import import DocxInspection, ImportItem
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans

PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 11)


def inspection(*items):
    return DocxInspection('synthetic-period-routing', tuple(items), (), (), 1,
                          cover_title_candidates=(PROFILE.facilities[0].title,
                                                  'Monthly Report October 2026'))


def item(identity, section, text, slot=''):
    return ImportItem(identity, 'text', 'word/document.xml', 100, 0,
                      section=section, suggested_slot=slot, text=text)


def test_explicit_utility_block_is_not_outside_period_analysis():
    source = item('utility', 'scorecards', 'Undated utility performance narrative.',
                  'utility_analysis')
    doc = inspection(source)
    result = analyze_starting_report(doc, PROFILE, PERIOD)
    assert source.id in result.uncertain_items
    assert source.id in result.period_review_items
    plan = automatic_section_plans(doc, result)['scorecards']
    assert source.id in plan['selected']
    assert not plan['approved']


def test_empty_slot_monthly_caption_requires_review_via_section_fallback():
    source = item('caption', 'activity', 'Pump overhaul work completed.')
    doc = inspection(source)
    result = analyze_starting_report(doc, PROFILE, PERIOD)
    assert source.id in result.period_review_items
    plan = automatic_section_plans(doc, result)['activity']
    assert plan['destinations'][source.id] == 'activity_summary'
    assert not plan['approved']


def test_dated_old_empty_slot_prose_is_not_current_month_work():
    source = item('old-caption', 'activity', 'October 2026 pump overhaul completed.')
    doc = inspection(source)
    result = analyze_starting_report(doc, PROFILE, PERIOD)
    assert source.id in result.older_items
    assert source.id not in automatic_section_plans(doc, result)['activity']['selected']


def test_standing_contract_text_is_not_forced_into_monthly_review():
    standing = item('standing', 'organization', 'Standing escalation workflow reference.')
    doc = inspection(standing)
    result = analyze_starting_report(doc, PROFILE, PERIOD)
    assert standing.id not in result.period_review_items
    assert standing.id not in result.older_items
    assert standing.id in automatic_section_plans(doc, result)['organization']['selected']


def test_cover_or_unknown_text_does_not_acquire_a_monthly_role():
    doc = inspection(item('cover', 'cover', 'Undated cover caption.'),
                     item('unknown', 'unrecognized', 'Undated source text.'))
    result = analyze_starting_report(doc, PROFILE, PERIOD)
    assert not result.period_review_items
    assert not result.older_items
