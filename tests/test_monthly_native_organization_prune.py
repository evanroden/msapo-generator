"""Organization region removal is a closed, source-derived picture proof."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Inches

from app.monthly_report_compatibility_view import derive_compatibility_view
from app.monthly_report_native_art_scope import expected_header_scope,W,_package,_routing
from app.monthly_report_native_organization_prune import organization_candidates,_picture,A,WP,PIC,R
from app.monthly_report_model import ResolvedBlock,DraftParagraph
from test_monthly_report_source_frame_logo_role import source,raster


def refreshed(path):
    view=derive_compatibility_view(path.read_bytes())
    return path,view,expected_header_scope(view)


def fixture(tmp_path):
    path=source(tmp_path,divergent=True);doc=Document(path)
    doc.add_section();doc.add_heading('ORGANIZATIONAL CHART',1)
    doc.add_section();doc.add_paragraph()
    doc.add_paragraph().add_run().add_picture(BytesIO(raster('orange')),width=Inches(1))
    doc.add_section();doc.add_heading('MONTHLY SCORECARDS',1)
    doc.add_paragraph('Synthetic retained content.')
    doc.add_section();doc.add_heading('TRAINING SUMMARY',1)
    doc.save(path)
    return refreshed(path)


def plan(f,blocks=()):
    return organization_candidates(f[0],f[1],SimpleNamespace(blocks=blocks),f[2])


def test_candidate_is_source_derived(tmp_path):
    f=fixture(tmp_path);c=plan(f)
    assert len(c)==1 and c[0][0]==3
    assert len(c[0][1])==len(c[0][2])==3


@pytest.mark.parametrize('field,value',[('text','Current'),('rows',(('Current',),)),('extra_tables',('table',)),('asset_hashes',('asset',)),('asset_instances',('instance',)),('org_nodes',('node',)),('ai_paragraphs',(DraftParagraph('',(),()),)),('references',('source:synthetic',))])
@pytest.mark.parametrize('key',['org_chart','business_hours_workflow','after_hours_workflow','contact_matrix'])
def test_all_organization_payloads_block_scope(tmp_path,field,value,key):
    assert not plan(fixture(tmp_path),(replace(ResolvedBlock(key,'This month'),**{field:value}),))


@pytest.mark.parametrize('tag',['bookmarkStart','bookmarkEnd','hyperlink','fldSimple','sdt','ins','pict','object','drawing'])
def test_unknown_content_never_erased(tmp_path,tag):
    path,_,_=fixture(tmp_path);d=Document(path)
    n=next(p._p for p in d.paragraphs if p._p.find('.//'+A+'blip') is not None)
    n.append(OxmlElement('w:'+tag));d.save(path)
    from app.monthly_report_compatibility_view import CompatibilityError
    try:
        f=refreshed(path)
    except CompatibilityError:
        return
    assert not plan(f)


@pytest.mark.parametrize('case',['unknown-child','hidden-text','hidden-tail','link','extra-attribute','textbox','duplicate-pic','external','missing-media','wrong-kind','nonrect','unknown-ext'])
def test_picture_grammar_refusals(tmp_path,case):
    f=fixture(tmp_path)
    from app.monthly_report_xml_parser import parse_xml
    with _package(f[0].read_bytes()) as a:
        units,_,_,_=_routing(a);rels={n.get('Id'):n for n in parse_xml(a.read('word/_rels/document.xml.rels'))};names=set(a.namelist())
    draw=deepcopy(next(n for root in units for n in root.iter(W+'drawing') if n.find('.//'+A+'blip') is not None))
    blip=next(draw.iter(A+'blip'));rid=blip.get(R+'embed')
    if case=='unknown-child':draw.append(OxmlElement('w:unknown'))
    elif case=='hidden-text':next(draw.iter(WP+'extent')).text='Hidden'
    elif case=='hidden-tail':next(draw.iter(WP+'extent')).tail='Hidden'
    elif case=='link':blip.set(R+'link','external')
    elif case=='extra-attribute':draw.set('unknown','1')
    elif case=='textbox':next(draw.iter(PIC+'pic')).append(OxmlElement('w:txbxContent'))
    elif case=='duplicate-pic':g=next(draw.iter(A+'graphicData'));g.append(deepcopy(g[0]))
    elif case=='external':rels[rid].set('TargetMode','External')
    elif case=='missing-media':names.clear()
    elif case=='wrong-kind':rels[rid].set('Type',R[1:-1]+'/hyperlink')
    elif case=='nonrect':next(draw.iter(A+'prstGeom')).set('prst','ellipse')
    else:blip.append(OxmlElement('a:extLst'))
    assert not _picture(draw,rels,names)


def test_source_identity_and_partial_scope_refuse(tmp_path):
    f=fixture(tmp_path)
    assert not plan((*f[:2],replace(f[2],section_key='organization')))
    assert not plan((*f[:2],replace(f[2],omitted_sections=('water',))))
    f[0].write_bytes(f[0].read_bytes()+b'changed')
    assert not plan(f)


def output(f):
    from app.monthly_report_native_art_scope import NativeEmissionProof
    from app.monthly_report_native_utility_intro import UtilityDecorationReceipt
    from test_monthly_native_utility_intro import pack
    from lxml import etree
    with _package(f[1].rendition_bytes) as a:
        parts={n:a.read(n) for n in a.namelist()}
        units,_,ends,_=_routing(a)
    owners=[];records=[];section=1
    for position,node in enumerate(units,1):
        owners.append(section);records.append((position,False,False,False))
        if section==3:
            for draw in list(node.iter(W+'drawing')):draw.getparent().remove(draw)
        if position in ends:section+=1
    parts['word/document.xml']=etree.tostring(units[0].getparent().getparent())
    return pack(parts),NativeEmissionProof(f[2].sha256,tuple(owners)),UtilityDecorationReceipt(f[2].sha256,tuple(records))


def candidate(f,blocks=()):
    from app.monthly_report_native_organization_prune import plan_native_unused_sections
    return plan_native_unused_sections(f[0],f[1],SimpleNamespace(blocks=blocks),f[2])


def test_exact_roots_inactive_receipt_and_package_delta(tmp_path):
    f=fixture(tmp_path);c=candidate(f);assert c.source_sections==(3,)
    raw,proof,receipt=output(f)
    fixed,scope,proof=c.apply(raw,proof,set(),decoration_receipt=receipt)
    assert fixed!=raw and len(Document(BytesIO(fixed)).sections)==4
    with _package(raw) as a,_package(fixed) as b:
        assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==['word/document.xml']


@pytest.mark.parametrize('case',['missing','scope','length','position','live','support','heading','detached-live','detached-support','detached-heading','unknown-owner','unknown-position','reserved','text','tail','extra-root'])
def test_inexact_or_active_final_receipt_never_removes(tmp_path,case):
    from test_monthly_native_utility_intro import pack
    from lxml import etree
    f=fixture(tmp_path);c=candidate(f);raw,proof,r=output(f)
    start=f[2].source_section_ends[1];records=list(r.roots)
    if case=='missing':r=None
    elif case=='scope':r=replace(r,scope_sha256='wrong')
    elif case=='length':r=replace(r,roots=r.roots[:-1])
    elif case in ('position','live','support','heading'):
        entry=list(records[start]);entry[{'position':0,'live':1,'support':2,'heading':3}[case]]=True if case!='position' else 1000
        records[start]=tuple(entry);r=replace(r,roots=tuple(records))
    elif case.startswith('detached'):
        bits=tuple(case=='detached-'+key for key in ('live','support','heading'))
        r=replace(r,activities=((3,start+1,*bits),))
    elif case=='unknown-owner':r=replace(r,activities=((None,start+1,True,False,False),))
    elif case=='unknown-position':r=replace(r,activities=((3,None,False,False,False),))
    elif case=='reserved':proof=replace(proof,reserved_source_sections=(3,))
    else:
        with _package(raw) as a:parts={n:a.read(n) for n in a.namelist()}
        root=etree.fromstring(parts['word/document.xml']);node=root.find(W+'body')[start]
        if case=='text':node.text='Hidden'
        elif case=='tail':node.tail='Hidden'
        else:node.append(OxmlElement('w:r'))
        parts['word/document.xml']=etree.tostring(root);raw=pack(parts)
    assert c.apply(raw,proof,set(),decoration_receipt=r)==(raw,f[2],proof)


def test_unknown_root_grammar_directly_refuses_without_normalization(tmp_path):
    from app.monthly_report_native_organization_prune import _empty_picture_root
    from app.monthly_report_xml_parser import parse_xml
    f=fixture(tmp_path)
    with _package(f[0].read_bytes()) as a:
        roots,_,_,_=_routing(a);rels={n.get('Id'):n for n in parse_xml(a.read('word/_rels/document.xml.rels'))};names=set(a.namelist())
    target=roots[8]
    assert _empty_picture_root(target,rels,names)
    for tag in ('bookmarkStart','bookmarkEnd','hyperlink','sdt','ins','pict','object','fldSimple'):
        n=deepcopy(target);n.append(OxmlElement('w:'+tag))
        assert _empty_picture_root(n,rels,names) is None


def test_saved_reopened_public_builder_uses_real_ownership(tmp_path,monkeypatch):
    from unittest.mock import patch
    from app import monthly_report_library as library
    from app import monthly_report_native_organization_prune as cleanup
    from app.monthly_report_native_layout import build_native_docx
    from test_monthly_report_native_art_review import setup
    from test_monthly_report_native_art_lifecycle import save_sample
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'store'))
    path,_,_=fixture(tmp_path)
    doc=Document(path)
    for index in (2,3):doc.sections[index].header.is_linked_to_previous=False
    doc.sections[2].header.paragraphs[0].add_run().add_picture(BytesIO(raster('blue')),width=Inches(1))
    doc.save(path);sample=setup(path)
    path,view,profile,period,inventory,review=sample
    saved,loader=save_sample(sample)
    draft=library.load_imported_draft(profile.contract,profile.key,source_view=view)
    assert draft==saved
    draft=replace(draft,blocks=tuple(b for b in draft.blocks if b.key not in ('org_chart','business_hours_workflow','after_hours_workflow','contact_matrix')))
    before=path.read_bytes();fingerprint=draft.fingerprint
    with patch.object(cleanup,'organization_candidates',lambda *args:()):
        baseline=build_native_docx(draft,path,asset_loader=loader,source_view=view)
    fixed=build_native_docx(draft,path,asset_loader=loader,source_view=view)
    assert len(Document(BytesIO(baseline)).sections)==5
    assert len(Document(BytesIO(fixed)).sections)==4
    with _package(baseline) as a,_package(fixed) as b:
        assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==['word/document.xml']
    assert draft.fingerprint==fingerprint and path.read_bytes()==before
    for field,value in [('text','Synthetic current organization.'),('references',('source:synthetic',)),('ai_paragraphs',(DraftParagraph('',(),()),))]:
        live=replace(draft,blocks=(*draft.blocks,replace(ResolvedBlock('org_chart','This month'),**{field:value})))
        raw=build_native_docx(live,path,asset_loader=loader,source_view=view)
        assert len(Document(BytesIO(raw)).sections)==5
