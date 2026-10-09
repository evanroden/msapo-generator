"""Synthetic commissioning cases: standing updates and monthly evidence differ."""

from dataclasses import asdict, replace
from io import BytesIO

from docx import Document
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import (BlockSpec, DraftParagraph, ReportDraft, ReportPeriod,
                                      ResolvedBlock, SectionSpec, profile_sections, synthetic_profiles)
from app.monthly_report_setup import new_month_draft, normalize_mbcx


def legacy_draft(block=None, status=None):
    profile = replace(synthetic_profiles()[0], section_block_order=(("mbcx", ("mbcx_report",)),))
    section = SectionSpec("mbcx", "4", "MBCx Reports", (BlockSpec("mbcx_report", "pdf_pages", stock_text_keys=("mbcx_pending",)),))
    block = block or ResolvedBlock("mbcx_report", "Last month", text="Synthetic monitoring is awaiting implementation.",
                                   asset_hashes=("synthetic-page.png",), references=("synthetic-evidence",),
                                   client_reviewed_fingerprint="earlier-review")
    return ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", (section,),
                       (block, status) if status else (block,))


def test_legacy_update_is_split_without_changing_original_or_losing_pages():
    original = legacy_draft()
    before = asdict(original)
    normalized = normalize_mbcx(original)
    status, pages = {b.key: b for b in normalized.blocks}["mbcx_status"], next(b for b in normalized.blocks if b.key == "mbcx_report")
    assert status.text == original.blocks[0].text
    assert status.references == pages.references == original.blocks[0].references
    assert pages.asset_hashes == original.blocks[0].asset_hashes
    assert not pages.text and not pages.client_reviewed_fingerprint
    assert [b.key for b in normalized.sections[0].blocks] == ["mbcx_status", "mbcx_report"]
    assert asdict(original) == before
    assert normalize_mbcx(normalized) == normalized
    assert new_month_draft(original, original.period) == normalized


def test_new_month_retains_update_but_clears_monthly_pages():
    original = legacy_draft()
    following = new_month_draft(original, ReportPeriod(2026, 10))
    blocks = {b.key: b for b in following.blocks}
    assert blocks["mbcx_status"].text == original.blocks[0].text
    assert blocks["mbcx_status"].references == (*original.blocks[0].references, "report-period:2026-09", "report-origin:2026-09")
    assert not blocks["mbcx_report"].asset_hashes
    assert not blocks["mbcx_report"].references
    assert original.blocks[0].asset_hashes


def test_existing_update_and_unreviewed_ai_wording_are_not_discarded():
    paragraph = DraftParagraph("Synthetic result awaiting review.", (), ("synthetic-source",), ())
    old = ResolvedBlock("mbcx_report", "This month", text=paragraph.text,
                        ai_written=True, ai_paragraphs=(paragraph,), references=paragraph.references,
                        reviewed_fingerprint="old-review")
    previous_status = ResolvedBlock("mbcx_status", "This month", text="Synthetic colleague's existing update.")
    normalized = normalize_mbcx(legacy_draft(old, previous_status))
    status = next(b for b in normalized.blocks if b.key == "mbcx_status")
    assert previous_status.text in status.text and paragraph.text in status.text
    assert status.ai_paragraphs == (paragraph,)
    assert status.ai_written and not status.reviewed
    assert status.references == paragraph.references
    assert normalize_mbcx(normalized) == normalized


def test_explicitly_omitted_update_is_not_silently_revived():
    old = ResolvedBlock("mbcx_report", "Omit", text="Synthetic excluded wording.")
    original = legacy_draft(old)
    status = next(b for b in normalize_mbcx(original).blocks if b.key == "mbcx_status")
    assert status.source == "Omit" and status.text == old.text
    kept = ResolvedBlock("mbcx_status", "This month", text="Synthetic included wording.")
    conflict = normalize_mbcx(legacy_draft(old, kept))
    assert next(b for b in conflict.blocks if b.key == "mbcx_status") == kept
    assert next(b for b in conflict.blocks if b.key == "mbcx_report") == old


def test_new_design_has_no_automatic_commissioning_claim_and_old_orders_expose_update(monkeypatch, tmp_path):
    from app.monthly_report_start import design_seed
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = legacy_draft().profile
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor")
    specs = next(s for s in profile_sections(profile) if s.key == "mbcx").blocks
    assert [b.key for b in specs] == ["mbcx_status", "mbcx_report"]
    assert not any(b.stock_text_keys for b in specs)
    assert not any(b.text for b in draft.blocks if b.key.startswith("mbcx_"))


def test_status_only_report_prints_the_editable_update():
    from app.monthly_report_docx import assemble_docx
    draft = normalize_mbcx(legacy_draft(ResolvedBlock("mbcx_report", "Stock text", text="Synthetic reporting is pending.")))
    document = Document(BytesIO(assemble_docx(draft)))
    text = "\n".join(p.text for p in document.paragraphs)
    assert text.count("Synthetic reporting is pending.") == 1


