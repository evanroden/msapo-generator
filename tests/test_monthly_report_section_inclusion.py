"""Whole-section checkboxes preserve content and renumber report outputs."""
from dataclasses import asdict, replace
from io import BytesIO

import pytest
from docx import Document

from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_library import draft_from_dict
from app.monthly_report_model import ReportPeriod, included_sections, synthetic_draft, synthetic_profiles
from app.monthly_report_section_inclusion import set_section_included


def draft():
    return complete_guided_sections(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)))


def test_checkbox_omission_survives_normalization_without_changing_content_or_design():
    before = draft()
    omitted = set_section_included(before, 'training', False)
    for _ in range(3):
        omitted = complete_guided_sections(omitted)
    assert omitted.profile == before.profile
    assert omitted.blocks == before.blocks
    assert omitted.follow_ups == before.follow_ups
    assert not next(s for s in omitted.sections if s.key == 'training').included
    assert omitted.omitted_sections == ('training',)
    assert complete_guided_sections(set_section_included(omitted, 'training', True)) == before


def test_choices_round_trip_in_snapshot_and_legacy_records_still_load():
    chosen = set_section_included(draft(), 'activity', False)
    restored = draft_from_dict(asdict(chosen))
    assert restored == chosen
    assert complete_guided_sections(restored) == chosen
    old = asdict(draft())
    old.pop('omitted_sections')
    assert draft_from_dict(old).omitted_sections == ()


@pytest.mark.parametrize('bad', [['missing'], ['training','training'], 'training', [1]])
def test_malformed_saved_choices_fail_closed(bad):
    from app.monthly_report_library import LibraryError
    record = asdict(draft()); record['omitted_sections'] = bad
    with pytest.raises(LibraryError): draft_from_dict(record)


def test_numbering_is_contiguous_and_appendices_keep_their_ids():
    before = draft()
    for key in ('organization', 'activity', 'water'):
        before = set_section_included(before, key, False)
    included = included_sections(before.sections)
    ordinary = [s for s in included if not s.appendix]
    assert [s.number for s in ordinary] == list(map(str, range(1,len(ordinary)+1)))
    assert not {'organization','activity','water'} & {s.key for s in included}
    assert all(s.number == next(x.number for x in before.sections if x.key == s.key)
               for s in included if s.appendix)


def test_docx_contents_dividers_and_headings_renumber_and_omit_whole_sections():
    from app.monthly_report_docx import _build_docx
    chosen = set_section_included(draft(), 'organization', False)
    chosen = set_section_included(chosen, 'training', False)
    document = Document(BytesIO(_build_docx(chosen)))
    text = '\n'.join(p.text for p in document.paragraphs)
    xml = document._element.xml
    assert '1. Monthly Activity Summary' in xml
    assert 'Organizational Chart' not in xml
    assert 'Training Summary' not in xml
    assert 'Section 1' in text
    assert '1. Monthly Activity Summary' in text
    assert '2. Monthly Activity Summary' not in text


def test_native_whole_section_removal_excludes_retained_source_and_new_payload(tmp_path):
    from tests.test_monthly_report_native_layout import draft as native_draft, source
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_native_layout import build_native_docx
    value = native_draft(ResolvedBlock('activity_summary','This month',text='CURRENT ACTIVITY MARKER'),
                         ResolvedBlock('training_summary','This month',text='CURRENT TRAINING MARKER'))
    value = set_section_included(value,'activity',False)
    raw = build_native_docx(value,source(tmp_path))
    text = '\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
    assert 'ACTIVITY' not in text.upper()
    assert 'CURRENT TRAINING MARKER' in text
    assert 'OLD PRIVATE' not in text


