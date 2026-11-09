"""Warning destinations must not confuse equal names/bytes or stale revisions."""
from dataclasses import asdict, replace
import pytest
from app.monthly_report_correction_targets import picture_target, resolve_target, source_target
from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
from app.monthly_report_checks import preflight
from app.monthly_report_model import (BlockSpec, ReportDraft, ReportPeriod, ReportSource,
    ResolvedBlock, SectionSpec, synthetic_profiles)


def fixture():
    source = ReportSource('source-a', 'same.pdf', 'hash', '.pdf', page_texts=('one', 'two'))
    other = replace(source, id='source-b')
    refs = ('source-a:1:hash', 'source-b:1:hash')
    block = ResolvedBlock('progress_photos', 'This month', asset_hashes=('same.png', 'same.png'),
                          asset_captions=('same', 'same'), references=refs)
    block = with_asset_instances(block, tuple(new_asset_instance('same.png', (ref,)) for ref in refs))
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor',
        (SectionSpec('activity', '1', 'Activity', (BlockSpec(block.key, 'rich_text'),)),),
        (block,), sources=(source, other))
    return draft, block, source


def test_identical_bytes_and_names_have_distinct_exact_targets_without_mutation():
    draft, block, source = fixture()
    before = asdict(draft)
    targets = [picture_target(draft, block, n) for n in range(2)]
    assert targets[0].token != targets[1].token
    assert [resolve_target(draft, t)[1] for t in targets] == [0, 1]
    assert source_target(draft, source).token != source_target(draft, draft.sources[1]).token
    assert asdict(draft) == before


@pytest.mark.parametrize('change', ['remove', 'caption', 'reorder', 'omit', 'duplicate', 'period', 'profile', 'excluded_section'])
def test_changed_picture_destination_never_opens_a_sibling(change):
    draft, block, _ = fixture()
    target = picture_target(draft, block, 0)
    if change == 'remove':
        changed = replace(draft, blocks=())
    elif change == 'caption':
        changed = replace(draft, blocks=(replace(block, asset_captions=('changed', 'same')),))
    elif change == 'reorder':
        changed = replace(draft, blocks=(replace(block, asset_instances=block.asset_instances[::-1]),))
    elif change == 'omit':
        changed = replace(draft, blocks=(replace(block, source='Omit'),))
    elif change == 'duplicate':
        changed = replace(draft, blocks=(block, block))
    elif change == 'excluded_section':
        changed = replace(draft, sections=(replace(draft.sections[0], included=False),))
    elif change == 'period':
        changed = replace(draft, period=ReportPeriod(2026, 10))
    else:
        changed = replace(draft, profile=replace(draft.profile, key='another-profile'))
    assert resolve_target(changed, target) is None


@pytest.mark.parametrize('change', ['removed', 'replacement', 'metadata', 'duplicate', 'page'])
def test_source_revision_and_page_are_exact(change):
    draft, _, source = fixture()
    target = source_target(draft, source, page=2)
    assert resolve_target(draft, target)[2] == source
    if change == 'removed': sources = draft.sources[1:]
    elif change == 'replacement': sources = (replace(source, sha256='different'), draft.sources[1])
    elif change == 'metadata': sources = (replace(source, facility='Changed'), draft.sources[1])
    elif change == 'duplicate': sources = (source, source)
    else: sources = (replace(source, page_texts=('one',)), draft.sources[1])
    assert resolve_target(replace(draft, sources=sources), target) is None


def test_preflight_keeps_pending_and_source_page_destinations():
    draft, block, _ = fixture()
    checks = preflight(draft)
    pending = next(check for check in checks if check.code == 'client_pages')
    assert len(pending.targets) == 2
    assert all(resolve_target(draft, target) is not None for target in pending.targets)
    pages = [check for check in checks if check.code == 'client_source_page']
    assert len(pages) == 2
    assert {target.source_id for check in pages for target in check.targets} == {'source-a', 'source-b'}
    assert {resolve_target(draft, target)[1] for check in pages for target in check.targets} == {0, 1}


def test_missing_source_warning_targets_only_its_surviving_picture():
    draft, block, _ = fixture()
    draft = replace(draft, sources=draft.sources[1:])
    checks = [check for check in preflight(draft) if check.code == 'client_source_missing']
    assert len(checks) == 1
    assert len(checks[0].targets) == 1
    assert resolve_target(draft, checks[0].targets[0])[:2] == (block, 0)
    assert checks[0].blocking


def test_display_navigation_identity_survives_caption_but_not_occurrence_removal():
    draft, block, _ = fixture()
    before = picture_target(draft, block, 0)
    changed = replace(block, asset_captions=('Delivered caption', 'same'))
    after = picture_target(replace(draft, blocks=(changed,)), changed, 0)
    assert before.navigation_key == after.navigation_key
    assert before.token != after.token
    # Read-only focus can follow this occurrence; no stale edit gains authority.
    assert resolve_target(replace(draft, blocks=(changed,)), before) is None
    assert before.navigation_key != picture_target(draft, block, 1).navigation_key