def app_for(text="", pages=0, status=None):
    return AppTest.from_string('''
import streamlit as st
from app.monthly_report_model import DraftParagraph, ResolvedBlock
from app.monthly_report_mbcx_ui import render_mbcx
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
def edit_pages(block):
    st.caption("Shared page editor: " + str(len(block.asset_hashes)) + " pages")
    return block
st.session_state.setdefault("status", INITIAL_STATUS)
st.session_state.setdefault("pages", ResolvedBlock("mbcx_report", "This month", asset_hashes=tuple("page"+str(n) for n in range(PAGE_COUNT))))
st.session_state["status"], st.session_state["pages"] = render_mbcx(st.session_state["status"], st.session_state["pages"], "report_section", field, edit_pages)
'''.replace("INITIAL_STATUS", repr(status or ResolvedBlock("mbcx_status", "This month", text=text))).replace("PAGE_COUNT", str(pages))).run()


def test_novice_can_choose_sentence_then_edit_without_page_or_destination_dropdown():
    app = app_for()
    assert not app.exception and not app.selectbox and not app.multiselect
    assert app.session_state["status"].text == ""
    next(b for b in app.button if b.label == "Reporting has not started").click().run()
    assert app.session_state["status"].text == "Monitoring-based commissioning reporting has not started."
    app.text_area[0].set_value("Synthetic monitoring starts after equipment setup.").run()
    app.run()
    assert app.session_state["status"].text == "Synthetic monitoring starts after equipment setup."
    assert not app.session_state["pages"].asset_hashes
    assert not app.button and not app.exception


def test_returning_user_sees_exact_existing_update_and_shared_pages():
    app = app_for("Synthetic colleague's reviewed update.", 2)
    assert not app.exception
    assert app.text_area[0].value == "Synthetic colleague's reviewed update."
    assert not app.button  # starters cannot overwrite existing colleague wording
    assert any(c.value == "Shared page editor: 2 pages" for c in app.caption)
    app.text_area[0].set_value("Synthetic updated result.").run()
    assert app.session_state["pages"].asset_hashes == ("page0", "page1")


def test_source_linked_update_has_one_editor_and_retains_its_review_and_evidence():
    paragraph = DraftParagraph("Synthetic sensor was inspected.", ("fact-1",), ("source-1:1",))
    status = ResolvedBlock("mbcx_status", "This month", text="- " + paragraph.text,
                           ai_written=True, ai_paragraphs=(paragraph,),
                           references=("source-1:1",), ai_evidence_fingerprint="source-fingerprint")
    status = replace(status, reviewed_fingerprint=status.fingerprint)
    app = app_for(pages=2, status=status)
    assert not app.exception and not app.text_area and not app.checkbox and not app.button
    assert app.session_state["status"] == status
    assert any(t.value == status.text for t in app.text)
    # A change from the source editor must appear without an old local text
    # widget replacing it or returning the original paragraph on rerun.
    updated_paragraph = replace(paragraph, text="Synthetic sensor inspection is complete.")
    updated = replace(status, text="- " + updated_paragraph.text,
                      ai_paragraphs=(updated_paragraph,), reviewed_fingerprint="")
    app.session_state["status"] = updated
    app.run()
    assert not app.exception and app.session_state["status"] == updated
    assert any(t.value == updated.text for t in app.text)
    assert app.session_state["pages"].asset_hashes == ("page0", "page1")


def test_omitted_update_can_be_included_without_changing_its_wording_or_sources():
    status = ResolvedBlock("mbcx_status", "Omit", text="Synthetic monitoring report is pending.",
                           references=("report-period:2026-09", "source-1:1"))
    app = app_for(status=status)
    assert not app.exception and app.session_state["status"] == status
    next(b for b in app.button if b.label == "Include this update").click().run()
    included = replace(status, source="This month")
    assert app.session_state["status"] == included
    app.run()
    assert not app.exception and not app.button
    assert app.text_area[0].value == status.text
    assert app.session_state["status"] == included


def test_including_omitted_linked_update_preserves_sources_and_requires_source_review():
    paragraph = DraftParagraph("Synthetic monitoring is ongoing.", ("fact-1",), ("source-1:2",))
    status = ResolvedBlock("mbcx_status", "Omit", text="- " + paragraph.text,
                           ai_written=True, ai_paragraphs=(paragraph,),
                           references=("source-1:2", "report-period:2026-09"),
                           ai_evidence_fingerprint="source-fingerprint")
    status = replace(status, reviewed_fingerprint=status.fingerprint)
    app = app_for(pages=1, status=status)
    assert not app.exception and not app.text_area and not app.checkbox
    assert app.session_state["status"] == status
    next(b for b in app.button if b.label == "Include this update").click().run()
    included = replace(status, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    assert app.session_state["status"] == included
    assert not app.session_state["status"].reviewed
    app.run()
    assert not app.exception and not app.text_area and not app.checkbox and not app.button
    assert app.session_state["status"] == included
    assert app.session_state["pages"].asset_hashes == ("page0",)
