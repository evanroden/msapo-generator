"""Damaged encoded receipts stay recoverable without granting source approval."""
from base64 import urlsafe_b64encode
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_source_details import facility_choice
from app.monthly_report_source_scope import (
    USE_PREFIX, contribution_dates_bound, contribution_receipt, correct_scope,
    included_scope_valid, reviewed_scope, source_review, text_edit_references,
)
from app.monthly_report_sources import ingest, source_bytes, source_reference


def damaged_receipt(kind="array"):
    # This is a short string in saved report JSON, not deep report structure.
    # Use 10,000 levels to exceed both Linux and Windows decoder stack limits.
    raw = "[" * 10_000 + "]" * 10_000
    if kind == "object":
        raw = '{"nested":' * 10_000 + "null" + "}" * 10_000
    return urlsafe_b64encode(raw.encode()).decode()


@pytest.fixture
def sample(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[1]
    raw = b"Inspected synthetic pump.\n\nIndependent operator note."
    digest = sha256(raw).hexdigest()
    source = ReportSource(digest, "synthetic-receipt-source.txt", digest, ".txt",
        service_date="2026-09-16", classification="Vendor service", page_texts=(raw.decode(),),
        selected_pages=(1,))
    block = ResolvedBlock("activity_summary", "This month", text=raw.decode(),
                          references=(source_reference(source, 1),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor",
        (SectionSpec("activity", "2", "Monthly activity", (BlockSpec(block.key, "rich_text"),)),),
        (block,), synthetic=True, sources=(source,))
    return draft, raw


def scope_blockers(draft):
    return tuple(check for check in preflight(draft)
                 if check.code == "source_facility" and check.blocking)


@pytest.mark.parametrize("kind", ["array", "object"])
def test_damaged_scope_receipt_keeps_existing_correction_and_blocker(sample, kind):
    draft, raw = sample
    source = replace(draft.sources[0], scope_review=damaged_receipt(kind))
    damaged = replace(draft, sources=(source,))
    before = damaged.fingerprint
    assert scope_blockers(damaged)
    assert source_review(source) == {}
    assert reviewed_scope(source, draft.profile) is None
    assert facility_choice(source, draft.profile) == ""
    assert not included_scope_valid(damaged, source)
    assert damaged.fingerprint == before
    assert source.page_texts == (raw.decode(),)


@pytest.mark.parametrize("kind", ["array", "object"])
def test_damaged_contribution_cannot_establish_scope_or_dates(sample, kind):
    draft, _ = sample
    source, = draft.sources
    block = replace(draft.blocks[0], references=(
        *draft.blocks[0].references, USE_PREFIX + damaged_receipt(kind)))
    damaged = replace(draft, blocks=(block,))
    assert not included_scope_valid(damaged, source)
    assert not contribution_dates_bound(damaged, source)
    assert scope_blockers(damaged)
    # A deliberate paragraph deletion must keep undecodable evidence for review.
    assert text_edit_references(block, "Independent operator note.") == block.references


def test_saved_damaged_receipt_preserved_until_explicit_correction(sample, tmp_path):
    draft, raw = sample
    content, _ = ingest(draft.profile, "synthetic-receipt-source.txt", raw)
    source = replace(content.source, service_date="2026-09-16", classification="Vendor service")
    draft = replace(draft, sources=(source,), blocks=(replace(draft.blocks[0],
        references=(source_reference(source, 1),)),))
    damaged = replace(draft, sources=(replace(draft.sources[0], scope_review=damaged_receipt()),))
    library.save_profile(draft.profile, expected_revision=0, actor="Synthetic editor", confirmed=True)
    library.save_snapshot(damaged, expected_revision=0, entered_editor="Synthetic editor")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    assert reopened == damaged
    assert scope_blockers(reopened)
    assert {p: p.read_bytes() for p in before} == before
    # Invalid proof cannot generate a report; an explicit correction can.
    with pytest.raises(ValueError, match="Establish the site scope"):
        assemble_docx(reopened, acknowledged_fingerprint=reopened.fingerprint)
    corrected_source = correct_scope(reopened.sources[0], reopened.profile, ("north",))
    corrected = replace(reopened, sources=(corrected_source,))
    assert not scope_blockers(corrected)
    library.save_snapshot(corrected, expected_revision=1, entered_editor="Synthetic editor")
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, 1).draft == damaged
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == corrected
    word = assemble_docx(corrected, acknowledged_fingerprint=corrected.fingerprint)
    visible = "\n".join(p.text for p in Document(BytesIO(word)).paragraphs)
    assert "Inspected synthetic pump." in visible and "Independent operator note." in visible
    assert source_bytes(draft.profile, corrected_source) == raw


def test_actual_source_detail_form_opens_and_corrects_damaged_receipt(sample):
    draft, _ = sample
    source = replace(draft.sources[0], scope_review=damaged_receipt())
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
from app.monthly_report_model import synthetic_profiles
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state["source"] = render_source_details(st.session_state["source"], synthetic_profiles()[1], "receipt-recovery", field)
st.text_input("Independent report note", key="operator_note")
''', default_timeout=20)
    app.session_state["source"] = source
    app.session_state["operator_note"] = "Keep this delivered note."
    app.run()
    assert not app.exception
    assert app.session_state["source"] == source
    assert app.multiselect[0].value == []
    assert app.text_input[0].value == "Keep this delivered note."
    app.run()
    assert not app.exception and app.session_state["source"] == source
    app.multiselect[0].set_value(["north"])
    app.button[0].click().run()
    assert not app.exception
    assert reviewed_scope(app.session_state["source"], draft.profile)["facilities"] == ["north"]
    assert app.text_input[0].value == "Keep this delivered note."


@pytest.mark.parametrize("encoded", ["", "not-base64", "W10=", "bnVsbA==", "e30="])
def test_existing_invalid_receipt_controls_remain_unconfirmed(sample, encoded):
    draft, _ = sample
    source = replace(draft.sources[0], scope_review=encoded)
    assert source_review(source) == {}
    assert reviewed_scope(source, draft.profile) is None


def test_valid_receipts_keep_scope_dates_and_deliberate_paragraph_edit(sample):
    draft, _ = sample
    source, = draft.sources
    reference = source_reference(source, 1)
    block = draft.blocks[0]
    accepted_text = "Inspected synthetic pump."
    receipt = contribution_receipt(reference, draft.profile, draft.period, block.key,
        text=accepted_text, source=source, prior_block=replace(block, text="", references=()))
    block = replace(block, references=(reference, receipt))
    valid = replace(draft, blocks=(block,))
    assert included_scope_valid(valid, source)
    assert contribution_dates_bound(valid, source)
    assert not scope_blockers(valid)
    assert text_edit_references(block, "Independent operator note.") == ()
    assert not included_scope_valid(replace(valid, period=ReportPeriod(2026, 10)), source)
    changed_source = replace(source, page_texts=("Changed source facts",))
    assert not included_scope_valid(replace(valid, sources=(changed_source,)), changed_source)
    corrected = correct_scope(source, draft.profile, ("north", "south"))
    assert reviewed_scope(corrected, draft.profile)["facilities"] == ["north", "south"]
    assert reviewed_scope(corrected, replace(draft.profile, contract="Unrelated synthetic contract")) is None
