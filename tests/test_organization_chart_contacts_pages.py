"""The current organization chart must not share its page with contacts."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches
from PIL import Image
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, OrgChartNode, ReportTable, default_sections
from app.monthly_report_native_layout import build_native_docx


def test_current_chart_and_contacts_have_explicit_page_separation(tmp_path):
    d = Document(); d.add_heading('ORGANIZATIONAL CHART', 1)
    img = BytesIO(); Image.new('RGB',(1200,600),'blue').save(img,format='PNG')
    d.add_picture(BytesIO(img.getvalue()),width=Inches(6))
    t=d.add_table(rows=2,cols=5)
    for i,s in enumerate(('Site','Role','Name','Telephone','Email')):
        t.cell(0,i).text=s; t.cell(1,i).text='obsolete'
    p=tmp_path/'synthetic.docx'; d.save(p)
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    chart=ResolvedBlock('org_chart','This month',org_nodes=(OrgChartNode('mgr','Synthetic Manager','Manager'), OrgChartNode('staff','Synthetic Staff','Engineer','mgr')))
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(('Site','Role','Name','Telephone','Email'),(('North','Lead','Synthetic Person','555','x@invalid'),),'synthetic:contacts'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(chart,contacts),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,p,section_key='organization',master=True)))
    body=list(result.element.body)
    chart_i=next(i for i,e in enumerate(body) if e.xpath('.//*[local-name()="blip"]'))
    table_i=next(i for i,e in enumerate(body) if e.tag==qn('w:tbl') and 'Synthetic Person' in ''.join(e.itertext()))
    assert chart_i<table_i
    assert any(e.xpath('.//*[local-name()="pageBreakBefore"]') or e.xpath('.//*[local-name()="br" and @w:type="page"]') for e in body[chart_i+1:table_i+1])


def test_source_bound_existing_chart_also_precedes_separate_contact_page(tmp_path):
    from hashlib import sha256
    from app.monthly_report_import import inspect_docx, read_import_image
    d=Document();d.add_heading('ORGANIZATIONAL CHART',1)
    image=BytesIO();Image.new('RGB',(1200,600),'blue').save(image,format='PNG')
    d.add_picture(BytesIO(image.getvalue()),width=Inches(6))
    t=d.add_table(rows=2,cols=5)
    for i,s in enumerate(('Site','Role','Name','Telephone','Email')):
        t.cell(0,i).text=s;t.cell(1,i).text='obsolete'
    p=tmp_path/'source.docx';d.save(p); before=p.read_bytes()
    inspection=inspect_docx(p)
    item=next(i for i in inspection.items if i.kind=='image')
    image=read_import_image(p,item)
    identity=sha256(image.data).hexdigest()+'.'+image.extension
    chart=ResolvedBlock('org_chart','This month',asset_hashes=(identity,),asset_captions=('',),references=(f'docx:{inspection.sha256}:{item.id}',))
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(('Site','Role','Name','Telephone','Email'),(('North','Lead','Synthetic Person','555','x@invalid'),),'synthetic:contacts'),))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(chart,contacts),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,p,section_key='organization',master=True,asset_loader={identity:image.data}.__getitem__)))
    body=list(result.element.body)
    chart_i=next(i for i,e in enumerate(body) if e.xpath('.//*[local-name()="blip"]'))
    table_i=next(i for i,e in enumerate(body) if e.tag==qn('w:tbl') and 'Synthetic Person' in ''.join(e.itertext()))
    assert chart_i<table_i
    assert any(e.xpath('.//*[local-name()="pageBreakBefore"]') for e in body[chart_i+1:table_i+1])
    assert p.read_bytes()==before


def test_contacts_without_chart_do_not_acquire_new_page_break(tmp_path):
    d=Document();d.add_heading('ORGANIZATIONAL CHART',1);t=d.add_table(rows=2,cols=5)
    for i,s in enumerate(('Site','Role','Name','Telephone','Email')):
        t.cell(0,i).text=s;t.cell(1,i).text='obsolete'
    p=tmp_path/'contacts-only.docx';d.save(p)
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(('Site','Role','Name','Telephone','Email'),(('North','Lead','Synthetic Person','555','x@invalid'),),'synthetic:contacts'),))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(contacts,),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,p,section_key='organization',master=True)))
    table=next(e for e in result.element.body if e.tag==qn('w:tbl') and 'Synthetic Person' in ''.join(e.itertext()))
    previous=table.getprevious()
    assert previous is not None and not previous.xpath('.//*[local-name()="pageBreakBefore"]')


from conftest import requires_libreoffice


@requires_libreoffice
def test_rendered_chart_and_contacts_occupy_distinct_pages(tmp_path, monkeypatch):
    """Actual PDF output must place current contact text after the chart page."""
    import fitz
    from app import pdf_converter
    d=Document();d.add_heading('ORGANIZATIONAL CHART',1)
    image=BytesIO();Image.new('RGB',(1200,600),'blue').save(image,format='PNG')
    d.add_picture(BytesIO(image.getvalue()),width=Inches(6))
    table=d.add_table(rows=2,cols=5)
    for i,value in enumerate(('Site','Role','Name','Telephone','Email')):
        table.cell(0,i).text=value;table.cell(1,i).text='obsolete'
    source=tmp_path/'synthetic-original.docx';d.save(source)
    chart=ResolvedBlock('org_chart','This month',org_nodes=(OrgChartNode('mgr','Synthetic Manager','Manager'),OrgChartNode('staff','Synthetic Staff','Engineer','mgr')))
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(('Site','Role','Name','Telephone','Email'),(('North','Lead','Synthetic Person','555','x@invalid'),),'synthetic:contacts'),))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(chart,contacts),synthetic=True)
    generated=tmp_path/'result.docx';generated.write_bytes(build_native_docx(draft,source,section_key='organization',master=True))
    monkeypatch.setattr(pdf_converter,'OUTPUT_DIR',tmp_path)
    pdf=pdf_converter.convert_to_pdf(generated)
    with fitz.open(pdf) as doc:
        contact_page=next(i for i,p in enumerate(doc) if 'Synthetic Person' in p.get_text())
        chart_pages=[i for i,p in enumerate(doc) if p.get_image_info()]
        assert chart_pages and max(i for i in chart_pages if i<contact_page)<contact_page
        assert not doc[contact_page].get_image_info()
