"""Capacity first-fill composes with contract charts without changing saved choices."""
from dataclasses import replace
import pytest
from app import monthly_report_capacity as capacity, monthly_report_library as library
from app import monthly_report_org_chart_defaults as charts
from app.monthly_report_guided import _initial_draft
from app.monthly_report_model import Facility, ReportPeriod, ResolvedBlock
from app.monthly_report_setup import new_month_draft
from test_monthly_report_capacity import profile, saved
from test_monthly_report_org_chart_defaults import publish, picture, chart


def block(draft, key):
    return next(b for b in draft.blocks if b.key == key)


@pytest.mark.parametrize('site', ['north', 'south'])
@pytest.mark.parametrize('month', [10, 11])
def test_fresh_reports_get_contract_chart_and_capacity_from_one_publication(profile, site, month):
    state = library.save_profile(profile, expected_revision=0, actor='Synthetic Tester', confirmed=True)
    _, shared_chart, _ = publish(profile)
    shared_capacity = saved(profile)
    target = profile if site == 'north' else replace(profile, key='south', title='South Hospital',
        facilities=(Facility('south', 'South Hospital', ('SH',)),))
    if site == 'south':
        state = library.save_profile(target, expected_revision=0, actor='Synthetic Tester', confirmed=True)
    assets = {}
    initial = _initial_draft(state, ReportPeriod(2026, month), 'Synthetic Tester', assets=assets)
    assert block(initial, 'thermal_capacity').source == 'This month'
    result = capacity.resolve_capacity(initial)
    assert chart(result).asset_hashes == shared_chart.asset_hashes
    assert set(assets) == set(shared_chart.asset_hashes)
    assert block(result, 'thermal_capacity') == capacity.capacity_block(target, shared_capacity)
    assert capacity.load_capacity(profile.contract) == shared_capacity
    assert charts.load_defaults(profile.contract).revision == 1
    assert library.load_profile(target.contract, target.key) == state


@pytest.mark.parametrize('source', ['Omit', 'This month'])
def test_explicit_imported_and_resumed_choices_remain_pinned(profile, source):
    state = library.save_profile(profile, expected_revision=0, actor='Synthetic Tester', confirmed=True)
    saved(profile)
    publish(profile)
    local_chart, assets = picture('green')
    explicit = ResolvedBlock('thermal_capacity', source, rows=(('NH', 'Steam', 'NR', 'lb/hr'),))
    state = library.replace_block(profile.contract, profile.key, 'thermal_capacity', explicit,
        label='Imported capacity', expected_revision=state.revision, actor='Synthetic Tester', confirmed=True)
    state = library.replace_block(profile.contract, profile.key, 'org_chart', local_chart,
        label='Imported chart', expected_revision=state.revision, actor='Synthetic Tester', confirmed=True,
        assets=tuple(assets.items()))
    # Imported content is already an explicit report copy, not fresh default adoption.
    imported = _initial_draft(state, ReportPeriod(2026, 10), 'Synthetic Tester')
    library.save_snapshot(imported, expected_revision=0, assets=tuple(assets.items()))
    before = library.load_snapshot(profile.contract, profile.key, imported.period)
    for existing in (imported, before.draft, new_month_draft(before.draft, ReportPeriod(2026, 11))):
        resolved = capacity.resolve_capacity(charts.apply_defaults(existing, {}))
        assert block(resolved, 'thermal_capacity') == explicit
        assert chart(resolved) == local_chart
    assert library.load_snapshot(profile.contract, profile.key, imported.period) == before
    assert library.load_profile(profile.contract, profile.key) == state
