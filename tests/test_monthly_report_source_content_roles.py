"""Invented template prose must be reviewed, not promoted to monthly facts."""
from dataclasses import replace
import json

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_sections import section_reviews
from app.monthly_report_start_import import (
    analyze_starting_report, automatic_section_plans, build_starting_import,
)
from test_monthly_report_start_import import PERIOD, report_file

INSTRUCTIONS = (
    "Author instructions: Describe the work completed this month.",
    "Example: Replaced a synthetic pump on September 4, 2026.",
    "[Insert monthly summary here]",
    "This section should include the completed maintenance activities.",
)
STANDING = "Inspect the synthetic pump monthly and record vibration readings."


def setup_source(tmp_path, texts, month="September 2026", *, table=False):
    path = report_file(tmp_path, activity=texts, month=month, contact=False, table=table)
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(inspection, synthetic_profiles()[0], PERIOD)
    plans = automatic_section_plans(inspection, analysis)
    return path, inspection, analysis, plans


@pytest.mark.parametrize("text", INSTRUCTIONS)
def test_explicit_template_text_needs_a_decision_before_automatic_reuse(tmp_path, text):
    path, inspection, analysis, plans = setup_source(tmp_path, (STANDING, text))
    source = next(item for item in inspection.items if item.text == text)
    assert not plans["activity"]["approved"]
    assert source.id not in plans["activity"]["selected"]
    assert source.id not in analysis.current_items
    with pytest.raises(ValueError, match="starting-report questions"):
        build_starting_import(path, inspection, plans.values())


def test_example_date_cannot_establish_current_work_under_an_old_cover(tmp_path):
    _, inspection, analysis, _ = setup_source(tmp_path, (INSTRUCTIONS[1],), month="July 2026")
    source = next(item for item in inspection.items if item.text == INSTRUCTIONS[1])
    assert source.id not in analysis.current_items
    assert source.id in analysis.uncertain_items


def test_unmarked_standing_prose_and_ambiguous_example_mention_are_not_discarded(tmp_path):
    text = "A sample was collected; the repaired pump provides an example of the inspection method."
    path, inspection, analysis, plans = setup_source(tmp_path, (STANDING, text))
    assert plans["activity"]["approved"]
    mapped, _ = build_starting_import(path, inspection, plans.values())
    block = next(block for block in mapped.blocks if block.key == "activity_summary")
    assert block.text == STANDING + "\n\n" + text


APP = '''
import streamlit as st
from app.monthly_report_section_ui import _section_card
from app.monthly_report_sections import section_reviews
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
section = next(s for s in section_reviews(st.session_state['inspection']) if s.key == 'activity')
_section_card(section, st.session_state['path'], st.session_state['inspection'],
    ReportPeriod(2026, 9), 'roles_test', _field, st.session_state['plans'], True)
'''


def role_app(path, inspection, plans):
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state['path'] = path
    app.session_state['inspection'] = inspection
    app.session_state['plans'] = plans
    app.run()
    assert not app.exception
    return app


def role_radio(app):
    return next(w for w in app.radio if w.label.startswith('Use source paragraph'))


def test_exclude_instruction_keeps_neighbors_and_survives_reentry_and_serialization(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (STANDING, INSTRUCTIONS[0], 'September 2026 verified repair.'))
    original = path.read_bytes()
    app = role_app(path, inspection, plans)
    assert not app.session_state['plans']['activity']['approved']
    role_radio(app).set_value('exclude').run()
    assert not app.exception and not app.error
    after = app.session_state['plans']
    assert after['activity']['approved']
    mapped, _ = build_starting_import(path, inspection, after.values())
    text = next(b.text for b in mapped.blocks if b.key == 'activity_summary')
    assert text == STANDING + '\n\nSeptember 2026 verified repair.'
    app.run()
    assert role_radio(app).value == 'exclude'
    stored = json.loads(json.dumps(app.session_state['plans']))
    reopened = role_app(path, inspection, stored)
    assert role_radio(reopened).value == 'exclude'
    again, _ = build_starting_import(path, inspection, reopened.session_state['plans'].values())
    assert again.blocks == mapped.blocks
    assert path.read_bytes() == original


