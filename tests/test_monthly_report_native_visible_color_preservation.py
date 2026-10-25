from docx import Document
from docx.shared import Pt,RGBColor
from lxml import etree
import pytest
@pytest.mark.parametrize('color',['17365D','404040'])
def test_known_visible_dark_native_typography_is_preserved(color):
    from app.monthly_report_native_narrative_visibility import narrative_visibility_writer
    doc=Document();p=doc.add_paragraph('Synthetic ordinary visible current prose.')
    r=p.runs[0];r.font.color.rgb=RGBColor.from_string(color);r.font.size=Pt(13);r.bold=True
    before=etree.tostring(p._p); styles=etree.tostring(doc.styles.element)
    result=narrative_visibility_writer(doc)(p._p)
    assert result is p._p
    assert etree.tostring(result)==before
    assert etree.tostring(doc.styles.element)==styles
