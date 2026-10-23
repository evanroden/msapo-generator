"""Removing the last restored Water page retains placement without inclusion."""
from dataclasses import asdict, replace

from app.monthly_report_page_controls import revise_included_page
from app.monthly_report_section_uploads import section_contents, source_destinations, included_pages
from app.monthly_report_model import ReportPeriod, synthetic_draft, BlockSpec
from app import monthly_report_library as library
from test_monthly_report_page_manager import _prepared
import pytest


def test_removed_last_page_keeps_durable_water_route_over_classifier(monkeypatch, tmp_path):
    profile, content, block = _prepared(monkeypatch, tmp_path, pages=1)
    content = replace(content, source=replace(content.source, classification='Vendor service'))
    # A restored attachment establishes its section even with no session map.
    assert section_contents((content,), 'water_reports', {}, {block.key:block}) == (content,)
    removed, source = revise_included_page(block, content.source, 1, 'omit', all_sources=(content.source,))
    content = replace(content, source=source)
    assert not removed.asset_hashes and not included_pages({block.key:removed})
    draft = replace(synthetic_draft(profile, ReportPeriod(2026,9)), blocks=(removed,), sources=(source,))
    draft = replace(draft, sections=tuple(replace(section,included=True,blocks=(BlockSpec('water_reports','pdf_pages'),)) if section.key=='water' else section
                                         for section in draft.sections))
    restored = library.draft_from_dict(asdict(draft))
    blocks = {item.key:item for item in restored.blocks}
    assert source_destinations((content,), {}, blocks)[source.id] == {'water_reports'}
    assert section_contents((content,), 'water_reports', {}, blocks) == (content,)
    assert section_contents((content,), 'improvements', {}, blocks) == ()
    assert not restored.blocks[0].asset_hashes and source.selected_pages == ()
    assert source.client_page_exclusions and source.classification == 'Vendor service'
    from app.monthly_report_source_recovery import used_missing_sources
    assert used_missing_sources(restored, (source,)) == (), 'Placement alone cannot block missing-source output'
    supporting = replace(restored, blocks=(replace(restored.blocks[0], text='Retained source evidence',
                            references=(*restored.blocks[0].references, source.id+':1:source-fingerprint')),))
    assert used_missing_sources(supporting, (source,)) == (source,)

    # A fresh real section caller has no old session routing or uploader value.
    from streamlit.testing.v1 import AppTest
    from app.monthly_report_source_recovery import restore_sources
    from app import monthly_report_upload_ui as ui
    from test_monthly_report_section_uploads import APP, button
    contents, missing = restore_sources(profile, restored.sources)
    assert not missing
    monkeypatch.setattr(ui.st,'file_uploader',lambda *args,**kwargs:[])
    app=AppTest.from_string(APP,default_timeout=20)
    app.session_state['test_blocks']=blocks
    app.session_state['synthetic_evidence']=contents
    app.run()
    next(w for w in app.radio if w.label=='Section').set_value('water_reports').run()
    assert not app.exception
    assert not app.session_state['test_blocks']['water_reports'].asset_hashes
    button(app,'Include page').click().run()
    assert not app.exception
    assert app.session_state['test_blocks']['water_reports'].asset_hashes==block.asset_hashes
    assert app.session_state['test_apply_count']==1
    assert app.session_state['test_sources'][0].classification=='Vendor service'


@pytest.mark.parametrize('change', ['bytes', 'id', 'block', 'malformed', 'actual_owner'])
def test_retained_route_never_overrides_new_source_or_actual_attachment(monkeypatch,tmp_path,change):
    profile, content, block = _prepared(monkeypatch,tmp_path,pages=1)
    content=replace(content,source=replace(content.source,classification='Vendor service'))
    removed, source=revise_included_page(block,content.source,1,'omit',all_sources=(content.source,))
    blocks={removed.key:removed}
    if change=='bytes':source=replace(source,sha256='f'*64)
    elif change=='id':source=replace(source,id='f'*64)
    elif change=='block':blocks={'mbcx_report':replace(removed,key='mbcx_report')}
    elif change=='malformed':blocks={removed.key:replace(removed,references=('section-source-route:v1:water_reports:'+source.id,))}
    elif change=='actual_owner':blocks['improvements']=replace(block,key='improvements')
    assert source_destinations((replace(content,source=source),),{},blocks)[source.id]=={'improvements'}
