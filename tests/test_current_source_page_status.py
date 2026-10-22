"""Current caption review resolves display status without granting admission."""
from dataclasses import replace
import pytest
from app import monthly_report_sources as sources
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections, synthetic_profiles
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_page_controls import revise_included_page
from app.monthly_report_source_status import source_manager_status
from app.monthly_report_asset_layout import document_page_indexes
from app.monthly_report_asset_review import pending_asset_indexes
from test_monthly_report_sources import pdf_bytes


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, 'synthetic-reviewed-page.pdf', pdf_bytes(1))
    source = replace(content.source, classification='Vendor service', service_date='2026-09-04',
                     facility=profile.facilities[0].key, selected_pages=(1,), captions=((1,'Original caption'),))
    source = replace(source, client_page_reviews=((1,page_fingerprint(source,1)),))
    content = replace(content,source=source)
    block, = sources.prepare_pages(profile,(content,),((source.id,'improvements'),))
    draft = ReportDraft(profile,ReportPeriod(2026,9),'Synthetic editor',default_sections(),(block,),sources=(source,),synthetic=True)
    edited, changed = revise_included_page(block,source,1,'caption',caption='Corrected caption',all_sources=(source,))
    ready, current = revise_included_page(edited,changed,1,'review',all_sources=(changed,))
    return replace(draft,blocks=(ready,),sources=(current,)),replace(content,source=current),edited,changed


def status(draft,content):
    return source_manager_status(draft,(content,))[0]


def test_current_caption_review_resolves_display_without_an_extra_scope_override(reviewed):
    draft,content,_,_=reviewed
    assert not content.source.scope_review
    assert not pending_asset_indexes(draft.blocks[0],draft.sources)
    assert document_page_indexes(draft.blocks[0],draft.sources)=={0}
    from app.monthly_report_checks import preflight
    assert not any(check.code == "client_pages" and check.blocking for check in preflight(draft))
    assert status(draft,content).resolved


@pytest.mark.parametrize('change',['pending_caption','asset_receipt','page_receipt','marker','duplicate_marker','duplicate_mapping','duplicate_asset','asset_bytes','wrong_site','old_date','notice','missing_file','unselected','other_source','malformed_reference','missing_block_reference','duplicate_source'])
def test_current_review_bridge_cannot_hide_real_problems(reviewed,change):
    draft,content,edited,changed=reviewed
    block=draft.blocks[0];source=content.source
    if change=='pending_caption':block,source=edited,changed
    elif change=='asset_receipt':block=replace(block,client_asset_reviews=(),client_reviewed_fingerprint='')
    elif change=='page_receipt':source=replace(source,client_page_reviews=())
    elif change in ('marker','duplicate_marker'):
        asset,refs=block.asset_provenance[0]
        markers=tuple(ref for ref in refs if ref.startswith('asset-source-context:'))
        refs=tuple(ref+'x' if ref in markers else ref for ref in refs) if change=='marker' else (*refs,*markers)
        block=replace(block,asset_provenance=((asset,refs),))
    elif change in ('other_source','malformed_reference'):
        asset,refs=block.asset_provenance[0]
        refs=tuple(('different-source'+ref[ref.index(':'):] if change=='other_source' else 'malformed')
                   if not ref.startswith('asset-source-context:') else ref for ref in refs)
        block=replace(block,asset_provenance=((asset,refs),))
    elif change=='missing_block_reference':block=replace(block,references=())
    elif change=='duplicate_mapping':block=replace(block,asset_provenance=block.asset_provenance*2)
    elif change=='duplicate_asset':block=replace(block,asset_hashes=block.asset_hashes*2,asset_captions=block.asset_captions*2)
    elif change=='asset_bytes':block=replace(block,asset_hashes=('0'*64+'.png',))
    elif change in ('wrong_site','old_date'):
        source=replace(source,**({'facility':'Another hospital'} if change=='wrong_site' else {'service_date':'2026-08-04'}))
        block,source=revise_included_page(block,source,1,'review',all_sources=(source,))
    elif change=='notice':source=replace(source,notices=('Original vector object still needs review.',))
    elif change=='missing_file':sources._path(draft.profile,source.sha256,source.suffix).unlink()
    elif change=='unselected':source=replace(source,selected_pages=())
    draft=replace(draft,blocks=(block,),sources=(source,));content=replace(content,source=source)
    if change=='duplicate_source':draft=replace(draft,sources=(source,source))
    assert not status(draft,content).resolved
