"""Synthetic source recovery and current-page consent at contract publication."""
from dataclasses import replace

import pytest

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as standards
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes, refresh_asset_source_context
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportSource, ReportTable, profile_sections
from app.monthly_report_source_recovery import used_missing_sources
from test_monthly_report_contract_workflows import isolated, report, image_block, file_bytes
from test_monthly_report_workflow_standards import publish


def imported_procedure():
    source = ReportSource('a' * 64, 'synthetic-procedure.pdf', 'b' * 64, '.pdf',
                          page_texts=('Technical outage procedure: inspect pump and reset controls.',),
                          selected_pages=(1,), facility=report().profile.facilities[0].title)
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    reference = f'{source.id}:1:{source.fingerprint}'
    block, assets = image_block(color='red')
    block = replace(block, references=(reference,), asset_provenance=((block.asset_hashes[0], (reference,)),))
    block = approve_all_assets(refresh_asset_source_context(block, (source,)))
    draft = report(blocks=(block,))
    return replace(draft, sources=(source,), sections=profile_sections(draft.profile)), block, assets


@pytest.mark.parametrize('retained', ['none', 'note', 'rows', 'table'])
def test_use_releases_only_obsolete_picture_dependencies(retained):
    _, default, _, _ = publish()
    draft, block, assets = imported_procedure()
    changes = {'none': {}, 'note': {'text': 'Retain source-supported note'},
               'rows': {'rows': (('Source-supported row',),)},
               'table': {'extra_tables': (ReportTable(('Detail',), (('Source-supported table',),)),)}}[retained]
    block = replace(block, **changes)
    draft = replace(draft, blocks=(block,))
    assert used_missing_sources(draft, draft.sources) == draft.sources
    result = standards.use_standard(draft, block, assets, expected_revision=1,
                                    expected_fingerprint=block.fingerprint)
    assert result.asset_hashes == default.asset_hashes
    assert not pending_asset_indexes(result)
    for name, value in changes.items():
        assert getattr(result, name) == value
    expected = () if retained == 'none' else draft.sources
    assert used_missing_sources(replace(draft, blocks=(result,)), draft.sources) == expected
    saved = library.save_snapshot(replace(draft, blocks=(result,)), expected_revision=0, assets=tuple(assets.items()))
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened == saved
    assert used_missing_sources(reopened.draft, draft.sources) == expected
    if retained == 'none':
        assert all(draft.sources[0].id not in ref for ref in result.references)
    else:
        assert set(block.references) <= set(result.references)


@pytest.mark.parametrize('revoked', ['selection', 'review', 'stale_review'])
def test_publication_rechecks_source_page_consent(revoked):
    draft, block, assets = imported_procedure()
    source = draft.sources[0]
    source = replace(source, **{'selection': {'selected_pages': ()}, 'review': {'client_page_reviews': ()},
                               'stale_review': {'client_page_reviews': ((1, 'old-review'),)}}[revoked])
    draft = replace(draft, sources=(source,))
    assert not pending_asset_indexes(refresh_asset_source_context(block, draft.sources))
    before = file_bytes()
    with pytest.raises(ValueError, match='source page'):
        standards.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before


