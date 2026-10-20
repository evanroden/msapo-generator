"""R7-5: a vendor/job correction retains only its existing site decision.

The fixtures are real synthetic source bytes. AppTest exercises the Python
metadata edit path; it does not establish native browser event delivery.
"""
from base64 import urlsafe_b64encode
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json

from docx import Document
import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, SectionSpec,
)
from app.monthly_report_source_scope import correct_scope, reviewed_scope, source_review
from app.monthly_report_sources import ingest, source_bytes, source_reference

PERIOD = ReportPeriod(2026, 10)
PROFILE = ReportProfile("Synthetic scope contract", "scope-west", "Synthetic West",
                        (Facility("west", "Synthetic West"),))
TEXT = "Tested fan EF-31. The return visit remains pending."


def legacy_site_record(source):
    # The version-one on-disk format intentionally uses the historical full
    # metadata revision. Do not reinterpret a saved v1 hash as a v2 approval.
    raw = replace(source, scope_review="", selected_pages=(), captions=(),
                  client_page_reviews=(), client_page_exclusions=())
    record = {"version": 1, "source": source.id, "sha256": source.sha256,
              "revision": raw.fingerprint, "contract": PROFILE.contract,
              "kind": "sites", "facilities": ["west"]}
    encoded = urlsafe_b64encode(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).decode()
    return replace(source, scope_review=encoded)


def fixture(monkeypatch, tmp_path, *, pdf=False, legacy=False):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    if pdf:
        with fitz.open() as document:
            document.new_page().insert_text((40, 50), TEXT)
            raw = document.tobytes()
        content, _ = ingest(PROFILE, "synthetic-scope-service.pdf", raw)
    else:
        raw = TEXT.encode()
        content, _ = ingest(PROFILE, "synthetic-scope-service.txt", raw)
    source = replace(content.source, service_date="2026-10-08", classification="Vendor service",
                     vendor="Synthetic Original Vendor", work_order="SYN-031",
                     captions=((1, "Synthetic fan inspection"),))
    source = legacy_site_record(source) if legacy else correct_scope(source, PROFILE, ("west",))
    return replace(content, source=source), raw


def draft_for(source):
    block = ResolvedBlock("activity_summary", "This month", text=TEXT,
                          references=(source_reference(source, 1),))
    return ReportDraft(PROFILE, PERIOD, "Synthetic Reviewer",
        (SectionSpec("activity", "2", "Monthly Activity Summary", (BlockSpec(block.key, "rich_text"),)),),
        (block,), synthetic=True, sources=(source,))


def site_blocks(draft):
    return [check for check in preflight(draft) if check.code == "source_facility" and check.blocking]


