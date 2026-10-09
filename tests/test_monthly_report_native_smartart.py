from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from dataclasses import replace
from lxml import etree as E
from docx import Document
from docx.oxml.ns import qn
import pytest

from test_monthly_report_smartart import smartart_doc, ROOTS
from app.monthly_report_import import inspect_docx, map_items, ImportMapping
from app.monthly_report_model import ReportDraft, ReportProfile, ReportPeriod, Facility, ResolvedBlock, default_sections
from app.monthly_report_native_layout import build_native_docx


def native_smartart(tmp_path, *, invalid=None, heading=False):
    path = smartart_doc(tmp_path, model_text='Synthetic leader Secret old contact' if invalid else 'Synthetic leader')
    with ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = E.fromstring(parts['word/document.xml']);body=root.find(qn('w:body'));paragraph=body[1]
    graphic = paragraph.find('.//' + qn('a:graphicData'));run=graphic.getparent();run.remove(graphic)
    drawing=E.SubElement(run,qn('w:drawing'));inline=E.SubElement(drawing,qn('wp:inline'))
    E.SubElement(inline,qn('wp:extent'),cx='1000000',cy='1000000')
    E.SubElement(inline,qn('wp:docPr'),id='20',name='Current diagram')
    E.SubElement(inline,qn('a:graphic')).append(graphic)
    E.SubElement(E.SubElement(paragraph,qn('w:r')),qn('w:t')).text='Organizational Chart' if heading else 'Current neighboring caption'
    parts['word/document.xml']=E.tostring(root)
    types=E.fromstring(parts['[Content_Types].xml'])
    for kind in ROOTS:
        E.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                     PartName='/word/diagrams/'+kind+'.xml',ContentType='application/xml')
    parts['[Content_Types].xml']=E.tostring(types)
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)
    return path


@pytest.mark.parametrize('mode',['mapped','omitted','changed','invalid','heading','textbox'])
def test_smartart_requires_explicit_complete_current_text(tmp_path,mode):
    path=native_smartart(tmp_path,invalid='image' if mode=='invalid' else None,heading=mode=='heading')
    if mode=='textbox':
        with ZipFile(path)as z:parts={n:z.read(n)for n in z.namelist()}
        root=E.fromstring(parts['word/document.xml'])
        drawing=root.find('.//' + qn('w:drawing'))
        textbox=E.SubElement(drawing,qn('w:txbxContent'))
        E.SubElement(textbox,qn('w:p'))
        parts['word/document.xml']=E.tostring(root)
        with ZipFile(path,'w',ZIP_DEFLATED)as z:
            for n,b in parts.items():z.writestr(n,b)
    inspection=inspect_docx(path)
    choices=[i for i in inspection.items if i.position==2 and i.kind=='text'
             and (mode=='mapped' or i.note!='Validated native SmartArt text')]
    if mode=='changed':choices=[i for i in inspection.items if i.position==2 and i.kind=='text']
    blocks=(ResolvedBlock('org_chart','This month',text='\n\n'.join(i.text for i in choices),
                          references=tuple(f'docx:{inspection.sha256}:{i.id}'for i in choices)),)
    if mode=='changed':blocks=tuple(replace(b,text=b.text.replace('Synthetic leader','New current leader'))for b in blocks)
    draft=ReportDraft(ReportProfile('Current contract','site','Current site',(Facility('site','Current site'),)),
                      ReportPeriod(2026,9),'Current editor',default_sections(),blocks)
    raw=build_native_docx(draft,path)
    with ZipFile(BytesIO(raw))as z:
        text=b'\n'.join(z.read(n)for n in z.namelist()if n.endswith('.xml'))
        assert (b'Synthetic leader' in text)==(mode=='mapped')
        assert (b'relIds' in z.read('word/document.xml'))==(mode=='mapped')
        if mode=='changed':assert b'New current leader' in text


@pytest.mark.parametrize('scope',['cover','header'])
def test_unmapped_smartart_cannot_survive_in_page_chrome(tmp_path,scope):
    path=native_smartart(tmp_path)
    with ZipFile(path)as z:parts={n:z.read(n)for n in z.namelist()}
    root=E.fromstring(parts['word/document.xml']);body=root.find(qn('w:body'));paragraph=body[1];body.remove(paragraph)
    if scope=='cover':body.insert(0,paragraph)
    else:
        header=E.Element(qn('w:hdr'));header.append(paragraph);parts['word/header99.xml']=E.tostring(header)
        rels=E.fromstring(parts['word/_rels/document.xml.rels'])
        diagram_rels=E.Element(rels.tag,nsmap=rels.nsmap)
        from copy import deepcopy
        for rel in rels:
            if 'diagram' in rel.get('Type','').casefold():diagram_rels.append(deepcopy(rel))
        parts['word/_rels/header99.xml.rels']=E.tostring(diagram_rels)
        E.SubElement(rels,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                     Id='rHeader99',Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/header',Target='header99.xml')
        parts['word/_rels/document.xml.rels']=E.tostring(rels)
        properties=body.find(qn('w:sectPr'))
        E.SubElement(properties,qn('w:headerReference'),{qn('w:type'):'default',qn('r:id'):'rHeader99'})
        types=E.fromstring(parts['[Content_Types].xml'])
        E.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                     PartName='/word/header99.xml',ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml')
        parts['[Content_Types].xml']=E.tostring(types)
    parts['word/document.xml']=E.tostring(root)
    with ZipFile(path,'w',ZIP_DEFLATED)as z:
        for n,b in parts.items():z.writestr(n,b)
    draft=ReportDraft(ReportProfile('New contract','site','New site',(Facility('site','New site'),)),
                     ReportPeriod(2026,9),'Current editor',default_sections(),())
    with ZipFile(BytesIO(build_native_docx(draft,path,master=True)))as z:
        assert not any(n.startswith('word/diagrams/')for n in z.namelist())
        assert not any(b'Synthetic leader'in z.read(n)for n in z.namelist()if n.endswith('.xml'))


def test_raster_frame_replacement_does_not_copy_neighboring_smartart():
    from PIL import Image
    from app.monthly_report_native_layout import _replace_image
    data=BytesIO();Image.new('RGB',(20,20),'navy').save(data,format='PNG')
    doc=Document();picture=doc.add_picture(BytesIO(data.getvalue()))
    paragraph=picture._inline.getparent().getparent()
    graphic=E.SubElement(picture._inline,qn('a:graphic'))
    content=E.SubElement(graphic,qn('a:graphicData'))
    E.SubElement(content,'{http://schemas.openxmlformats.org/drawingml/2006/diagram}relIds',
                 {qn('r:dm'):'old-diagram'})
    _replace_image(doc,paragraph,data.getvalue())
    assert not list(paragraph.iter('{http://schemas.openxmlformats.org/drawingml/2006/diagram}relIds'))
    assert len(doc.inline_shapes)==1
