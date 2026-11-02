"""Real historical seeding format, not a fabricated unpinned legacy fixture."""
from dataclasses import asdict, replace
import importlib.util
from pathlib import Path
import sys
import pytest
from app import monthly_report_library as library, monthly_report_workflow_standards as workflows
from app.monthly_report_asset_review import approve_all_assets
from test_monthly_report_contract_workflows import isolated, report, image_block, file_bytes


def seeded():
    path = Path(__file__).parent / 'fixtures' / 'legacy_workflow_seed_a1b2aa61.py'
    spec = importlib.util.spec_from_file_location('historical_workflow_seed', path)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    block, assets = image_block()
    draft = report(blocks=(block,))
    library.save_profile(draft.profile, expected_revision=0, actor=draft.prepared_by, confirmed=True)
    library.replace_block(draft.profile.contract, draft.profile.key, block.key, block,
        label='Synthetic saved procedure', expected_revision=1, actor=draft.prepared_by,
        confirmed=True, assets=tuple(assets.items()))
    old.seed_from_saved_profile(draft.profile.contract, draft.profile.key)
    return draft, workflows.legacy_candidate(draft.profile.contract, block.key)


def test_actual_old_seed_can_be_explicitly_adopted_without_mutating_history():
    draft, item = seeded()
    assert item.block.references[0].startswith('enfra-workflow-standard:')
    before = file_bytes()
    kwargs = dict(expected_revision=0, expected_legacy_fingerprint=item.block.fingerprint, confirmed=True)
    if hasattr(workflows, 'legacy_review_receipt'):
        kwargs['expected_legacy_receipt'] = workflows.legacy_review_receipt(item)
    state = workflows.adopt_legacy(draft, item.key, **kwargs)
    assert state.revision == 1
    assert all(file_bytes()[name] == raw for name, raw in before.items())
    assert state.workflows[0].block.asset_hashes == item.block.asset_hashes


def test_real_legacy_preview_and_adoption_native_flow():
    from test_monthly_report_contract_workflow_ui import start, button
    draft, item = seeded()
    app = start(draft)
    assert button(app, 'Adopt legacy procedure for this contract').disabled
    button(app, 'Preview legacy procedure').click().run()
    button(app, 'Adopt legacy procedure for this contract').click().run()
    assert not app.exception
    assert workflows.load_standards(draft.profile.contract).revision == 1


def write_legacy(item, revision=1):
    library._atomic_write(workflows._path() / 'manifest.json', library._json(
        {'schema': 1, 'revision': revision, 'workflows': [asdict(item)]}))


@pytest.mark.parametrize('change', ['origin_profile', 'origin_fingerprint', 'saved_at', 'revision', 'origin_contract'])
def test_full_legacy_receipt_rejects_record_change(change):
    draft, item = seeded()
    receipt = workflows.legacy_review_receipt(item)
    changed = replace(item, **{change: {'origin_profile':'other-site', 'origin_fingerprint':'0'*64,
        'saved_at':'2026-10-02', 'origin_contract':'Other Contract'}[change]}) if change != 'revision' else item
    write_legacy(changed, 2 if change == 'revision' else 1)
    before = file_bytes()
    with pytest.raises(ValueError):
        workflows.adopt_legacy(draft,item.key,expected_revision=0,expected_legacy_fingerprint=item.block.fingerprint,
                               expected_legacy_receipt=receipt,confirmed=True)
    assert file_bytes() == before


@pytest.mark.parametrize('change', ['mixed_raw', 'notes', 'malformed', 'tampered_asset', 'missing_receipt'])
def test_legacy_exception_is_not_a_namespace_bypass(change, monkeypatch):
    draft, item = seeded()
    block = item.block
    if change == 'mixed_raw':
        block = approve_all_assets(replace(block,references=(*block.references,'missing:1:'+'a'*64),asset_provenance=()))
    elif change == 'notes':
        block = approve_all_assets(replace(block,text='Unreviewed neighboring site note'))
    elif change == 'malformed':
        block = approve_all_assets(replace(block,references=('enfra-workflow-standard:bad',),asset_provenance=()))
    item = replace(item,block=block)
    write_legacy(item)
    if change == 'tampered_asset':
        # Simulate corrupt read bytes without writing immutable asset storage.
        monkeypatch.setattr(workflows, 'read_asset',
            lambda reference: workflows._verify_asset(reference, b'corrupted synthetic image'))
    before = file_bytes()
    with pytest.raises(ValueError):
        workflows.adopt_legacy(draft,item.key,expected_revision=0,expected_legacy_fingerprint=block.fingerprint,
            expected_legacy_receipt=None if change=='missing_receipt' else workflows.legacy_review_receipt(item),confirmed=True)
    assert file_bytes() == before


def test_pinned_legacy_marker_still_cannot_bypass_normal_publication():
    draft,item=seeded();draft=replace(draft,blocks=(item.block,));before=file_bytes()
    with pytest.raises(ValueError):
        workflows.save_standard(draft,item.block,{},expected_revision=0,expected_fingerprint=item.block.fingerprint,confirmed=True)
    assert file_bytes()==before


def test_native_preview_receipt_rejects_changed_origin_and_requires_new_preview():
    from test_monthly_report_contract_workflow_ui import start,button
    draft,item=seeded();app=start(draft)
    button(app,'Preview legacy procedure').click().run()
    button(app,'Adopt legacy procedure for this contract').click()
    write_legacy(replace(item,origin_profile='different-recorded-site'))
    before=file_bytes();app.run()
    assert not app.exception and workflows.load_standards(draft.profile.contract).revision==0
    assert file_bytes()==before
    assert button(app,'Adopt legacy procedure for this contract').disabled
    assert any('changed' in warning.value for warning in app.warning)
    assert any('different-recorded-site' in c.value.replace(chr(92), '') for c in app.caption)
