"""Reviewed standing contract branding supplies bytes, never pixel equivalence."""
from dataclasses import replace

from app import monthly_report_branding as branding, monthly_report_library as library
from app.monthly_report_compatibility_view import derive_compatibility_view
from app.monthly_report_import import imported_draft
from app.monthly_report_model import Facility, ReportPeriod, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_start_import import automatic_section_plans, build_starting_import, StartingReportAnalysis
from test_monthly_report_source_frame_logo_role import source, raster
from test_monthly_report_source_view_lifecycle import _body_images


def test_exact_saved_contract_logo_reused_without_source_identity_or_new_am_choice(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'store'))
    original=source(tmp_path,divergent=True)
    before=original.read_bytes();view=derive_compatibility_view(before)
    profile=replace(synthetic_profiles()[0],imported_from=view.original_inspection.sha256,
                    title='Synthetic Regional Community Health Hospital',
                    facilities=(Facility('synthetic','Synthetic Regional Community Health Hospital'),))
    purple=raster('purple');yellow=raster('yellow')
    reference=library.asset_reference(purple,'png');other_ref=library.asset_reference(yellow,'png')
    # Similar display names do not establish association; exact contract map does.
    chosen=branding.BrandLogo('target','Synthetic shared artwork',(profile.contract,),reference,
                               'https://example.invalid/source','https://example.invalid/asset.png','2026-10-07')
    other=replace(chosen,key='other',contracts=('Other synthetic contract',),asset=other_ref)
    branding.save_branding((other,chosen),{reference:purple,other_ref:yellow},expected_revision=0,
                           actor='Synthetic registry reviewer',confirmed=True)
    assert branding.find_logo(profile.contract)==chosen
    assert branding.find_logo('Unknown synthetic contract') is None
    plans=automatic_section_plans(view.original_inspection,StartingReportAnalysis((),'same',(),(),()),
                                   preferred_logos=('client_logo',),source_view=view)
    assert all(plan['approved'] for plan in plans.values())
    mapped,_=build_starting_import(original,view.original_inspection,tuple(plans.values()),source_view=view)
    draft=imported_draft(profile,ReportPeriod(2026,9),'Synthetic Editor',mapped)
    assets=dict(mapped.assets)
    draft=branding.apply_defaults(draft,assets)
    logo=next(b for b in draft.blocks if b.key=='client_logo')
    assert logo.asset_hashes==(reference,)
    assert not logo.references  # Saved contract artwork is not a source equality assertion.
    assert logo.client_asset_reviews
    assert all(i.image_digest!=reference.removesuffix('.png') for i in view.original_inspection.items if i.kind=='image')
    library.save_profile(profile,expected_revision=0,actor='Synthetic Editor',confirmed=True)
    library.save_report_setup(profile,draft,original,{'sha256':profile.imported_from,'period':draft.period.key},
        assets=tuple(assets.items()),source_draft=draft,source_view=view,expected_revision=1,
        actor='Synthetic Editor',confirmed=True)
    reloaded=library.load_imported_draft(profile.contract,profile.key,source_view=view)
    load=lambda key:library.read_asset(profile.contract,profile.key,key)
    output=build_native_docx(reloaded,original,asset_loader=load,source_view=view)
    assert _body_images(output)==(purple,raster())
    assert original.read_bytes()==before
    # Refreshing the registry cannot mutate this report's pinned reviewed copy.
    blue=raster('blue');blue_ref=library.asset_reference(blue,'png')
    branding.save_branding((replace(chosen,asset=blue_ref),other),{blue_ref:blue},expected_revision=1,
                           actor='Synthetic next reviewer',confirmed=True)
    assert branding.apply_defaults(reloaded,{})==reloaded
    assert _body_images(build_native_docx(reloaded,original,asset_loader=load,source_view=view))[0]==purple
    omitted=replace(reloaded,blocks=tuple(replace(b,source='Omit',asset_hashes=(),references=())
                        if b.key=='client_logo' else b for b in reloaded.blocks))
    assert branding.apply_defaults(omitted,{})==omitted
    assert _body_images(build_native_docx(omitted,original,asset_loader=load,source_view=view))==(raster(),)
