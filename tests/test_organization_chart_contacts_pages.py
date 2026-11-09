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
    import pymupdf as fitz
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
        import re
        contact_page=next(i for i,p in enumerate(doc) if 'Synthetic Person' in re.sub(r'\s+', ' ', p.get_text()))
        chart_pages=[i for i,p in enumerate(doc) if p.get_image_info()]
        assert chart_pages and max(i for i in chart_pages if i<contact_page)<contact_page
        assert not doc[contact_page].get_image_info()


@requires_libreoffice
def test_rendered_retained_chart_and_contacts_are_separate(tmp_path, monkeypatch):
    import re
    import pymupdf as fitz
    from hashlib import sha256
    from app import pdf_converter
    from app.monthly_report_import import inspect_docx, read_import_image
    d=Document();d.add_heading('ORGANIZATIONAL CHART',1)
    image=BytesIO();Image.new('RGB',(1200,600),'blue').save(image,format='PNG')
    d.add_picture(BytesIO(image.getvalue()),width=Inches(6))
    t=d.add_table(rows=2,cols=5)
    for i,s in enumerate(('Site','Role','Name','Telephone','Email')):
        t.cell(0,i).text=s;t.cell(1,i).text='obsolete'
    source=tmp_path/'source.docx';d.save(source)
    inspection=inspect_docx(source);item=next(i for i in inspection.items if i.kind=='image')
    image=read_import_image(source,item); identity=sha256(image.data).hexdigest()+'.'+image.extension
    chart=ResolvedBlock('org_chart','This month',asset_hashes=(identity,),asset_captions=('',),references=(f'docx:{inspection.sha256}:{item.id}',))
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(('Site','Role','Name','Telephone','Email'),(('North','Lead','Synthetic Person','555','x@invalid'),),'synthetic:contacts'),))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(chart,contacts),synthetic=True)
    generated=tmp_path/'retained.docx';generated.write_bytes(build_native_docx(draft,source,section_key='organization',master=True,asset_loader={identity:image.data}.__getitem__))
    monkeypatch.setattr(pdf_converter,'OUTPUT_DIR',tmp_path)
    with fitz.open(pdf_converter.convert_to_pdf(generated)) as pdf:
        contact_page=next(i for i,p in enumerate(pdf) if 'Synthetic Person' in re.sub(r'\s+',' ',p.get_text()))
        chart_pages=[i for i,p in enumerate(pdf) if p.get_image_info()]
        assert chart_pages and max(chart_pages)<contact_page
        assert not pdf[contact_page].get_image_info()


def test_bound_unchanged_contact_table_also_moves_after_chart(tmp_path, monkeypatch):
    from hashlib import sha256
    from app.monthly_report_import import inspect_docx, read_import_image
    from app.monthly_report_sections import table_without_prices
    d=Document();d.add_heading('ORGANIZATIONAL CHART',1)
    image=BytesIO();Image.new('RGB',(1200,600),'blue').save(image,format='PNG')
    d.add_picture(BytesIO(image.getvalue()),width=Inches(6))
    table=d.add_table(rows=2,cols=5)
    for i,s in enumerate(('Site','Role','Name','Telephone','Email')): table.cell(0,i).text=s
    for i,s in enumerate(('North','Lead','Synthetic Person','555','x@invalid')): table.cell(1,i).text=s
    source=tmp_path/'retained.docx';d.save(source)
    inspection=inspect_docx(source); chart_item=next(i for i in inspection.items if i.kind=='image')
    table_item=next(i for i in inspection.items if i.kind=='table')
    image=read_import_image(source,chart_item); identity=sha256(image.data).hexdigest()+'.'+image.extension
    chart=ResolvedBlock('org_chart','This month',asset_hashes=(identity,),asset_captions=('',),references=(f'docx:{inspection.sha256}:{chart_item.id}',))
    filtered,_=table_without_prices(table_item)
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(filtered.columns,filtered.rows,f'docx:{inspection.sha256}:{table_item.id}'),))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(chart,contacts),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,source,section_key='organization',master=True,asset_loader={identity:image.data}.__getitem__)))
    body=list(result.element.body); chart_i=next(i for i,e in enumerate(body) if e.xpath('.//*[local-name()="blip"]'))
    table_i=next(i for i,e in enumerate(body) if e.tag==qn('w:tbl') and 'Synthetic Person' in ''.join(e.itertext()))
    assert chart_i<table_i
    assert any(e.xpath('.//*[local-name()="pageBreakBefore"]') for e in body[chart_i+1:table_i+1])
    # Exercise actual pagination where the writer is available, including the
    # preserved table path (the text may wrap within a PDF table cell).
    from conftest import libreoffice_can_convert
    if libreoffice_can_convert():
        import pymupdf as fitz
        import re
        from app import pdf_converter
        rendered=tmp_path/'retained-both.docx'; result.save(rendered)
        monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
        with fitz.open(pdf_converter.convert_to_pdf(rendered)) as pdf:
            contact_page=next(i for i,p in enumerate(pdf) if 'Synthetic Person' in re.sub(r'\s+',' ',p.get_text()))
            image_pages=[i for i,p in enumerate(pdf) if p.get_image_info()]
            assert image_pages and max(image_pages)<contact_page
            assert not pdf[contact_page].get_image_info()


