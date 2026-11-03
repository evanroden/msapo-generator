"""Strict AI destinations preserve facts and never derive identity from prose."""
from dataclasses import replace
import pytest
from app.monthly_report_model import ReportDraft,default_sections
from app.monthly_report_ai_correction_targets import paragraph_target,resolve_paragraph,unsupported_number_indexes
from app.monthly_report_ai import fact_date_problems,_unverified_fact_dates,block_date_problems
from app.monthly_report_checks import preflight
from test_monthly_report_ai import prepared,PROFILE,PERIOD


def fixture():
    source,block=prepared()
    return ReportDraft(PROFILE,PERIOD,'Synthetic Editor',default_sections(),(block,),sources=(source,))


def test_source_fact_and_paragraph_snapshot_are_exact_and_immutable():
    draft=fixture();block=draft.blocks[0];target=paragraph_target(draft,block,0,'evidence')
    assert resolve_paragraph(draft,target)==(block,block.ai_paragraphs[0])
    for changed in (replace(block,source='Omit'),replace(block,ai_paragraphs=()),
                    replace(block,ai_paragraphs=(replace(block.ai_paragraphs[0],text='Changed'),))):
        assert resolve_paragraph(replace(draft,blocks=(changed,)),target) is None
    assert resolve_paragraph(replace(draft,blocks=(*draft.blocks,*draft.blocks)),target) is None
    assert resolve_paragraph(replace(draft,sources=(*draft.sources,*draft.sources)),target) is None
    source=replace(draft.sources[0],facts=(replace(draft.sources[0].facts[0],quote='Changed evidence'),))
    assert resolve_paragraph(replace(draft,sources=(source,)),target) is None


def test_equal_paragraph_occurrences_and_duplicate_fact_ids_are_not_first_match():
    draft=fixture();block=draft.blocks[0]
    duplicate=replace(block,ai_paragraphs=(*block.ai_paragraphs,*block.ai_paragraphs))
    changed=replace(draft,blocks=(duplicate,))
    assert resolve_paragraph(changed,paragraph_target(changed,duplicate,1,'evidence')) is None
    source=replace(draft.sources[0],facts=(*draft.sources[0].facts,*draft.sources[0].facts))
    changed=replace(draft,sources=(source,))
    assert resolve_paragraph(changed,paragraph_target(changed,block,0,'evidence')) is None


def test_missing_saved_fact_is_explicit_evidence_destination_not_silent_cleanup():
    draft=fixture();changed=replace(draft,sources=())
    block=changed.blocks[0];target=paragraph_target(changed,block,0,'evidence')
    assert resolve_paragraph(changed,target)==(block,block.ai_paragraphs[0])
    assert target.facts[0][1:]==('','','','',0)
    assert changed.blocks[0].ai_paragraphs[0].fact_ids==draft.blocks[0].ai_paragraphs[0].fact_ids


def test_numeric_targets_use_numeric_evidence_validation_not_flag_text():
    draft=fixture();block=draft.blocks[0]
    assert unsupported_number_indexes(block,draft.sources)==()
    bad=replace(block,ai_paragraphs=(replace(block.ai_paragraphs[0],text='Replaced 99 seals.',flags=('Unsupported number: arbitrary localized label',)),))
    assert unsupported_number_indexes(bad,draft.sources)==(0,)
    bad_draft=replace(draft,blocks=(bad,))
    check=next(c for c in preflight(bad_draft) if c.code=='ai_number')
    assert len(check.targets)==1 and check.targets[0].ordinal==0
    assert resolve_paragraph(bad_draft,check.targets[0]) is not None


def test_fact_date_metadata_keeps_original_message_api_and_exact_fact_page():
    draft=fixture();source=draft.sources[0]
    fact=replace(source.facts[0],date='2026-09-25')
    source=replace(source,facts=(fact,));draft=replace(draft,sources=(source,))
    details=fact_date_problems(source.facts,draft.sources)
    assert len(details)==1 and details[0].fact_id==fact.id and details[0].page==1
    assert tuple(d.message for d in details)==_unverified_fact_dates(source.facts,draft.sources)
    check=next(c for c in preflight(draft) if c.code=='ai_date')
    assert (check.message,)==block_date_problems(draft.blocks[0],draft.sources)
    assert check.targets[0].fact_id==fact.id and check.targets[0].source_id==source.id
    assert resolve_paragraph(draft,check.targets[0]) is not None
