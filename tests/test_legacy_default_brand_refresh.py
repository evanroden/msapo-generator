from dataclasses import replace
from io import BytesIO
import pytest
from PIL import Image
from app import monthly_report_branding as branding
from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import ResolvedBlock


def logo(color):
    data=BytesIO();Image.new('RGBA',(500,80),color).save(data,'PNG');raw=data.getvalue()
    ref=library.asset_reference(raw,'png')
    return branding.BrandLogo('enfra','ENFRA',(),ref,'https://example.com','https://example.com/logo.png','2026-10-22'),raw


def setup(monkeypatch,tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'store'))
    old,oldraw=logo('red');new,newraw=logo('green')
    branding.save_branding((old,),{old.asset:oldraw},expected_revision=0,actor='Synthetic',confirmed=True)
    branding.save_branding((new,),{new.asset:newraw},expected_revision=1,actor='Synthetic',confirmed=True)
    return old,new,newraw


def test_only_exact_previous_default_refreshes_from_proved_current_source(monkeypatch,tmp_path):
    old,new,newraw=setup(monkeypatch,tmp_path)
    block=approve_all_assets(ResolvedBlock('brand_logo','Library',asset_hashes=(old.asset,)))
    assets={};result=branding.refresh_proven_prior_default_brand(block,(new.asset,),assets)
    assert result.asset_hashes==(new.asset,) and result.source=='Library' and assets[new.asset]==newraw
    assert block.asset_hashes==(old.asset,)
    assert branding.load_branding().revision==2
    unchanged={};assert branding.refresh_proven_prior_default_brand(result,(new.asset,),unchanged)==result
    assert not unchanged


@pytest.mark.parametrize('change',['custom','omit','annotated','unproved','wrong_old','multiple','no_block'])
def test_explicit_or_unproved_logo_never_auto_changes(monkeypatch,tmp_path,change):
    old,new,_=setup(monkeypatch,tmp_path)
    block=approve_all_assets(ResolvedBlock('brand_logo','Library',asset_hashes=(old.asset,)))
    proof=(new.asset,)
    if change=='custom':block=replace(block,source='Replace once')
    if change=='omit':block=replace(block,source='Omit')
    if change=='annotated':block=replace(block,references=('manual:choice',))
    if change=='unproved':proof=()
    if change=='wrong_old':block=approve_all_assets(ResolvedBlock('brand_logo','Library',asset_hashes=('a'*64+'.png',)))
    if change=='multiple':block=replace(block,asset_hashes=(old.asset,old.asset))
    if change=='no_block':block=None
    assets={};assert branding.refresh_proven_prior_default_brand(block,proof,assets)==block
    assert not assets


def test_pending_preview_uses_proved_default_without_mutating_open_report(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from app import monthly_report_section_ui as ui
    from app.monthly_report_model import Facility,ReportDraft,ReportPeriod,ReportProfile,default_sections
    old,new,newraw=setup(monkeypatch,tmp_path)
    oldblock=approve_all_assets(ResolvedBlock('brand_logo','Library',asset_hashes=(old.asset,)))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),));period=ReportPeriod(2026,10)
    draft=ReportDraft(profile,period,'Tester',default_sections(),(oldblock,),synthetic=True)
    state=SimpleNamespace(profile=profile);digest='d'*64
    prefix='report_setup_'+ui._signature((profile.contract,profile.key,period.key));active='unit_scope'
    memory={prefix+'_stage':('source',tmp_path/'unused',SimpleNamespace(sha256=digest)),
            prefix+'_active_section_review':(digest,active),
            active+'_section_plans':{'cover':{'omit':True,'automatic_identical_cover_reuse':True,'automatic_brand_identity_refs':(new.asset,)}}}
    monkeypatch.setattr(ui.st,'session_state',memory);monkeypatch.setattr(ui.st,'caption',lambda *_:None)
    assets={};preview,preview_assets=ui.render_pending_cover_selection(draft,assets,profile.contract,period,state)
    assert next(b for b in preview.blocks if b.key=='brand_logo').asset_hashes==(new.asset,)
    assert preview_assets[new.asset]==newraw and not assets
    assert next(b for b in draft.blocks if b.key=='brand_logo').asset_hashes==(old.asset,)


def test_missing_history_fails_closed_without_losing_existing_logo(monkeypatch,tmp_path):
    old,new,_=setup(monkeypatch,tmp_path)
    block=approve_all_assets(ResolvedBlock('brand_logo','Library',asset_hashes=(old.asset,)))
    (branding._path()/'history'/'00000001.json').unlink()
    assets={};assert branding.refresh_proven_prior_default_brand(block,(new.asset,),assets)==block
    assert not assets
