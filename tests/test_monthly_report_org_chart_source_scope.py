"""Publication may not discard a source-site admission blocker."""
from dataclasses import replace
import pytest
from app import monthly_report_org_chart_defaults as charts
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportSource
from app.monthly_report_source_scope import correct_scope
from test_monthly_report_org_chart_defaults import scopes, fresh, picture, with_chart


def source_chart(profile, facility='', correction=()):
    source=ReportSource('a'*64,'synthetic-site-chart.pdf','b'*64,'.pdf',facility=facility,
        page_texts=('Synthetic reporting chart.',),selected_pages=(1,))
    source=replace(source,client_page_reviews=((1,page_fingerprint(source,1)),))
    if correction:source=correct_scope(source,profile,correction)
    block,assets=picture('red');ref=f'{source.id}:1:{source.fingerprint}'
    block=replace(block,references=(ref,),asset_provenance=((block.asset_hashes[0],(ref,)),))
    block=approve_all_assets(refresh_asset_source_context(block,(source,)))
    return replace(with_chart(fresh(profile),block),sources=(source,)),block,assets


def storage_bytes():
    from app import monthly_report_library as library
    return {str(p.relative_to(library._root())):p.read_bytes() for p in library._root().rglob('*') if p.is_file()}

@pytest.mark.parametrize('case',['foreign','unknown','stale','other_contract','other_site','multi_unknown','foreign_corrected','contract_artwork'])
def test_rejects_unadmitted_source_without_any_storage_write(scopes,case):
    a1,a2,b1,multi=scopes;p=multi if case=='multi_unknown' else a1
    d,block,assets=source_chart(p,'Foreign Site' if case in ('foreign','foreign_corrected') else '')
    source=d.sources[0]
    if case=='stale':source=replace(correct_scope(source,p,('a1',)),sha256='c'*64)
    if case=='other_contract':source=correct_scope(source,b1,('a1',))
    if case=='other_site':source=correct_scope(source,a2,('a2',))
    if case=='foreign_corrected':source=correct_scope(source,p,('a1',))
    if case=='contract_artwork':source=correct_scope(source,p,contract_artwork=True,artwork_keys=('business_hours_workflow',))
    d=replace(d,sources=(source,))
    before=storage_bytes()
    with pytest.raises(ValueError):
        charts.save_default(d,block,assets,scope='contract',expected_revision=0,expected_fingerprint=block.fingerprint,confirmed=True)
    assert storage_bytes()==before
    assert not charts._path(p.contract).exists()

@pytest.mark.parametrize('case',['known','alias','corrected','multi_corrected'])
def test_valid_source_admission_still_allows_explicit_publication(scopes,case):
    a1,_,_,multi=scopes;p=multi if case=='multi_corrected' else a1
    if case=='alias':p=replace(p,facilities=(replace(p.facilities[0],aliases=('Exact Alias',)),))
    # Keep fixture's profile object aligned while using the existing library.
    d,b,a=source_chart(p,'Exact Alias' if case=='alias' else 'A1' if case=='known' else '',
                        ('a1','a2') if case=='multi_corrected' else ('a1',) if case=='corrected' else ())
    d=replace(d,profile=p)
    assert charts.save_default(d,b,a,scope='contract',expected_revision=0,expected_fingerprint=b.fingerprint,confirmed=True).revision==1

@pytest.mark.parametrize('facility',['','Foreign Site'])
def test_structured_chart_cannot_launder_source_site_scope(scopes,facility):
    from app.monthly_report_model import OrgChartNode
    a1,_,_,_=scopes;d,b,a=source_chart(a1,facility)
    b=replace(b,asset_hashes=(),asset_provenance=(),client_asset_reviews=(),org_nodes=(OrgChartNode('lead','Synthetic Lead'),))
    d=with_chart(d,b);before=storage_bytes()
    with pytest.raises(ValueError):
        charts.save_default(d,b,{},scope='contract',expected_revision=0,expected_fingerprint=b.fingerprint,confirmed=True)
    assert storage_bytes()==before


def test_native_pending_save_rechecks_scope_and_allows_corrected_retry(scopes):
    from test_monthly_report_org_chart_defaults_ui import start,button
    a1,_,_,_=scopes;d,b,a=source_chart(a1,'A1')
    app=start(d,a);app.checkbox[0].check().run();button(app,'Publish chart default').click()
    source=replace(d.sources[0],facility='Foreign Site')
    # The pending action is not authority to retain the former source admission.
    app.session_state['draft']=replace(d,sources=(source,))
    before=storage_bytes();app.run()
    assert not app.exception and any('scope' in warning.value for warning in app.warning)
    assert storage_bytes()==before
    app.run();assert button(app,'Publish chart default').disabled
    corrected=correct_scope(replace(source,facility=''),a1,('a1',))
    block=approve_all_assets(refresh_asset_source_context(b,(corrected,)))
    current=replace(with_chart(d,block),sources=(corrected,))
    app.session_state['draft']=current;app.run()
    # Content-bound confirmation can require a new click after source changes.
    app.checkbox[0].check().run();assert not button(app,'Publish chart default').disabled
    button(app,'Publish chart default').click().run()
    assert not app.exception and charts.load_defaults(a1.contract).revision==1