def test_include_requires_verified_replacement_and_preserves_source_reference(tmp_path):
    from app.monthly_report_source_content_roles import source_stamp
    path, inspection, _, plans = setup_source(tmp_path, (STANDING, INSTRUCTIONS[1]))
    app = role_app(path, inspection, plans)
    role_radio(app).set_value('include').run()
    assert not app.exception
    assert not app.session_state['plans']['activity']['approved']
    next(w for w in app.text_area if w.label == 'Verified report wording').set_value('September 2026 verified pump inspection.').run()
    assert not app.exception and not app.error
    updated = app.session_state['plans']
    mapped, _ = build_starting_import(path, inspection, updated.values())
    block = next(b for b in mapped.blocks if b.key == 'activity_summary')
    source = next(i for i in inspection.items if i.text == INSTRUCTIONS[1])
    assert block.text == STANDING + '\n\nSeptember 2026 verified pump inspection.'
    assert f'docx:{inspection.sha256}:{source.id}' in block.references
    # A copied receipt cannot silently approve later changed report wording.
    changed = json.loads(json.dumps(updated))
    changed['activity']['texts'][source.id] = 'Unconfirmed later wording.'
    with pytest.raises(ValueError, match='verified report wording'):
        build_starting_import(path, inspection, changed.values())
    assert updated['activity']['content_role_reviews'][source.id]['stamp'] == source_stamp(inspection.sha256, source)


def test_new_source_bytes_with_same_item_ids_invalidate_old_role_choice(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (STANDING, INSTRUCTIONS[0]))
    app = role_app(path, inspection, plans)
    role_radio(app).set_value('exclude').run()
    reviewed = json.loads(json.dumps(app.session_state['plans']))
    changed = replace(inspection, sha256='f' * 64)
    with pytest.raises(ValueError, match='source instructions or examples again'):
        build_starting_import(path, changed, reviewed.values())
    app.session_state['inspection'] = changed
    app.run()
    assert not app.exception
    assert role_radio(app).value == ''
    assert not app.session_state['plans']['activity']['approved']


def test_direct_approved_plan_cannot_bypass_source_role_decision(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (INSTRUCTIONS[0],))
    item = next(i for i in inspection.items if i.text == INSTRUCTIONS[0])
    plan = plans['activity']
    plan.update(approved=True, selected=[item.id], texts={item.id: item.text})
    with pytest.raises(ValueError, match='source instructions or examples again'):
        build_starting_import(path, inspection, plans.values())


def test_role_review_does_not_restore_old_month_prose(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path,
        ('July 2026 completed repair.', INSTRUCTIONS[1]), month='July 2026')
    app = role_app(path, inspection, plans)
    role_radio(app).set_value('exclude').run()
    assert not app.exception and not app.error
    mapped, _ = build_starting_import(path, inspection, app.session_state['plans'].values())
    assert not any(b.text for b in mapped.blocks)


def test_prior_edited_aggregate_is_not_split_or_reset(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (STANDING, INSTRUCTIONS[0]))
    texts = [i for i in inspection.items if i.section == 'activity' and i.kind == 'text'
             and not i.note.startswith('Native') and i.text in (STANDING, INSTRUCTIONS[0])]
    assert len(texts) == 2
    edited = 'Existing edited plant instruction.\n\nAuthor instructions: Resolve this remaining example.'
    plans['activity'].update(selected=[texts[0].id], combined_text_ids=[i.id for i in texts],
                             texts={texts[0].id: edited})
    app = role_app(path, inspection, plans)
    assert any(t.value == edited for t in app.text)
    next(w for w in app.radio if w.label == 'Use this edited section text').set_value('include').run()
    editor = next(w for w in app.text_area if w.label == 'Verified report wording')
    assert editor.value == edited
    editor.set_value('Existing edited plant instruction.\n\nVerified September 2026 inspection.').run()
    assert not app.exception and not app.error
    mapped, _ = build_starting_import(path, inspection, app.session_state['plans'].values())
    assert 'Existing edited plant instruction.' in mapped.blocks[0].text
    assert 'Verified September 2026 inspection.' in mapped.blocks[0].text


