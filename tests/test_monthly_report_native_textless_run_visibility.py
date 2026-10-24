from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pytest
@pytest.mark.parametrize('scope',['paragraph-default','document-default'])
def test_textless_visible_run_cannot_authorize_future_unstyled_text(tmp_path,monkeypatch,scope):
    from app.monthly_report_native_narrative_visibility import narrative_visibility_writer
    from app.monthly_report_native_text import write_narrative
    from app import pdf_converter
    from conftest import libreoffice_can_convert
    import pymupdf
    assert libreoffice_can_convert()
    doc=Document()
    if scope=='paragraph-default': doc.styles['Normal'].font.hidden=True
    else:
        rp=doc.styles.element.find('./'+qn('w:docDefaults')+'/'+qn('w:rPrDefault')+'/'+qn('w:rPr'))
        rp.append(OxmlElement('w:vanish'))
    empty=OxmlElement('w:p'); r=OxmlElement('w:r'); empty.append(r); rp=OxmlElement('w:rPr'); r.append(rp); v=OxmlElement('w:vanish'); v.set(qn('w:val'),'0'); rp.append(v); anchor=doc.add_paragraph()._p
    prototype=narrative_visibility_writer(doc)(empty)
    write_narrative(anchor,prototype,'Independent table-only current narrative.')
    out=tmp_path/'out.docx';doc.save(out)
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'runtime'));monkeypatch.setattr(pdf_converter,'OUTPUT_DIR',tmp_path)
    pdf=pdf_converter.convert_to_pdf(out)
    with pymupdf.open(pdf) as d:text='\n'.join(p.get_text() for p in d)
    assert text.count('Independent table-only current narrative.')==1
