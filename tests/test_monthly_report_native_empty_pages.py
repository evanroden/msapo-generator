"""Only positively cleared plain scorecard pages lose explicit page breaks."""
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.section import WD_SECTION_START

from app.monthly_report_native_empty_pages import empty_scorecard_pages


def scenario(*, tail=False, section='scorecards'):
    doc=Document()
    doc.add_paragraph('RETAINED CURRENT TABLE CONTEXT')
    if tail: doc.add_page_break()
    old=doc.add_paragraph('Old source facts')._p
    closing=doc.add_paragraph()._p if tail else doc.add_page_break()._p
    if not tail: doc.add_paragraph('CURRENT TABLE CONTEXT')
    original=list(doc.element.body)
    plan=empty_scorecard_pages(original,{n:section for n in range(1,len(original)+1)})
    # Prove redaction, not just a currently blank paragraph.
    for t in old.iter(qn('w:t')):t.text=''
    pages=SimpleNamespace(live=set(),support=set(),headings=set())
    return doc,old,closing,plan,pages


@pytest.mark.parametrize('tail',[False,True])
def test_cleared_plain_page_break_is_removed_without_removing_roots(tail):
    doc,old,closing,plan,pages=scenario(tail=tail)
    # The retained first paragraph is not part of a cleared page in this case.
    if not tail:
        # Source page starts immediately after a Word boundary.
        first=doc.element.body[0];first.getparent().remove(first)
        # Recreate source proof before the final clear.
        next(old.iter(qn('w:t'))).text='Old source facts'
        plan=empty_scorecard_pages(list(doc.element.body),{n:'scorecards' for n in range(1,len(doc.element.body)+1)})
        next(old.iter(qn('w:t'))).text=''
    roots=tuple(doc.element.body)
    plan.apply(doc.element.body,pages,{old})
    assert not list(doc.element.iter(qn('w:br')))
    assert tuple(doc.element.body)==roots


@pytest.mark.parametrize('guard',['live','support','headings','not-cleared','current-text','unknown','new-insertion','other-section','authored-blank'])
def test_ambiguous_or_current_page_is_preserved(guard):
    doc=Document();old=doc.add_paragraph('Old facts')._p;end=doc.add_page_break()._p;doc.add_paragraph('Current table')
    if guard=='unknown':old.append(OxmlElement('w:bookmarkStart'))
    if guard=='authored-blank':next(old.iter(qn('w:t'))).text=''
    plan=empty_scorecard_pages(list(doc.element.body),{n:('activity' if guard=='other-section' else 'scorecards') for n in range(1,len(doc.element.body)+1)})
    next(old.iter(qn('w:t'))).text='Current' if guard=='current-text' else ''
    pages=SimpleNamespace(live=set(),support=set(),headings=set())
    if guard in ('live','support','headings'):getattr(pages,guard).add(old)
    if guard=='new-insertion':old.addnext(OxmlElement('w:p'))
    before=len(list(doc.element.iter(qn('w:br'))))
    plan.apply(doc.element.body,pages,set() if guard=='not-cleared' else {old})
    assert len(list(doc.element.iter(qn('w:br'))))==before


def test_word_section_boundary_and_its_header_reference_are_untouched():
    doc=Document();old=doc.add_paragraph('Old facts')._p;doc.add_page_break();doc.add_section(WD_SECTION_START.NEW_PAGE);doc.add_paragraph('Current table')
    roots=list(doc.element.body);plan=empty_scorecard_pages(roots,{n:'scorecards' for n in range(1,len(roots)+1)})
    boundaries=[n for n in doc.element.iter(qn('w:sectPr'))];before=[n.xml for n in boundaries]
    next(old.iter(qn('w:t'))).text=''
    plan.apply(doc.element.body,SimpleNamespace(live=set(),support=set(),headings=set()),{old})
    assert [n.xml for n in doc.element.iter(qn('w:sectPr'))]==before


