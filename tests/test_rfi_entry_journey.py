"""The RFI browser output assertion rejects missing, invented and blank rows."""
from io import BytesIO

from docx import Document
import pymupdf
import pytest

from scripts.qa_rfi_entry import assert_outputs, REQUEST, SECOND, TEMPORARY


def outputs(*, first=REQUEST, status='', extra=None, pdf_second=SECOND):
    document = Document()
    rows = [('Facility','Requested item','Status'),
            ('Demo North',first,status), ('Demo South',SECOND,'Awaiting response')]
    if extra is not None:
        rows.append(extra)
    table = document.add_table(rows=len(rows), cols=3)
    for row, values in zip(table.rows, rows):
        for cell, value in zip(row.cells, values):
            cell.text = value
    word = BytesIO()
    document.save(word)
    with pymupdf.open() as document:
        page = document.new_page()
        assert page.insert_textbox((40,40,550,750), first+'\n'+pdf_second,
                                   fontsize=10) >= 0
        pdf = document.tobytes()
    return word.getvalue(), pdf


def test_rfi_output_assertion_accepts_exact_editable_rows_and_pdf_text():
    result = assert_outputs(*outputs())
    assert result['docx']['bytes'] > 0 and result['pdf']['pages'] == 1


@pytest.mark.parametrize('change', [
    {'first':'A changed request'}, {'status':'Completed'}, {'extra':('','','')},
    {'extra':('',TEMPORARY,'')}, {'pdf_second':''},
])
def test_rfi_output_assertion_rejects_changed_status_lost_text_and_uncounted_rows(change):
    with pytest.raises(AssertionError):
        assert_outputs(*outputs(**change))
