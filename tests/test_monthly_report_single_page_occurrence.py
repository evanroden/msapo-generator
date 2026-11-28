"""Independent source occurrences cannot silently make a single-page slot plural."""
from dataclasses import replace
import pytest
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_setup import merge_drafts
from app.monthly_report_start_replay import merge_starting_drafts


def drafts(slot='org_chart'):
    old=ResolvedBlock(slot,'This month',asset_hashes=('same.png',),references=('docx:'+'a'*64+':item-0005',))
    new=replace(old,references=('docx:'+'b'*64+':item-0005',))
    d=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),'Synthetic',default_sections(),(old,))
    return d,replace(d,blocks=(new,))

@pytest.mark.parametrize('slot',['org_chart','contact_matrix','business_hours_workflow','after_hours_workflow'])
def test_different_source_equal_picture_cannot_duplicate_single_page(slot):
    current,incoming=drafts(slot)
    with pytest.raises(ValueError,match='single-image'):
        merge_starting_drafts(current,incoming)
    assert current.blocks[0].asset_hashes==('same.png',)


def test_exact_source_reimport_remains_idempotent():
    current,_=drafts()
    assert merge_drafts(current,current).blocks[0].asset_hashes==('same.png',)


def test_equal_independent_multi_picture_occurrences_remain_separate():
    current,incoming=drafts('improvements')
    merged=merge_drafts(current,incoming)
    assert merged.blocks[0].asset_hashes==('same.png','same.png')
