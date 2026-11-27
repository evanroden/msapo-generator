"""Invented imported vendor labels stay attached to their contact details."""
from dataclasses import replace
from io import BytesIO
from docx import Document
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import ReportDraft,ReportTable,ReportPeriod,ResolvedBlock,default_sections,synthetic_profiles


def output(columns, rows, slot='subcontractor_matrix'):
    section=next(s for s in default_sections() if any(b.key==slot for b in s.blocks))
    draft=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),'Synthetic Editor',(section,),
        (ResolvedBlock(slot,'Last month',extra_tables=(ReportTable(columns,rows),)),),synthetic=True)
    return Document(BytesIO(_build_docx(draft))).tables[0]


def keeps(table):
    return [all(p.paragraph_format.keep_with_next for c in r.cells for p in c.paragraphs) for r in table.rows]


def test_vendor_name_and_number_group_is_kept_but_not_entire_roster():
    rows=(('Electrical','Synthetic Electric','X'),('Contact Name','Synthetic Person',''),('Contact Number','555-0100',''),
          ('','',''),('Mechanical','Synthetic Mechanical','X'),('Contact Name','Another Person',''),('Contact Number','555-0101',''))
    table=output(('Discipline','Invented Site','MSA'),rows)
    assert keeps(table)==[True,True,True,False,False,True,True,False]
    assert tuple(tuple(c.text for c in r.cells) for r in table.rows)==(('Discipline','Invented Site','MSA'),*rows)


def test_standalone_extra_contact_pair_stays_together_without_linking_blank_row():
    table=output(('Discipline','Invented Site','MSA'),(('','',''),('Contact Name','Dispatch Person',''),('Contact Number','555-0102','')))
    assert keeps(table)==[True,False,True,False]


def test_unrecognized_schema_or_incomplete_pair_keeps_existing_pagination():
    rows=(('Electrical','Synthetic Electric','X'),('Contact Name','Synthetic Person',''),('Other detail','note',''))
    assert keeps(output(('Discipline','Invented Site','MSA'),rows))==[True,False,False,False]
    complete=(('Electrical','Synthetic Electric','X'),('Contact Name','Synthetic Person',''),('Contact Number','555-0100',''))
    assert keeps(output(('Item','Invented Site','Status'),complete))==[True,False,False,False]