def test_source_chart_after_table_is_moved_before_new_contacts(tmp_path, monkeypatch):
    from hashlib import sha256
    from app.monthly_report_import import inspect_docx, read_import_image
    d=Document();d.add_heading('ORGANIZATIONAL CHART',1)
    table=d.add_table(rows=2,cols=5)
    for i,s in enumerate(('Site','Role','Name','Telephone','Email')): table.cell(0,i).text=s;table.cell(1,i).text='obsolete'
    image=BytesIO();Image.new('RGB',(1200,600),'blue').save(image,format='PNG')
    d.add_picture(BytesIO(image.getvalue()),width=Inches(6))
    source=tmp_path/'source-reversed.docx';d.save(source)
    inspection=inspect_docx(source); item=next(i for i in inspection.items if i.kind=='image')
    image=read_import_image(source,item); key=sha256(image.data).hexdigest()+'.'+image.extension
    chart=ResolvedBlock('org_chart','This month',asset_hashes=(key,),asset_captions=('',),references=(f'docx:{inspection.sha256}:{item.id}',))
    contacts=ResolvedBlock('contact_matrix','This month',extra_tables=(ReportTable(('Site','Role','Name','Telephone','Email'),(('North','Lead','Synthetic Person','555','x@invalid'),),'synthetic:contacts'),))
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Tester',default_sections(),(chart,contacts),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,source,section_key='organization',master=True,asset_loader={key:image.data}.__getitem__)))
    body=list(result.element.body);chart_i=next(i for i,e in enumerate(body) if e.xpath('.//*[local-name()="blip"]'))
    table_i=next(i for i,e in enumerate(body) if e.tag==qn('w:tbl') and 'Synthetic Person' in ''.join(e.itertext()))
    assert chart_i<table_i
    assert any(e.xpath('.//*[local-name()="pageBreakBefore"]') for e in body[chart_i+1:table_i+1])
    from conftest import libreoffice_can_convert
    if libreoffice_can_convert():
        import pymupdf as fitz
        import re
        from app import pdf_converter
        generated=tmp_path/'reversed-output.docx';result.save(generated)
        monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
        with fitz.open(pdf_converter.convert_to_pdf(generated)) as pdf:
            contact_page=next(i for i,p in enumerate(pdf) if 'Synthetic Person' in re.sub(r'\s+',' ',p.get_text()))
            chart_pages=[i for i,p in enumerate(pdf) if p.get_image_info()]
            assert chart_pages and max(chart_pages)<contact_page
            assert not pdf[contact_page].get_image_info()


def test_duplicate_break_removed_only_at_proven_divider_boundary(monkeypatch):
    from docx.oxml import OxmlElement
    from app import monthly_report_native_layout as native
    d=Document(); divider=d.add_paragraph('recognized divider')._p
    section=OxmlElement('w:sectPr'); divider.get_or_add_pPr().append(section)
    d.add_paragraph(); break_p=d.add_paragraph(); break_p.add_run().add_break(__import__('docx').enum.text.WD_BREAK.PAGE)
    chart=d.add_paragraph('chart')._p
    monkeypatch.setattr(native,'_is_native_divider_background',lambda node,text: node is divider)
    native._remove_duplicate_divider_chart_break(chart,d.element.body)
    assert not list(break_p._p.iter(qn('w:br')))
    assert divider.find('.//' + qn('w:sectPr')) is not None


def test_duplicate_break_preserved_for_odd_page_or_intervening_content(monkeypatch):
    from docx.oxml import OxmlElement
    from app import monthly_report_native_layout as native
    for reason in ('odd', 'content', 'unrecognized'):
        d=Document(); divider=d.add_paragraph('divider')._p
        section=OxmlElement('w:sectPr'); divider.get_or_add_pPr().append(section)
        if reason=='odd':
            kind=OxmlElement('w:type');kind.set(qn('w:val'),'oddPage');section.append(kind)
        d.add_paragraph('important' if reason=='content' else '')
        break_p=d.add_paragraph();break_p.add_run().add_break(__import__('docx').enum.text.WD_BREAK.PAGE)
        chart=d.add_paragraph('chart')._p
        monkeypatch.setattr(native,'_is_native_divider_background',lambda node,text: reason!='unrecognized' and node is divider)
        native._remove_duplicate_divider_chart_break(chart,d.element.body)
        assert len(list(break_p._p.iter(qn('w:br')))) == 1