def test_currently_approved_source_page_can_be_published():
    draft, block, assets = imported_procedure()
    state = standards.save_standard(draft, block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert state.revision == 1
    assert not pending_asset_indexes(state.workflows[0].block)
    assert all(draft.sources[0].id not in ref for ref in state.workflows[0].block.references)


@pytest.mark.parametrize('revoked', ['selection', 'review'])
def test_delivered_ui_save_cannot_promote_a_now_rejected_page(revoked):
    from test_monthly_report_contract_workflow_ui import start, button
    draft, block, assets = imported_procedure()
    app = start(draft, assets)
    assert not app.exception
    button(app, 'Save as contract default').click()
    source = replace(draft.sources[0], **({'selected_pages': ()} if revoked == 'selection'
                                        else {'client_page_reviews': ()}))
    changed = replace(draft, sources=(source,))
    app.session_state['draft'] = changed
    before = file_bytes()
    app.run()
    assert not app.exception
    assert standards.load_standards('Contract A').revision == 0
    assert file_bytes() == before
    assert app.session_state['draft'] == changed
    assert any('source page' in warning.value for warning in app.warning)
    app.run()
    assert file_bytes() == before
    assert button(app, 'Save as contract default').disabled
    app.session_state['draft'] = draft
    app.run()
    assert not button(app, 'Save as contract default').disabled
    button(app, 'Save as contract default').click().run()
    assert not app.exception and standards.load_standards('Contract A').revision == 1


def test_native_use_replaces_unavailable_picture_without_stale_page_or_dependency():
    from test_monthly_report_contract_workflow_ui import start, button
    _, default, _, _ = publish()
    draft, original, assets = imported_procedure()
    app = start(draft, assets)
    button(app, 'Use contract default in this report').click().run()
    assert not app.exception
    result = app.session_state['draft']
    assert result.blocks[0].asset_hashes == default.asset_hashes
    assert original.asset_hashes[0] not in result.blocks[0].asset_hashes
    assert not pending_asset_indexes(result.blocks[0])
    assert not used_missing_sources(result, draft.sources)
    app.run()
    assert app.session_state['draft'] == result


def test_unselected_unrelated_page_does_not_revoke_selected_picture():
    draft, block, assets = imported_procedure()
    source = replace(draft.sources[0], page_texts=(*draft.sources[0].page_texts, 'Unrelated page'))
    draft = replace(draft, sources=(source,))
    assert not pending_asset_indexes(refresh_asset_source_context(block, draft.sources))
    state = standards.save_standard(draft, block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert state.revision == 1


@pytest.mark.parametrize('text', ['', 'Total price: $10,000'])
def test_picture_receipt_cannot_override_source_content_policy(text):
    draft, block, assets = imported_procedure()
    source = replace(draft.sources[0], page_texts=(text,))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    block = approve_all_assets(refresh_asset_source_context(block, (source,)))
    draft = replace(draft, sources=(source,), blocks=(block,))
    assert not pending_asset_indexes(block)
    before = file_bytes()
    with pytest.raises(ValueError, match='source page'):
        standards.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before


@pytest.mark.parametrize('shape', ['missing_page', 'missing_digest', 'non_numeric', 'extra_part', 'bad_digest', 'unknown_source', 'unknown_kind'])
def test_malformed_external_source_provenance_cannot_bypass_page_consent(shape):
    draft, block, assets = imported_procedure()
    source = replace(draft.sources[0], selected_pages=(), client_page_reviews=())
    ref = {'missing_page': source.id, 'missing_digest': source.id + ':1',
           'non_numeric': source.id + ':one:' + source.fingerprint,
           'extra_part': source.id + ':1:' + source.fingerprint + ':extra',
           'bad_digest': source.id + ':1:invalid',
           'unknown_source': 'c' * 64 + ':one:' + source.fingerprint,
           'unknown_kind': 'unrecognized-import-source'}[shape]
    block = approve_all_assets(replace(block, references=(ref,), asset_provenance=((block.asset_hashes[0], (ref,)),)))
    draft = replace(draft, sources=(source,), blocks=(block,))
    before = file_bytes()
    with pytest.raises(ValueError):
        standards.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before


def test_legacy_stale_source_fingerprint_requires_fresh_picture_review():
    draft, block, assets = imported_procedure()
    ref = draft.sources[0].id + ':1:' + '0' * 64
    block = approve_all_assets(replace(block, references=(ref,), asset_provenance=((block.asset_hashes[0], (ref,)),)))
    draft = replace(draft, blocks=(block,))
    before = file_bytes()
    with pytest.raises(ValueError, match='review every'):
        standards.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before


@pytest.mark.parametrize('reference', ['docx:' + 'd' * 64 + ':image-1', 'contract-workflow-standard:v1:' + 'e' * 64])
def test_native_or_pinned_reference_is_not_an_external_source_page(reference):
    block, assets = image_block()
    block = approve_all_assets(replace(block, references=(reference,), asset_provenance=((block.asset_hashes[0], (reference,)),)))
    state = standards.save_standard(report(blocks=(block,)), block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert state.revision == 1
