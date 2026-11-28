"""Empty Activity photo tails do not earn authority from output emptiness."""
from dataclasses import replace
from types import SimpleNamespace
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pytest
from app.monthly_report_native_photo_tail import empty_photo_tails
from app.monthly_report_model import ResolvedBlock


def fixture(tmp_path, transition='nextPage'):
    d = Document()
    d.add_paragraph('Improvement Highlights and Pics')
    label = d.add_paragraph('Synthetic prior photo caption')
    label.paragraph_format.page_break_before = True
    pic = d.add_paragraph()
    pic.add_run()._r.append(OxmlElement('w:drawing'))
    end = d.add_paragraph()
    end._p.get_or_add_pPr().append(OxmlElement('w:sectPr'))
    d.add_paragraph('MONTHLY SCORECARDS')
    typ = OxmlElement('w:type'); typ.set(qn('w:val'), transition)
    d.element.body.sectPr.append(typ)
    path = tmp_path / 'synthetic.docx'; d.save(path)
    return path, d, label._p, pic._p, end._p


def plans(path, d, blocks=(), unchanged=()):
    return empty_photo_tails(path, SimpleNamespace(blocks=blocks), list(d.element.body),
                             {1:'activity', 2:'activity', 3:'activity', 4:'activity'}, set(unchanged))


def state():
    return SimpleNamespace(live=set(), support=set(), headings=set())


def clear(pic):
    label=pic.getprevious()
    from app.monthly_report_native_layout import _set_text
    _set_text(label, '')
    for drawing in list(pic.iter(qn('w:drawing'))):
        drawing.getparent().remove(drawing)


def apply(plan,d,s):
    from app.monthly_report_native_layout import _set_text
    plan.apply(d.element.body,s,{plan.label})


def has_break(label):
    return label.find('./' + qn('w:pPr') + '/' + qn('w:pageBreakBefore')) is not None


def test_only_direct_label_break_changes(tmp_path):
    p,d,label,pic,end = fixture(tmp_path)
    plan, = plans(p,d)
    clear(pic)
    from app.monthly_report_native_layout import _set_text
    _set_text(label, '')
    before = d.element.xml
    apply(plan,d,state())
    assert not has_break(label)
    br = OxmlElement('w:pageBreakBefore'); label.get_or_add_pPr().append(br)
    assert d.element.xml == before


@pytest.mark.parametrize('key,value', [('text','Current'),('rows',(('Current',),)),
    ('extra_tables',('Current',)),('asset_hashes',('current.png',)),
    ('asset_instances',('current',)),('org_nodes',('current',))])
def test_current_payload_refuses_plan(tmp_path,key,value):
    p,d,*_ = fixture(tmp_path)
    b = replace(ResolvedBlock('improvements','This month'), **{key:value})
    assert not plans(p,d,(b,))


@pytest.mark.parametrize('kind', ['live','support','headings'])
@pytest.mark.parametrize('target', [0,1,2])
def test_current_ownership_refuses_cleanup(tmp_path,kind,target):
    p,d,*nodes = fixture(tmp_path); plan, = plans(p,d); clear(nodes[1]); s=state()
    getattr(s,kind).add(nodes[target]); before=d.element.xml
    apply(plan,d,s); assert d.element.xml==before


@pytest.mark.parametrize('mutation', ['field','bookmark','style','section','numbering'])
def test_raw_source_unknowns_cannot_be_normalized_into_proof(tmp_path,mutation):
    p,d,label,pic,end = fixture(tmp_path)
    tags={'field':'fldSimple','bookmark':'bookmarkStart','style':'pStyle',
          'section':'sectPr','numbering':'numPr'}
    n=OxmlElement('w:'+tags[mutation]); label.get_or_add_pPr().append(n); d.save(p)
    label.get_or_add_pPr().remove(n)
    assert not plans(p,d)


@pytest.mark.parametrize('transition',['continuous','oddPage','evenPage','nextColumn','unknown'])
def test_non_nextpage_transition_refused(tmp_path,transition):
    p,d,*_ = fixture(tmp_path,transition); assert not plans(p,d)


