"""Omitted proposal artwork stays excluded until an explicit report action.

Synthetic import/AppTest/save/reopen and actual DOCX package checks; these do
not establish native-browser delivery, Office rendering or PDF acceptance.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.shared import Inches
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_followups import confirmation
from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_import import inspect_docx, imported_draft
from app.monthly_report_model import ReportFollowUp, ReportPeriod, ReportTable, ResolvedBlock, synthetic_profiles
from app.monthly_report_sections import apply_section_omissions, section_reviews
from app.monthly_report_setup import confirm_current_period, new_month_draft
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans, build_starting_import


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)
NOVEMBER = ReportPeriod(2026, 11)
CAPTION = "Synthetic actuator proposal illustration."

OMIT_APP = """
import streamlit as st
from pathlib import Path
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field

plans = st.session_state['plans']
_section_card(st.session_state['source_section'], Path(st.session_state['path']),
    st.session_state['inspection'], st.session_state['draft'].period,
    'proposal_omission', _field, plans, True, profile=st.session_state['draft'].profile)
st.session_state['plans'] = plans
"""

INCLUDE_APP = """
import streamlit as st
from dataclasses import replace
from app import monthly_report_library as library
from app.monthly_report_guided import _edit_content
from app.monthly_report_ui import _field

draft = st.session_state['draft']
block = next(value for value in draft.blocks if value.key == 'proposals')
spec = next(value for section in draft.sections for value in section.blocks if value.key == 'proposals')
state = library.load_profile(draft.profile.contract, draft.profile.key)
updated = _edit_content(spec, block, state, 'proposal_reinclude', {}, _field, draft,
                        manage_saved_pictures=False)
st.session_state['draft'] = replace(draft, blocks=tuple(
    updated if value.key == 'proposals' else value for value in draft.blocks))
