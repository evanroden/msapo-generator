"""Saved report identities must retain unambiguous catalog cover aliases."""
from dataclasses import replace
from app.monthly_report_import import DocxInspection
from app.monthly_report_model import Facility, ReportPeriod, synthetic_profiles
from app.monthly_report_start_import import analyze_starting_report, merge_source_site_choices


def test_saved_target_without_alias_does_not_erase_catalog_abbreviation():
    catalog = Facility('north', 'Demonstration North Facility', ('DNF',))
    saved = replace(catalog, aliases=())
    profile = replace(synthetic_profiles()[0], facilities=(saved,))
    sites = merge_source_site_choices((catalog,), (saved,), profile.facilities)
    inspection = DocxInspection('x', (), ('DNF', 'October 2026'), (), 1,
                                cover_title_candidates=('DNF', 'October 2026'))
    result = analyze_starting_report(inspection, profile, ReportPeriod(2026, 11), sites)
    assert result.site_relation == 'same'
    assert result.source_sites[0].key == saved.key
    assert 'DNF' in result.source_sites[0].aliases
    assert saved.aliases == ()


def test_aliases_are_unioned_without_mutating_saved_site():
    first = Facility('north', 'North Facility', ('NF',))
    second = Facility('north', 'North Facility', ('North', 'NF'))
    assert merge_source_site_choices((first,), (second,))[0].aliases == ('NF', 'North')
    assert first.aliases == ('NF',)


def test_conflicting_title_for_same_key_does_not_borrow_alias():
    prior = Facility('north', 'North Facility', ('NF',))
    other = Facility('north', 'South Facility')
    assert merge_source_site_choices((prior,), (other,)) == (other,)
