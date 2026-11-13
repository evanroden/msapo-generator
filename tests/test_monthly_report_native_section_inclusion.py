"""Whole-section omissions keep independently proved source chrome closure."""
from dataclasses import replace
from io import BytesIO
import pytest
from docx import Document
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_section_inclusion import set_section_included
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


@pytest.mark.parametrize('key',['activity','training'])
def test_reviewed_native_source_omission_has_derived_header_scope(sample,key):
    path,view,profile,period,inventory,receipt=sample
    value,loader=save_sample(sample)
    assert key in {s.key for s in value.sections}
    before=path.read_bytes()
    value=set_section_included(value,key,False)
    output=build_native_docx(value,path,asset_loader=loader,source_view=view)
    text='\n'.join(p.text for p in Document(BytesIO(output)).paragraphs)
    assert ('MONTHLY ACTIVITY SUMMARY' if key=='activity' else 'TRAINING SUMMARY') not in text
    assert path.read_bytes()==before
