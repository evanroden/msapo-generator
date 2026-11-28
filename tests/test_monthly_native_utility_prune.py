"""A reduced scope must be derived before output, never from missing regions."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile,ZIP_DEFLATED
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from app.monthly_report_compatibility_view import derive_compatibility_view
from app.monthly_report_native_art_scope import expected_header_scope,NativeEmissionProof,verify_header_routing,W
from app.monthly_report_native_utility_prune import plan_utility_section_prune,_empty_signature
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_source_frame_logo_role import source


def fixture(tmp_path):
    p=source(tmp_path,divergent=True)
    d=Document(p)
    d.add_section()
    d.add_heading('MONTHLY SCORECARDS',1)
    d.add_section()
    d.add_paragraph('Rate-trend reporting is pending implementation; no current utility report is included.')
    d.add_section()
    d.add_heading('TRAINING SUMMARY',1)
    d.add_paragraph('Synthetic completed training.')
    d.add_section()
    d.add_heading('CAPITAL PROJECTS',1)
    d.add_paragraph('Synthetic project.')
    d.save(p)
    v=derive_compatibility_view(p.read_bytes());s=expected_header_scope(v)
    return p,v,s


def plan(fixture,blocks=()):
    p,v,s=fixture
    return plan_utility_section_prune(p,v,SimpleNamespace(blocks=blocks),s)


def cleared(view,scope):
    from app.monthly_report_native_layout import _set_text
    with ZipFile(BytesIO(view.rendition_bytes)) as z:parts={n:z.read(n) for n in z.namelist()}
    root=etree.fromstring(parts['word/document.xml']);body=root.find(W+'body');owners=[];region=1
    for node in body:
        owners.append(region)
        boundary=node.tag==W+'sectPr' or node.find('.//'+W+'sectPr') is not None
        text=''.join(t.text or '' for t in node.iter(W+'t'))
        if region==3 and text.strip():
            _set_text(node,'');pr=node.find(W+'pPr')
            if pr is not None:
                num=OxmlElement('w:numPr');n=OxmlElement('w:numId');n.set(W+'val','0');num.append(n);pr.append(num)
        if boundary:region+=1
    parts['word/document.xml']=etree.tostring(root)
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)
    return stream.getvalue(),NativeEmissionProof(scope.sha256,tuple(owners))


def test_positive_scope_and_exact_output(tmp_path):
    f=fixture(tmp_path);p,v,s=f;candidate=plan(f)
    assert candidate is not None and candidate.source_sections==(3,)
    raw,proof=cleared(v,s);out,reduced,receipt=candidate.apply(raw,proof,set())
    assert out!=raw and reduced.source_word_sections==(1,2,4,5)
    verify_header_routing(out,reduced,emission_proof=receipt)
    with pytest.raises(ValueError):verify_header_routing(out,s)
    assert len(Document(BytesIO(out)).sections)==4
    with ZipFile(BytesIO(raw)) as a,ZipFile(BytesIO(out)) as b:
        assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==['word/document.xml']


@pytest.mark.parametrize('field,value',[('text','Current'),('rows',(('Current',),)),('extra_tables',('table',)),('asset_hashes',('asset',)),('asset_instances',('occurrence',)),('org_nodes',('node',))])
def test_any_current_utility_payload_blocks_scope(tmp_path,field,value):
    assert plan(fixture(tmp_path),(replace(ResolvedBlock('utility_analysis','This month'),**{field:value}),)) is None


@pytest.mark.parametrize('tag',['bookmarkStart','fldSimple','sdt','drawing','hyperlink','ins','pStyle','numPr'])
def test_unknown_original_grammar_not_erased_into_permission(tmp_path,tag):
    p,_,_=fixture(tmp_path);d=Document(p);n=next(p for p in d.paragraphs if p.text.startswith('Rate-trend'))
    n._p.append(OxmlElement('w:'+tag));d.save(p)
    v=derive_compatibility_view(p.read_bytes());s=expected_header_scope(v)
    assert plan((p,v,s)) is None


@pytest.mark.parametrize('transition',['continuous','oddPage','evenPage','nextColumn'])
def test_non_nextpage_source_transition_blocks_scope(tmp_path,transition):
    p,_,_=fixture(tmp_path);d=Document(p);props=d.sections[2]._sectPr
    typ=props.find(W+'type')
    if typ is None:typ=OxmlElement('w:type');props.insert(0,typ)
    typ.set(W+'val',transition);d.save(p);v=derive_compatibility_view(p.read_bytes());s=expected_header_scope(v)
    assert plan((p,v,s)) is None


def test_active_or_uncleared_region_is_retained(tmp_path):
    f=fixture(tmp_path);_,v,s=f;c=plan(f);raw,proof=cleared(v,s)
    assert c.apply(raw,proof,{3})==(raw,s,proof)
    with ZipFile(BytesIO(raw)) as z:parts={n:z.read(n) for n in z.namelist()}
    root=etree.fromstring(parts['word/document.xml']);node=root.find(W+'body')[s.source_section_ends[1]]
    node.append(OxmlElement('w:drawing'));parts['word/document.xml']=etree.tostring(root)
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)
    changed=stream.getvalue();assert c.apply(changed,proof,set())==(changed,s,proof)


def test_source_hash_change_refuses_scope(tmp_path):
    f=fixture(tmp_path);p,v,s=f;p.write_bytes(p.read_bytes()+b'changed');assert plan(f) is None


def test_preview_or_omission_never_gets_prune_scope(tmp_path):
    p,v,s=fixture(tmp_path)
    assert plan((p,v,replace(s,section_key='scorecards'))) is None
    assert plan((p,v,replace(s,omitted_sections=('water',)))) is None


def test_real_public_builder_saved_reopened_prunes_only_unused_region(tmp_path,monkeypatch):
    from app.monthly_report_native_layout import build_native_docx
    from app import monthly_report_library as library
    from app.monthly_report_native_art_review import verify_native_art_output,verify_native_art_review
    from test_monthly_report_native_art_review import setup
    from test_monthly_report_native_art_lifecycle import save_sample
    from test_monthly_report_source_frame_logo_role import raster
    from unittest.mock import patch
    from app import monthly_report_native_utility_prune as cleanup
    from docx.shared import Inches
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'store'))
    path,_,_=fixture(tmp_path);d=Document(path)
    # Distinct native art is visible ONLY in the candidate physical region.
    for index in (2,3):d.sections[index].header.is_linked_to_previous=False
    d.sections[2].header.paragraphs[0].add_run().add_picture(BytesIO(raster('orange')),width=Inches(1))
    d.save(path);sample=setup(path);path,view,profile,period,inventory,review=sample
    saved,loader=save_sample(sample)
    draft=library.load_imported_draft(profile.contract,profile.key,source_view=view)
    assert draft==saved
    draft=replace(draft,blocks=tuple(b for b in draft.blocks if b.key!='utility_analysis'))
    before=path.read_bytes();fingerprint=draft.fingerprint
    with patch.object(cleanup.UtilitySectionPrune,'apply',lambda self,raw,proof,active:(raw,self.full_scope,proof)):
        base=build_native_docx(draft,path,asset_loader=loader,source_view=view)
    fixed=build_native_docx(draft,path,asset_loader=loader,source_view=view)
    assert len(Document(BytesIO(base)).sections)==5
    assert len(Document(BytesIO(fixed)).sections)==4
    c=plan_utility_section_prune(path,view,draft,expected_header_scope(view));assert c is not None
    context=verify_native_art_review(path,view,profile,period,review)
    # Full original contract is still exact and refuses reduced output.
    with pytest.raises(ValueError):verify_native_art_output(fixed,context,source_scope=c.full_scope)
    # The art part remains unmodified in package; only its preselected page is absent.
    with ZipFile(BytesIO(base)) as a,ZipFile(BytesIO(fixed)) as b:
        assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==['word/document.xml']
    assert path.read_bytes()==before and draft.fingerprint==fingerprint
    # Current utility content must retain all five regions through the same API.
    live=replace(draft,blocks=(*draft.blocks,ResolvedBlock('utility_analysis','This month',text='Synthetic current rate analysis.')))
    current=build_native_docx(live,path,asset_loader=loader,source_view=view)
    assert len(Document(BytesIO(current)).sections)==5
    assert 'Synthetic current rate analysis.' in '\n'.join(p.text for p in Document(BytesIO(current)).paragraphs)


@pytest.mark.parametrize('case',['duplicate-pPr','nested-rPr','nested-format','hidden-property-text','hidden-tail'])
def test_malformed_plain_markup_is_not_proof(tmp_path,case):
    p,_,_=fixture(tmp_path);d=Document(p);n=next(p for p in d.paragraphs if p.text.startswith('Rate-trend'))._p
    if case=='duplicate-pPr':n.insert(0,OxmlElement('w:pPr'));n.insert(0,OxmlElement('w:pPr'))
    elif case=='nested-rPr':n.get_or_add_pPr().append(OxmlElement('w:rPr'));n.find(W+'pPr/'+W+'rPr').append(OxmlElement('w:rPr'))
    elif case=='nested-format':
        a=OxmlElement('w:color');a.append(OxmlElement('w:color'));n.get_or_add_pPr().append(a)
    elif case=='hidden-property-text':n.get_or_add_pPr().text='Synthetic hidden text'
    else:n[0].tail='Synthetic hidden tail'
    d.save(p);v=derive_compatibility_view(p.read_bytes());assert plan((p,v,expected_header_scope(v))) is None


def test_removed_header_inheritance_cannot_change_retained_route(tmp_path):
    p,_,_=fixture(tmp_path);d=Document(p)
    d.sections[2].header.is_linked_to_previous=False
    d.sections[2].header.paragraphs[0].text='Synthetic inherited heading'
    d.save(p);v=derive_compatibility_view(p.read_bytes());assert plan((p,v,expected_header_scope(v))) is None


@pytest.mark.parametrize('case',['page-width','header-distance','extra-boundary','wrong-proof','missing-owner'])
def test_full_and_reduced_scopes_reject_unproved_mutations(tmp_path,case):
    f=fixture(tmp_path);_,v,s=f;c=plan(f);raw,proof=cleared(v,s)
    fixed,reduced,receipt=c.apply(raw,proof,set())
    with ZipFile(BytesIO(fixed)) as z:parts={n:z.read(n) for n in z.namelist()}
    root=etree.fromstring(parts['word/document.xml']);body=root.find(W+'body');props=body.find('.//'+W+'sectPr')
    if case=='page-width':props.find(W+'pgSz').set(W+'w','15000')
    elif case=='header-distance':props.find(W+'pgMar').set(W+'header','999')
    elif case=='extra-boundary':
        p=OxmlElement('w:p');pr=OxmlElement('w:pPr');pr.append(deepcopy(props));p.append(pr);body.insert(0,p)
    elif case=='wrong-proof':receipt=replace(receipt,scope_sha256=s.sha256)
    else:receipt=replace(receipt,source_word_sections_by_unit=receipt.source_word_sections_by_unit[1:])
    parts['word/document.xml']=etree.tostring(root);stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)
    with pytest.raises(ValueError):verify_header_routing(stream.getvalue(),reduced,emission_proof=receipt)


@pytest.mark.parametrize('target',['text','boundary','extra-root'])
def test_final_root_signature_must_match_precomputed_empty(tmp_path,target):
    f=fixture(tmp_path);_,v,s=f;c=plan(f);raw,proof=cleared(v,s)
    with ZipFile(BytesIO(raw)) as z:parts={n:z.read(n) for n in z.namelist()}
    root=etree.fromstring(parts['word/document.xml']);body=root.find(W+'body');positions=[i for i,o in enumerate(proof.source_word_sections_by_unit) if o==3]
    if target=='text':body[positions[0]].find('.//'+W+'t').text='Synthetic unexpected content'
    elif target=='boundary':body[positions[-1]].set(W+'rsidR','different')
    else:
        body.insert(positions[0],OxmlElement('w:p'))
        owners=list(proof.source_word_sections_by_unit);owners.insert(positions[0],3)
        proof=replace(proof,source_word_sections_by_unit=tuple(owners))
    parts['word/document.xml']=etree.tostring(root);stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)
    changed=stream.getvalue();assert c.apply(changed,proof,set())==(changed,s,proof)


def test_duplicate_utility_blocks_and_wrong_destination_refuse(tmp_path):
    f=fixture(tmp_path)
    assert plan(f,(ResolvedBlock('utility_analysis','Omit'),ResolvedBlock('utility_analysis','Omit'))) is None
    p,v,s=f
    items=tuple(replace(i,suggested_slot='activity_summary') if i.position==8 else i for i in v.original_inspection.items)
    v=replace(v,original_inspection=replace(v.original_inspection,items=items))
    assert plan((p,v,s)) is None