def test_native_contents_and_both_divider_branches_renumber_without_editing_other_numbers():
    from types import SimpleNamespace
    from docx.oxml import OxmlElement
    from app.monthly_report_native_section_inclusion import apply_native_section_choices
    document=Document()
    contents=document.add_paragraph('Section 1: Organizational Chart')
    entry=document.add_paragraph('Section 2: Monthly Activity Summary')
    omitted_heading=document.add_paragraph('ORGANIZATIONAL CHART')
    activity=document.add_paragraph()
    # Nested frame paragraphs model independent modern/legacy copies.
    for _ in range(2):
        frame=OxmlElement('w:txbxContent'); p=OxmlElement('w:p')
        for char in ('2',):
            r=OxmlElement('w:r'); t=OxmlElement('w:t');t.text=char;r.append(t);p.append(r)
        frame.append(p);activity._p.append(frame)
    ordinary=document.add_paragraph('Unit 2 completed 25 checks')
    roots=[p._p for p in (contents,entry,omitted_heading,activity,ordinary)]
    mapping={1:'cover',2:'cover',3:'organization',4:'activity',5:'activity'}
    value=set_section_included(draft(),'organization',False)
    plan=SimpleNamespace(logical_owner={n:mapping[i+1] for i,n in enumerate(roots)})
    apply_native_section_choices(document,value,roots,{3,4},mapping,plan)
    assert contents._p.getparent() is not document.element.body
    assert entry.text=='Section 1: Monthly Activity Summary'
    assert omitted_heading._p.getparent() is None
    assert [t.text for t in activity._p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')]==['1','1']
    assert ordinary.text=='Unit 2 completed 25 checks'


def test_served_editor_checkbox_excludes_and_restores_without_losing_content(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_cover_import_task_ui import current
    app=monthly(monkeypatch,tmp_path)
    before=current(app)
    label='Include Monthly Activity Summary in this report'
    box=next(w for w in app.checkbox if w.label==label)
    box.uncheck().run()
    assert not app.exception
    omitted=current(app)
    assert omitted.omitted_sections==('activity',)
    assert next(s for s in omitted.sections if s.key=='activity').included is False
    assert next(b for b in omitted.blocks if b.key=='activity_summary')==next(b for b in before.blocks if b.key=='activity_summary')
    app.run()
    assert not next(w for w in app.checkbox if w.label==label).value
    next(w for w in app.checkbox if w.label==label).check().run()
    assert not app.exception
    assert current(app).omitted_sections==()
    assert next(s for s in current(app).sections if s.key=='activity').included


def test_native_pdf_excludes_whole_section_and_retains_remaining_content(tmp_path):
    import shutil
    import subprocess
    import pymupdf as fitz
    from tests.test_monthly_report_native_layout import draft as native_draft, source
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_native_layout import build_native_docx
    if not shutil.which('libreoffice'): pytest.skip('LibreOffice is required')
    value=native_draft(ResolvedBlock('activity_summary','This month',text='EXCLUDED ACTIVITY MARKER'),
                       ResolvedBlock('training_summary','This month',text='RETAINED TRAINING MARKER'))
    value=set_section_included(value,'activity',False)
    path=tmp_path/'chosen.docx';path.write_bytes(build_native_docx(value,source(tmp_path)))
    subprocess.run(['libreoffice','-env:UserInstallation=file://'+str(tmp_path/'lo'),
                    '--headless','--convert-to','pdf','--outdir',str(tmp_path),str(path)],check=True,capture_output=True)
    with fitz.open(tmp_path/'chosen.pdf') as pdf:
        text='\n'.join(p.get_text() for p in pdf)
    assert 'ACTIVITY' not in text.upper()
    assert 'RETAINED TRAINING MARKER' in text


def test_same_event_text_edit_is_collected_before_section_is_hidden(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_cover_import_task_ui import current
    app=monthly(monkeypatch,tmp_path)
    # Native text and checkbox changes arrive together, without an intervening
    # render or separate blur acknowledgement.
    editor=next(w for w in app.text_area if 'activity_summary' in (w.key or '') and not w.disabled)
    editor.set_value('SAME EVENT SYNTHETIC ACTIVITY')
    next(w for w in app.checkbox if w.label=='Include Monthly Activity Summary in this report').uncheck().run()
    assert not app.exception
    value=current(app)
    assert value.omitted_sections==('activity',)
    assert next(b for b in value.blocks if b.key=='activity_summary').text=='SAME EVENT SYNTHETIC ACTIVITY'



@pytest.mark.parametrize("category,section_key", [("issue", "issues"), ("proposal", "proposals")])
def test_whole_section_omission_preserves_carried_items_without_blocking_generation(category, section_key):
    from app.monthly_report_checks import preflight
    from app.monthly_report_model import ReportFollowUp

    carried = ReportFollowUp(
        key="synthetic-follow-up", category=category,
        text="Synthetic carried task: verify a later month.", carried_from="")
    before = replace(draft(), follow_ups=(carried,))
    omitted = set_section_included(before, section_key, False)
    assert omitted.follow_ups == before.follow_ups
    assert omitted.omitted_sections == (section_key,)

    # A checkbox must not require the user to destroy or individually omit
    # a retained item in the now-hidden section before generating the report.
    assert not any(check.code == "follow_up_section"
                   for check in preflight(omitted))
    assert not any(check.block_key == carried.key and check.code == "follow_up"
                   for check in preflight(omitted))
    assert draft_from_dict(asdict(omitted)).follow_ups == before.follow_ups

    # Legacy/profile-disabled sections still have the pre-existing explicit
    # follow-up review gate, rather than silently approving a missing page.
    unchosen = replace(omitted, omitted_sections=())
    assert any(check.code == "follow_up_section"
               for check in preflight(unchosen))


def test_master_design_change_prunes_only_removed_optional_omission_keys():
    before = draft()
    assert "accounts_receivable" not in {section.key for section in before.sections}
    # Model the old saved AR-inclusive master after a switch to one without
    # AR. The old optional section no longer exists but its omission does.
    orphaned = replace(before, omitted_sections=("accounts_receivable",))
    updated = complete_guided_sections(orphaned)
    assert updated.omitted_sections == ()
    assert updated.blocks == before.blocks
    assert updated.follow_ups == before.follow_ups
    assert draft_from_dict(asdict(updated)) == updated

    # Existing choices in the retained design must not be dropped by the
    # same normalization path.
    retained = set_section_included(before, "activity", False)
    both = replace(retained, omitted_sections=("activity", "accounts_receivable"))
    normalized = complete_guided_sections(both)
    assert normalized.omitted_sections == ("activity",)
    assert draft_from_dict(asdict(normalized)) == normalized



def test_omitted_activity_keeps_the_one_shared_source_manager(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    from test_cover_import_task_ui import current

    app = monthly(monkeypatch, tmp_path)
    def manager_buttons():
        return [button for button in app.button if button.label
                in {"Manage source files", "Done with source files"}]

    assert len(manager_buttons()) == 1
    next(w for w in app.checkbox
         if w.label == "Include Monthly Activity Summary in this report").uncheck().run()
    assert not app.exception
    assert current(app).omitted_sections == ("activity",)
    # Retained sections still depend on these source corrections; the global
    # file manager must remain reachable without re-including Activity.
    assert len(manager_buttons()) == 1
    manager_buttons()[0].click().run()
    assert not app.exception
    assert len(manager_buttons()) == 1
    assert current(app).omitted_sections == ("activity",)


def test_checkbox_native_default_matches_current_section_on_a_fresh_mount(monkeypatch):
    from app.monthly_report_section_inclusion import render_section_inclusion
    import streamlit as st
    seen=[]
    def native_checkbox(label, **kwargs):
        seen.append(kwargs)
        return kwargs.get('value', False)
    monkeypatch.setattr(st, 'checkbox', native_checkbox)
    value=draft()
    section=next(s for s in value.sections if s.key=='activity')
    assert render_section_inclusion(value,section,'synthetic',lambda key,default:key) is True
    assert seen[-1]['value'] is True
    omitted=set_section_included(value,'activity',False)
    section=next(s for s in omitted.sections if s.key=='activity')
    assert render_section_inclusion(omitted,section,'synthetic',lambda key,default:key) is False
    assert seen[-1]['value'] is False