def test_excluded_receipt_cannot_be_inserted_as_combined_text(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (STANDING, INSTRUCTIONS[0]))
    app = role_app(path, inspection, plans)
    role_radio(app).set_value('exclude').run()
    plan = app.session_state['plans']['activity']
    source = next(i for i in inspection.items if i.text == INSTRUCTIONS[0])
    plan['combined_text_ids'] = [*plan['selected'], source.id]
    with pytest.raises(ValueError, match='Excluded source instructions'):
        build_starting_import(path, inspection, app.session_state['plans'].values())


@pytest.mark.parametrize("table", [False, True])
def test_starting_flow_saves_only_reviewed_text_and_native_word_excludes_instruction(tmp_path, monkeypatch, table):
    from io import BytesIO
    from docx import Document
    from app import monthly_report_library as library
    from app.monthly_report_docx import assemble_docx
    from test_monthly_report_start_import import start_app, save_start
    path, inspection, _, _ = setup_source(tmp_path, (STANDING, INSTRUCTIONS[0], 'September 2026 verified maintenance.'), table=table)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    assert next(b for b in app.button if b.label == 'Continue to this month’s updates').disabled
    role_radio(app).set_value('exclude').run()
    assert not app.exception
    draft = save_start(app)
    block = next(b for b in draft.blocks if b.key == 'activity_summary')
    assert block.text == STANDING + '\n\nSeptember 2026 verified maintenance.'
    assert library.load_imported_draft(draft.profile.contract, draft.profile.key) == draft
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original
    # This exercises the retained/native Word path, not only mapped Python text.
    # Empty required sections remain unresolved; explicitly omit them for this
    # Activity-only output rather than waive the normal required-content gate.
    output_draft = replace(draft, sections=tuple(
        replace(s, included=s.key == 'activity') for s in draft.sections))
    raw = assemble_docx(output_draft, acknowledged_fingerprint=output_draft.fingerprint)
    output = Document(BytesIO(raw))
    text = '\n'.join(output.element.body.itertext())
    assert INSTRUCTIONS[0] not in text
    assert STANDING in text and 'September 2026 verified maintenance.' in text
    assert path.read_bytes() == original


def test_report_only_edit_delivered_with_exclusion_remains_recoverable(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (STANDING, INSTRUCTIONS[1]))
    app = role_app(path, inspection, plans)
    role_radio(app).set_value('include').run()
    area = next(w for w in app.text_area if w.label == 'Verified report wording')
    area.set_value('September 2026 typed but not yet blurred.')
    role_radio(app).set_value('exclude').run()
    assert not app.exception
    role_radio(app).set_value('include').run()
    assert next(w for w in app.text_area if w.label == 'Verified report wording').value == 'September 2026 typed but not yet blurred.'
    assert app.session_state['plans']['activity']['approved']


def test_price_in_verified_replacement_still_blocks(tmp_path):
    path, inspection, _, plans = setup_source(tmp_path, (INSTRUCTIONS[0],))
    app = role_app(path, inspection, plans)
    role_radio(app).set_value('include').run()
    next(w for w in app.text_area if w.label == 'Verified report wording').set_value('September 2026 repair cost $500.').run()
    assert not app.exception
    assert not app.session_state['plans']['activity']['approved']
    assert any('pricing' in e.value for e in app.error)


def test_foreign_site_template_does_not_force_review_or_import_its_narrative(tmp_path):
    profile = synthetic_profiles()[0]
    path = report_file(tmp_path, title=synthetic_profiles()[1].facilities[1].title,
                       activity=(INSTRUCTIONS[0], STANDING), contact=False)
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(inspection, profile, PERIOD, synthetic_profiles()[1].facilities)
    assert analysis.site_relation == 'other'
    plans = automatic_section_plans(inspection, analysis)
    assert plans['activity']['approved']
    mapped, _ = build_starting_import(path, inspection, plans.values())
    assert not any(b.text for b in mapped.blocks)