@pytest.mark.parametrize("field,value", [("vendor", "Synthetic Corrected Vendor"), ("work_order", "SYN-032")])
def test_descriptive_edit_retains_scope_through_preflight_saved_report_and_word(monkeypatch, tmp_path, field, value):
    content, raw = fixture(monkeypatch, tmp_path)
    original = content.source
    assert reviewed_scope(original, PROFILE) is not None
    edited = replace(original, **{field: value})
    assert reviewed_scope(edited, PROFILE) is not None, "Vendor/job alone must not revoke a confirmed site."
    draft = draft_for(edited)
    assert not site_blocks(draft)
    library.save_profile(PROFILE, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Reviewer")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    assert reopened == draft and not site_blocks(reopened)
    assert source_bytes(PROFILE, reopened.sources[0]) == raw
    word = assemble_docx(reopened, acknowledged_fingerprint=reopened.fingerprint)
    assert TEXT in "\n".join(p.text for p in Document(BytesIO(word)).paragraphs)
    assert sha256(source_bytes(PROFILE, edited)).hexdigest() == original.sha256
    (tmp_path / (field + ".docx")).write_bytes(word)


@pytest.mark.parametrize("changes", [
    {"service_date": "2026-10-09"}, {"facility": "Different site"},
    {"page_texts": ("A different site's service record.",)}, {"sha256": "f" * 64},
    {"id": "a" * 64}, {"actions": "An added action"},
])
def test_descriptive_exemption_does_not_cover_scope_content_or_other_source(monkeypatch, tmp_path, changes):
    content, _ = fixture(monkeypatch, tmp_path)
    edited = replace(content.source, vendor="Synthetic Corrected Vendor", **changes)
    assert reviewed_scope(edited, PROFILE) is None
    assert site_blocks(draft_for(edited))
    with pytest.raises(ValueError, match="site scope|outside this report's selected sites"):
        assemble_docx(draft_for(edited), acknowledged_fingerprint=draft_for(edited).fingerprint)


def test_caption_and_source_site_decisions_remain_distinct_from_page_acceptance(monkeypatch, tmp_path):
    from app.monthly_report_content_policy import page_allowed, page_fingerprint
    content, _ = fixture(monkeypatch, tmp_path, pdf=True)
    source = content.source
    reviewed = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    assert page_allowed(reviewed, 1)
    changed = replace(reviewed, captions=((1, "Corrected caption"),))
    assert reviewed_scope(changed, PROFILE) is not None
    assert not page_allowed(changed, 1), "A retained site decision cannot approve a changed page caption."
    changed = replace(reviewed, page_texts=(TEXT, "Second previously unreviewed page"), selected_pages=(1, 2))
    assert reviewed_scope(changed, PROFILE) is None
    assert not page_allowed(changed, 2)


APP = '''
import streamlit as st
from app.monthly_report_upload_ui import render_uploads, _render_section_page_review
from app.monthly_report_model import ReportPeriod
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["_monthly_source_detail_anchors"] = set()
profile = st.session_state["test_profile"]
if st.session_state["test_route"] == "general":
    result, _, _ = render_uploads(profile, ReportPeriod(2026, 10), "scope", field)
    st.session_state["result"] = result[0]
else:
    result = _render_section_page_review(profile, st.session_state["content"], "scope", field,
        {}, period=ReportPeriod(2026, 10))
    st.session_state["content"] = result
    st.session_state["result"] = result.source
'''


def metadata_app(content, route):
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state["test_profile"] = PROFILE
    app.session_state["test_route"] = route
    app.session_state["scope_evidence"] = (content,)
    app.session_state["content"] = content
    app.run()
    assert not app.exception
    return app


@pytest.mark.parametrize("route", ["general", "page"])
@pytest.mark.parametrize("field,label,value", [
    ("vendor", "Vendor", "Synthetic Corrected Vendor"),
    ("work_order", "Job / work-order number", "SYN-032"),
])
def test_legacy_site_receipt_migrates_only_on_actual_descriptive_edit(monkeypatch, tmp_path, route, field, label, value):
    content, raw = fixture(monkeypatch, tmp_path, pdf=True, legacy=True)
    original = content.source
    app = metadata_app(content, route)
    assert app.session_state["result"] == original, "Opening metadata must not write a new scope receipt."
    next(w for w in app.text_input if w.label == label).set_value(value).run()
    assert not app.exception
    edited = app.session_state["result"]
    assert getattr(edited, field) == value
    assert reviewed_scope(edited, PROFILE) is not None, "Native metadata edit must preserve a valid legacy site decision."
    assert source_review(edited)["facilities"] == ["west"]
    assert not site_blocks(draft_for(edited))
    assert source_bytes(PROFILE, edited) == raw
    saved = library.draft_from_dict(asdict(draft_for(edited)))
    assert saved.sources[0] == edited and reviewed_scope(saved.sources[0], PROFILE)
    app.run()
    assert app.session_state["result"] == edited, "Neutral rerun must not reissue acceptance."


@pytest.mark.parametrize("route", ["general", "page"])
def test_stale_legacy_scope_cannot_be_repaired_by_vendor_edit(monkeypatch, tmp_path, route):
    content, raw = fixture(monkeypatch, tmp_path, pdf=True, legacy=True)
    stale = replace(content.source, service_date="2026-10-09")
    assert reviewed_scope(stale, PROFILE) is None
    app = metadata_app(replace(content, source=stale), route)
    next(w for w in app.text_input if w.label == "Vendor").set_value("Synthetic Corrected Vendor").run()
    assert not app.exception
    edited = app.session_state["result"]
    assert reviewed_scope(edited, PROFILE) is None
    assert edited.scope_review == stale.scope_review
    assert site_blocks(draft_for(edited))
    assert source_bytes(PROFILE, edited) == raw


def test_combined_changed_facts_do_not_migrate_legacy_site_approval(monkeypatch, tmp_path):
    content, _ = fixture(monkeypatch, tmp_path, pdf=True, legacy=True)
    app = metadata_app(content, "general")
    next(w for w in app.text_input if w.label == "Vendor").set_value("Synthetic Corrected Vendor")
    next(w for w in app.text_area if w.label == "Actions").set_value("Different work at another site")
    app.run()
    assert not app.exception
    edited = app.session_state["result"]
    assert reviewed_scope(edited, PROFILE) is None
    assert edited.scope_review == content.source.scope_review
    assert site_blocks(draft_for(edited))


def test_site_exemption_does_not_widen_accepted_contribution_receipts(monkeypatch, tmp_path):
    from app.monthly_report_source_scope import contribution_receipt, included_scope_valid
    content, _ = fixture(monkeypatch, tmp_path)
    original = replace(content.source, scope_review="")
    reference = source_reference(original, 1)
    receipt = contribution_receipt(reference, PROFILE, PERIOD, "activity_summary",
                                   text=TEXT, source=original)
    draft = draft_for(original)
    draft = replace(draft, blocks=(replace(draft.blocks[0], references=(reference, receipt)),))
    assert included_scope_valid(draft, original)
    changed = replace(original, work_order="A different work-order identity")
    assert not included_scope_valid(replace(draft, sources=(changed,)), changed)
    assert site_blocks(replace(draft, sources=(changed,)))