"""


def block_of(draft, key="proposals"):
    return next(value for value in draft.blocks if value.key == key)


def with_block(draft, block):
    return replace(draft, blocks=tuple(block if value.key == block.key else value for value in draft.blocks))


def art_state(block):
    return (block.asset_hashes, block.asset_captions, block.references,
            block.asset_provenance, block.asset_instances, block.client_asset_reviews)


def word_output(draft):
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
        asset_loader=lambda reference: library.read_asset(draft.profile.contract, draft.profile.key, reference))
    with ZipFile(BytesIO(raw)) as archive:
        media = tuple(sha256(archive.read(name)).hexdigest()
                      for name in archive.namelist() if name.startswith("word/media/"))
    document = Document(BytesIO(raw))
    return document, media


def save_reopen(draft, *, expected_revision=0):
    saved = library.save_snapshot(draft, expected_revision=expected_revision)
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened == saved
    return reopened.draft


@pytest.fixture
def source_report(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-no-call")
    profile = synthetic_profiles()[0]
    image = BytesIO()
    Image.new("RGB", (320, 180), "navy").save(image, "PNG")
    document = Document()
    document.add_heading(profile.facilities[0].title, 0)
    document.add_paragraph("Monthly Report · September 2026")
    document.add_heading("10 Pending & Declined Proposals", 1)
    document.add_picture(BytesIO(image.getvalue()), width=Inches(3))
    path = tmp_path / "synthetic-proposals.docx"
    document.save(path)
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(inspection, profile, SEPTEMBER, ())
    plans = automatic_section_plans(inspection, analysis)
    pictures = tuple(value for value in inspection.items
                     if value.kind == "image" and value.section == "proposals")
    assert len(pictures) == 1
    # Proposal images require an explicit human purpose/privacy review. This
    # accepted manual plan uses the real builder and its normal policy gates.
    plans["proposals"].update(
        selected=[value.id for value in pictures],
        destinations={value.id: "proposals" for value in pictures},
        image_notes={value.image_part: "Synthetic equipment illustration without pricing or personal information."
                     for value in pictures},
        automatic=False, approved=True, questions=(),
    )
    mapped, _ = build_starting_import(path, inspection, plans.values())
    draft = imported_draft(profile, SEPTEMBER, "Synthetic Reviewer", mapped)
    # The operator has edited and reviewed this report caption after import.
    draft = with_block(draft, approve_all_assets(replace(
        block_of(draft), asset_captions=(CAPTION,))))
    assert block_of(draft).asset_captions == (CAPTION,)
    assert not pending_asset_indexes(block_of(draft))
    # Import into an existing generic design so the original is retained
    # independently; no native-template pin or shared artwork default is added.
    library.save_profile(profile, expected_revision=0, actor=draft.prepared_by, confirmed=True)
    library.save_report_setup(profile, draft, path, {"sha256": inspection.sha256},
        assets=mapped.assets, expected_revision=1, actor=draft.prepared_by, confirmed=True)
    original = library.imported_original(profile.contract, profile.key)
    assert original.read_bytes() == path.read_bytes()
    return draft, path, inspection, plans


def omit_through_source_review(source_report, *, draft=None):
    imported, path, inspection, plans = source_report
    draft = draft or imported
    app = AppTest.from_string(OMIT_APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.session_state["path"] = str(path)
    app.session_state["inspection"] = inspection
    app.session_state["plans"] = plans
    app.session_state["source_section"] = next(
        value for value in section_reviews(inspection) if value.key == "proposals")
    app.run()
    assert not app.exception
    next(value for value in app.radio if value.label == "What would you like to do?").set_value(
        "Leave this section out").run()
    assert not app.exception
    plan = app.session_state["plans"]["proposals"]
    assert plan["approved"] and plan["omit"]
    omitted = complete_guided_sections(apply_section_omissions(draft, (plan,)))
    assert block_of(omitted).source == "Omit"
    assert art_state(block_of(omitted)) == art_state(block_of(draft))
    return omitted


def include_through_editor(draft):
    app = AppTest.from_string(INCLUDE_APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    assert app.session_state["draft"] == draft, "A passive editor visit must retain the omission."
    buttons = [value for value in app.button if value.label == "Include in this report"]
    assert len(buttons) == 1, "Retained proposal artwork needs its explicit Include action."
    buttons[0].click().run()
    assert not app.exception
    included = app.session_state["draft"]
    assert block_of(included).source == "This month"
    app.run()
    assert not app.exception and app.session_state["draft"] == included
    assert not any(value.label == "Include in this report" for value in app.button)
    return included


@pytest.mark.parametrize("target", (OCTOBER, NOVEMBER), ids=("next-month", "two-months"))
def test_saved_omitted_art_never_reappears_in_rolled_word_output(source_report, target):
    imported, source_path, _, _ = source_report
    prior = save_reopen(omit_through_source_review(source_report))
    proposal = block_of(prior)
    profile = prior.profile
    profile_path = library._profile_path(profile.contract, profile.key)
    snapshot_path = library._profile_path(profile.contract, profile.key, snapshots=True)
    originals = {path: path.read_bytes() for path in (
        source_path, library.imported_original(profile.contract, profile.key),
        profile_path / "manifest.json", profile_path / "history" / "00000002.json",
        snapshot_path / "2026-09.json", snapshot_path / "history" / "2026-09-00000001.json")}
    prior_document, prior_media = word_output(prior)
    assert not prior_media and not prior_document.inline_shapes
    current = prior
    for period in (OCTOBER, NOVEMBER):
        current = save_reopen(complete_guided_sections(new_month_draft(current, period)))
        if period == target:
            break
    document, media = word_output(current)
    assert not media and not document.inline_shapes, "Rollover republished explicitly omitted proposal art."
    assert CAPTION not in [paragraph.text for paragraph in document.paragraphs]
    assert block_of(current).source == "Omit"
    assert art_state(block_of(current)) == art_state(proposal)
    assert not current.follow_ups
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert library.load_snapshot(profile.contract, profile.key, SEPTEMBER).draft == prior
    for reference in proposal.asset_hashes:
        assert sha256(library.read_asset(profile.contract, profile.key, reference)).hexdigest() == reference.split(".")[0]
    assert block_of(imported).source != "Omit"


def test_included_reviewed_proposal_art_still_carries_and_prints(source_report):
    draft = save_reopen(complete_guided_sections(source_report[0]))
    original_art = art_state(block_of(draft))
    for period in (OCTOBER, NOVEMBER):
        draft = save_reopen(complete_guided_sections(new_month_draft(draft, period)))
        assert block_of(draft).source == "This month"
        assert art_state(block_of(draft)) == original_art
        document, media = word_output(draft)
        assert media == tuple(reference.split(".")[0] for reference in block_of(draft).asset_hashes)
        assert len(document.inline_shapes) == 1
        assert CAPTION in [paragraph.text for paragraph in document.paragraphs]


def test_explicit_include_restores_rolled_art_without_reupload_or_source_change(source_report):
    prior = save_reopen(omit_through_source_review(source_report))
    current = save_reopen(complete_guided_sections(new_month_draft(prior, OCTOBER)))
    included = include_through_editor(current)
    assert art_state(block_of(included)) == art_state(block_of(prior))
    reopened = save_reopen(included, expected_revision=1)
    document, media = word_output(reopened)
    assert media == tuple(reference.split(".")[0] for reference in block_of(prior).asset_hashes)
    assert len(document.inline_shapes) == 1 and CAPTION in [value.text for value in document.paragraphs]
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, SEPTEMBER).draft == prior


@pytest.mark.parametrize("change", ("unreviewed", "changed-caption"))
def test_omission_and_explicit_include_never_approve_unreviewed_art(source_report, change):
    original = source_report[0]
    block = block_of(original)
    block = (replace(block, client_reviewed_fingerprint="", client_asset_reviews=()) if change == "unreviewed"
             else replace(block, asset_captions=("Changed synthetic equipment detail.",)))
    assert pending_asset_indexes(block) == (0,)
    prior = save_reopen(omit_through_source_review(source_report, draft=with_block(original, block)))
    current = complete_guided_sections(new_month_draft(prior, OCTOBER))
    document, media = word_output(current)
    assert not media and not document.inline_shapes
    included = include_through_editor(current)
    assert pending_asset_indexes(block_of(included)) == (0,)
    assert any(value.blocking and value.code == "client_pages" for value in preflight(included))
    with pytest.raises(ValueError, match="new or changed picture"):
        word_output(included)


@pytest.mark.parametrize("omitted", (False, True), ids=("included", "omitted"))
def test_equipment_art_keeps_existing_omission_and_period_review_rules(source_report, omitted):
    draft = complete_guided_sections(source_report[0])
    issue_art = approve_all_assets(replace(block_of(draft), key="equipment_issues",
                                          source="Omit" if omitted else "This month"))
    draft = replace(draft, blocks=(issue_art,))
    current = new_month_draft(draft, OCTOBER)
    carried = block_of(current, "equipment_issues")
    assert carried.asset_hashes == issue_art.asset_hashes
    assert carried.asset_captions == issue_art.asset_captions
    assert carried.asset_provenance == issue_art.asset_provenance
    assert not pending_asset_indexes(carried)
    if omitted:
        assert carried.source == "Omit"
        document, media = word_output(current)
        assert not media and not document.inline_shapes
    else:
        assert carried.source == "Last month"
        assert any(value.blocking and value.code == "carried_period" for value in preflight(current))
        with pytest.raises(ValueError, match="last confirmed for September 2026"):
            word_output(current)
        current = with_block(current, confirm_current_period(carried, OCTOBER))
        document, media = word_output(current)
        assert len(document.inline_shapes) == len(media) == 1


def test_proposal_card_states_remain_independent_of_an_omitted_art_block(source_report):
    draft = omit_through_source_review(source_report)
    items = tuple(ReportFollowUp(key, "proposal", text, SEPTEMBER.key, status=status, included=included)
                  for key, text, status, included in (
                      ("pending", "Synthetic actuator scope remains pending.", "pending", True),
                      ("declined", "Synthetic damper scope was declined.", "declined", True),
                      ("left-out", "Synthetic excluded scope.", "pending", False)))
    draft = replace(draft, follow_ups=tuple(replace(item,
        reviewed_fingerprint=confirmation(item, SEPTEMBER)) for item in items))
    current = new_month_draft(draft, OCTOBER)
    assert [(item.key, item.text, item.status, item.included) for item in current.follow_ups] == [
        (item.key, item.text, item.status, True) for item in items[:2]]
    assert all(item.carried_from == SEPTEMBER.key and not item.reviewed_fingerprint for item in current.follow_ups)
    assert any(value.blocking and value.code == "follow_up" for value in preflight(current))
    current = replace(current, follow_ups=tuple(replace(item,
        reviewed_fingerprint=confirmation(item, OCTOBER)) for item in current.follow_ups))
    document, _ = word_output(current)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert all(item.text in text for item in items[:2])
    assert items[2].text not in text
    assert draft.follow_ups[2].included is False


def test_other_monthly_content_still_clears_without_changing_its_reset_source(source_report):
    draft = complete_guided_sections(source_report[0])
    proposal = block_of(draft)
    frame = ReportTable(("Work order", "Status"), (("0007", "Complete"),), reference="synthetic-table")
    draft = replace(draft, blocks=(
        ResolvedBlock("activity_summary", "Omit", text="September inspection completed."),
        replace(proposal, key="improvements", source="Omit"),
        ResolvedBlock("work_orders", "Omit", extra_tables=(frame,)),
    ))
    current = new_month_draft(draft, OCTOBER)
    assert all(block.source == "This month" for block in current.blocks)
    assert not block_of(current, "activity_summary").text
    assert not block_of(current, "improvements").asset_hashes
    table, = block_of(current, "work_orders").extra_tables
    assert table.columns == frame.columns and not table.rows and not table.reference
    assert block_of(draft, "activity_summary").text
    assert block_of(draft, "improvements").asset_hashes == proposal.asset_hashes
    assert block_of(draft, "work_orders").extra_tables == (frame,)


def test_same_month_preserves_the_proposal_omission_without_rewriting_its_snapshot(source_report):
    draft = save_reopen(omit_through_source_review(source_report))
    current = new_month_draft(draft, SEPTEMBER)
    assert current.period == SEPTEMBER
    assert block_of(current) == block_of(draft)
    assert current.follow_ups == draft.follow_ups
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, SEPTEMBER).draft == draft
