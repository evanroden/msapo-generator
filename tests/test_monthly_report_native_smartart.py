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