def test_exact_native_table_survives_while_cleared_shared_pages_reflow(tmp_path):
    from app.monthly_report_import import inspect_docx, imported_draft
    from app.monthly_report_sections import build_section_import
    from app.monthly_report_model import ReportProfile,ReportPeriod,Facility
    from app.monthly_report_native_layout import build_native_docx
    doc=Document();doc.add_paragraph('Synthetic Campus');doc.add_section(WD_SECTION_START.NEW_PAGE);doc.add_heading('MONTHLY SCORECARDS',1);doc.add_section(WD_SECTION_START.NEW_PAGE)
    doc.add_paragraph('Old monthly prose');doc.add_page_break();doc.add_paragraph('Thermal Services Requirements and Capacity')
    table=doc.add_table(rows=2,cols=2)
    for cell,text in zip((c for r in table.rows for c in r.cells),('Campus','Capacity','Synthetic Campus','123')):cell.text=text
    doc.add_page_break();doc.add_paragraph('Old trailing prose')
    source=tmp_path/'source.docx';doc.save(source);i=inspect_docx(source)
    item=next(x for x in i.items if x.kind=='table')
    profile=ReportProfile('Synthetic contract','synthetic','Synthetic Campus',(Facility('synthetic','Synthetic Campus'),))
    plan={'key':'scorecards','target':'scorecards','approved':True,'selected':[item.id],'destinations':{item.id:'thermal_capacity'}}
    mapped,_=build_section_import(source,i,(plan,),profile=profile,period=ReportPeriod(2026,11))
    draft=imported_draft(profile,ReportPeriod(2026,11),'Synthetic operator',mapped)
    for section in (None,'scorecards'):
        for master in (False,True):
            raw=build_native_docx(draft,source,section_key=section,master=master)
            result=Document(BytesIO(raw))
            # Preview slicing replaces its terminal Word boundary, so that
            # tail stays conservative. Full-document roots retain exact proof.
            assert len(list(result.element.iter(qn('w:br')))) == (1 if section else 0)
            assert [[c.text for c in r.cells] for r in result.tables[0].rows]==[['Campus','Capacity'],['Synthetic Campus','123']]
            assert 'Old monthly' not in '\n'.join(p.text for p in result.paragraphs)


def test_authored_page_break_without_cleared_source_text_is_not_cleanup_consent():
    doc=Document();blank=doc.add_paragraph()._p;doc.add_page_break();doc.add_paragraph('Current table')
    plan=empty_scorecard_pages(list(doc.element.body),{n:'scorecards' for n in range(1,len(doc.element.body)+1)})
    plan.apply(doc.element.body,SimpleNamespace(live=set(),support=set(),headings=set()),{blank})
    assert len(list(doc.element.iter(qn('w:br'))))==1


@pytest.mark.parametrize('guard',['live','support','headings','text','unknown'])
def test_changed_tail_delimiter_remains_untouched(guard):
    doc,old,closing,plan,pages=scenario(tail=True)
    delimiter=old.getprevious()
    if guard in ('live','support','headings'):getattr(pages,guard).add(delimiter)
    elif guard=='unknown':delimiter.append(OxmlElement('w:bookmarkStart'))
    else:
        run=OxmlElement('w:r');text=OxmlElement('w:t');text.text='Current note';run.append(text);delimiter.append(run)
    plan.apply(doc.element.body,pages,{old})
    assert len(list(doc.element.iter(qn('w:br'))))==1


@pytest.mark.parametrize('where',['before','after'])
def test_tail_new_neighbor_is_not_erased_by_stale_page_proof(where):
    doc,old,closing,plan,pages=scenario(tail=True)
    new=OxmlElement('w:p')
    if where=='before':old.addprevious(new)
    else:closing.addnext(new)
    plan.apply(doc.element.body,pages,{old})
    assert len(list(doc.element.iter(qn('w:br'))))==1


def test_cleared_text_after_current_table_does_not_prove_a_whole_empty_page():
    doc=Document();doc.add_table(rows=1,cols=1).cell(0,0).text='Current'
    old=doc.add_paragraph('Old prose after current table')._p;doc.add_page_break();doc.add_paragraph('Next page')
    plan=empty_scorecard_pages(list(doc.element.body),{n:'scorecards' for n in range(1,len(doc.element.body)+1)})
    next(old.iter(qn('w:t'))).text=''
    plan.apply(doc.element.body,SimpleNamespace(live=set(),support=set(),headings=set()),{old})
    assert len(list(doc.element.iter(qn('w:br'))))==1


def test_new_extra_tail_break_is_not_covered_by_single_break_proof():
    doc,old,closing,plan,pages=scenario(tail=True)
    delimiter=old.getprevious();run=OxmlElement('w:r');br=OxmlElement('w:br');br.set(qn('w:type'),'page');run.append(br);delimiter.append(run)
    plan.apply(doc.element.body,pages,{old})
    assert len(list(doc.element.iter(qn('w:br'))))==2
