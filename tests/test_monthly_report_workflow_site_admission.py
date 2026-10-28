"""Publishing defaults must not erase unresolved/foreign source-site evidence."""
from dataclasses import replace
import pytest
from app import monthly_report_workflow_standards as workflows
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_checks import preflight
from app.monthly_report_model import Facility
from app.monthly_report_source_scope import correct_scope
from test_monthly_report_contract_workflows import isolated, file_bytes
from test_monthly_report_workflow_source_guards import imported_procedure


def source_chart(kind):
    draft, block, assets = imported_procedure()
    facilities = (Facility('site-a', 'Synthetic Site A', ('Synthetic Alias A',)),)
    if kind == 'multi_site':
        facilities += (Facility('site-b', 'Synthetic Site B'),)
    draft = replace(draft, profile=replace(draft.profile, facilities=facilities, scope_type='multi_site' if kind == 'multi_site' else 'individual'))
    source = replace(draft.sources[0], facility='')
    if kind in ('known', 'alias', 'multi_site', 'foreign', 'foreign_corrected'):
        facility = {'known':'Synthetic Site A', 'alias':'Synthetic Alias A', 'multi_site':'Synthetic Site B',
                    'foreign':'Synthetic Other Site', 'foreign_corrected':'Synthetic Other Site'}[kind]
        source = replace(source, facility=facility)
    if kind in ('corrected', 'foreign_corrected', 'stale_scope', 'other_contract'):
        profile = replace(draft.profile, contract='Synthetic Other Contract') if kind == 'other_contract' else draft.profile
        source = correct_scope(source, profile, ('site-a',))
        if kind == 'stale_scope':
            source = replace(source, service_date='2026-10-03')
    if kind == 'contract_artwork':
        source = correct_scope(source, draft.profile, contract_artwork=True, artwork_keys=(block.key,))
    reference = f'{source.id}:1:{source.fingerprint}'
    block = replace(block, references=(reference,), asset_provenance=((block.asset_hashes[0], (reference,)),))
    block = approve_all_assets(refresh_asset_source_context(block, (source,)))
    return replace(draft, sources=(source,), blocks=(block,)), block, assets


@pytest.mark.parametrize('kind', ['foreign', 'unresolved', 'foreign_corrected', 'stale_scope', 'other_contract'])
def test_scope_blocker_cannot_be_laundered_into_contract_default(kind):
    draft, block, assets = source_chart(kind)
    assert any(c.code == 'source_facility' and c.blocking for c in preflight(draft))
    before, original_assets = file_bytes(), dict(assets)
    with pytest.raises(ValueError, match='site'):
        workflows.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before and assets == original_assets
    assert workflows.load_standards(draft.profile.contract).revision == 0
    assert not workflows._path(draft.profile.contract).exists()


@pytest.mark.parametrize('kind', ['known', 'alias', 'corrected', 'multi_site', 'contract_artwork'])
def test_current_site_admission_allows_explicit_publication(kind):
    draft, block, assets = source_chart(kind)
    assert not any(c.code == 'source_facility' and c.blocking for c in preflight(draft))
    state = workflows.save_standard(draft, block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert state.revision == 1


@pytest.mark.parametrize('kind', ['foreign', 'unresolved'])
def test_delivered_publish_click_rechecks_source_site_admission(kind):
    from test_monthly_report_contract_workflow_ui import start, button
    draft, block, assets = source_chart('known')
    app = start(draft, assets)
    button(app, 'Save as contract default').click()
    changed_source = replace(draft.sources[0], facility='Synthetic Other Site' if kind == 'foreign' else '')
    # This is a reviewed image, but its independent current site gate remains unresolved.
    reviewed = approve_all_assets(refresh_asset_source_context(block, (changed_source,)))
    changed = replace(draft, sources=(changed_source,), blocks=(reviewed,))
    assert reviewed.fingerprint == block.fingerprint
    app.session_state['draft'] = changed
    before = file_bytes()
    app.run()
    assert not app.exception
    assert workflows.load_standards(draft.profile.contract).revision == 0
    assert not workflows._path(draft.profile.contract).exists()
    assert file_bytes() == before and app.session_state['draft'] == changed
    assert any('site' in w.value for w in app.warning)
    app.run()
    assert button(app, 'Save as contract default').disabled
    assert file_bytes() == before
    corrected = correct_scope(replace(changed_source, facility=''), draft.profile, ('site-a',))
    reviewed = approve_all_assets(refresh_asset_source_context(block, (corrected,)))
    app.session_state['draft'] = replace(draft, sources=(corrected,), blocks=(reviewed,))
    app.run()
    assert not button(app, 'Save as contract default').disabled
    button(app, 'Save as contract default').click().run()
    assert not app.exception and workflows.load_standards(draft.profile.contract).revision == 1


@pytest.mark.parametrize('kind', ['foreign', 'unresolved', 'corrected'])
def test_legacy_adoption_retains_current_source_site_boundary(kind):
    from dataclasses import asdict
    from app import monthly_report_library as library
    draft, block, assets = source_chart(kind)
    item = workflows.WorkflowStandard(block.key, block, draft.profile.contract, 'synthetic-old-site', block.fingerprint, '2026-10-01')
    path = workflows._path()
    for ref, raw in assets.items():
        library._atomic_write(path / 'assets' / ref, raw)
    library._atomic_write(path / 'manifest.json', library._json({'schema': 1, 'revision': 1, 'workflows': [asdict(item)]}))
    before = file_bytes()
    kwargs = dict(expected_revision=0, expected_legacy_fingerprint=block.fingerprint, confirmed=True, expected_legacy_receipt=workflows.legacy_review_receipt(item))
    if kind == 'corrected':
        assert workflows.adopt_legacy(draft, block.key, **kwargs).revision == 1
        assert all(file_bytes()[name] == raw for name, raw in before.items())
    else:
        with pytest.raises(ValueError, match='site'):
            workflows.adopt_legacy(draft, block.key, **kwargs)
        assert file_bytes() == before