@pytest.mark.parametrize('mutation',['picture','label','boundary','inserted','next-route','next-boundary'])
def test_postproof_change_refuses_cleanup(tmp_path,mutation):
    p,d,label,pic,end = fixture(tmp_path); plan, = plans(p,d); clear(pic)
    if mutation=='picture': pic.append(OxmlElement('w:drawing'))
    elif mutation=='label': label.get_or_add_pPr().append(OxmlElement('w:spacing'))
    elif mutation=='boundary': end.get_or_add_pPr().append(OxmlElement('w:spacing'))
    elif mutation=='inserted': pic.addnext(OxmlElement('w:p'))
    elif mutation=='next-route': d.element.body.sectPr.append(OxmlElement('w:headerReference'))
    else:
        n=OxmlElement('w:p'); npr=OxmlElement('w:pPr'); npr.append(OxmlElement('w:sectPr')); n.append(npr)
        d.element.body[-1].addprevious(n)
    before=d.element.xml; apply(plan,d,state()); assert d.element.xml==before


@pytest.mark.parametrize('value',['0','false','off'])
def test_false_break_refused(tmp_path,value):
    p,d,label,*_=fixture(tmp_path)
    label.find('./'+qn('w:pPr')+'/'+qn('w:pageBreakBefore')).set(qn('w:val'),value)
    d.save(p); assert not plans(p,d)


def test_only_builder_zero_numbering_override_is_permitted(tmp_path):
    p,d,label,pic,end=fixture(tmp_path); plan,=plans(p,d);clear(pic)
    num=OxmlElement('w:numPr');n=OxmlElement('w:numId');n.set(qn('w:val'),'0');num.append(n)
    label.get_or_add_pPr().append(num);apply(plan,d,state());assert not has_break(label)


def test_public_builder_removes_only_break_from_cleared_caption(tmp_path):
    from io import BytesIO
    from PIL import Image
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_native_layout import build_native_docx
    from app.monthly_report_sections import table_without_prices
    from test_monthly_report_native_empty_activity import report
    path,draft = report.__wrapped__(tmp_path)
    d=Document(path)
    caption=next(p for p in d.paragraphs if p.text=='Prior improvement description.')
    pic=d.add_paragraph();caption._p.addnext(pic._p)
    image=BytesIO();Image.new('RGB',(40,40),'navy').save(image,format='PNG')
    pic.add_run().add_picture(BytesIO(image.getvalue()))
    t=d.add_table(rows=2,cols=2)
    for row,values in zip(t.rows,(('Course','Hours'),('Synthetic training','2'))):
        for c,value in zip(row.cells,values):c.text=value
    d.save(path)
    inspection=inspect_docx(path);item=next(i for i in inspection.items if i.kind=='table')
    table,_=table_without_prices(item);table=replace(table,reference=f'docx:{inspection.sha256}:{item.id}')
    draft=replace(draft,blocks=tuple(replace(b,extra_tables=(table,)) if b.key=='work_orders' else b for b in draft.blocks))
    item=next(i for i in inspection.items if i.kind=='table' and i.id!=item.id)
    training,_=table_without_prices(item);training=replace(training,reference=f'docx:{inspection.sha256}:{item.id}')
    draft=replace(draft,blocks=tuple(replace(b,extra_tables=(training,)) if b.key=='training_summary' else b for b in draft.blocks))
    source=path.read_bytes()
    from app import monthly_report_native_photo_tail as cleanup
    from unittest.mock import patch
    with patch.object(cleanup.EmptyPhotoTail,'apply',lambda *args:None):
        baseline=Document(BytesIO(build_native_docx(draft,path)))
    fixed=Document(BytesIO(build_native_docx(draft,path)))
    changes=[]
    for a,b in zip(baseline.element.body,fixed.element.body):
        if a.xml!=b.xml:
            changes.append(a)
            br=a.find('./'+qn('w:pPr')+'/'+qn('w:pageBreakBefore'))
            assert br is not None;br.getparent().remove(br)
    assert len(changes)==1
    assert baseline.element.xml==fixed.element.xml
    assert len(d.sections)==len(fixed.sections)
    assert path.read_bytes()==source


@pytest.mark.parametrize('kind',['duplicate-break','text-in-properties','duplicate-numbering'])
def test_malformed_raw_caption_refused(tmp_path,kind):
    p,d,label,pic,end=fixture(tmp_path);pr=label.get_or_add_pPr()
    if kind=='duplicate-break':pr.append(OxmlElement('w:pageBreakBefore'))
    elif kind=='text-in-properties':
        text=OxmlElement('w:t');text.text='Synthetic';pr.append(text)
    else:
        pr.append(OxmlElement('w:numPr'));pr.append(OxmlElement('w:numPr'))
    d.save(p);assert not plans(p,d)


def test_uncleared_caption_has_no_authority(tmp_path):
    p,d,label,pic,end=fixture(tmp_path);plan,=plans(p,d);clear(pic)
    before=d.element.xml;plan.apply(d.element.body,state(),set());assert d.element.xml==before
