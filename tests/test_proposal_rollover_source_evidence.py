"""Carried proposals retain only their already-attached source-page evidence."""
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_followups import confirmation, problems, seed_followups
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, ReportDraft, ReportFollowUp, ReportPeriod, ReportSource,
    ReportTable, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_setup import new_month_draft
from app.monthly_report_structured_uploads import native_update

PROFILE = synthetic_profiles()[0]
SEPTEMBER, OCTOBER = ReportPeriod(2026, 9), ReportPeriod(2026, 10)
COLUMNS = ("Facility", "Vendor", "Scope", "Status")
ROW = ("Demo North", "Synthetic Vendor", "Replace aging controls", "Pending")
CSV = (",".join(COLUMNS) + "\n" + ",".join(ROW) + "\n").encode()
SECTION = SectionSpec("proposals", "11", "Pending & Declined Proposals", (
    BlockSpec("proposals", "table", columns=tuple(ColumnSpec(str(n), title)
        for n, title in enumerate(COLUMNS))),))


def parsed(suffix=".csv", decision="Pending"):
    raw = CSV.replace(b"Pending", decision.encode())
    if suffix == ".xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(COLUMNS)
        workbook.active.append((*ROW[:3], decision))
        stream = BytesIO()
        workbook.save(stream)
        raw = stream.getvalue()
    tables = sources._spreadsheet(raw, suffix)
    digest = sha256(raw).hexdigest()
    source = ReportSource(digest, "synthetic-proposal" + suffix, digest, suffix,
        page_texts=tuple("\n".join(["\t".join(t.columns), *("\t".join(r) for r in t.rows)])
                         for t in tables), selected_pages=(1,))
    return sources.SourceContent(source, tables), raw


def report(block=None, source=None):
    content, _ = parsed()
    source = source or content.source
    return ReportDraft(PROFILE, SEPTEMBER, "Synthetic Editor", (SECTION,),
        (block or native_update((replace(content, source=source),), "proposals"),), sources=(source,))


def template(tmp_path):
    doc = Document()
    doc.add_heading("11 Pending & Declined Proposals", 1)
    doc.add_paragraph("Synthetic proposal layout.")
    path = tmp_path / "proposal-layout.docx"
    doc.save(path)
    return path


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("decision", ["Pending", "Declined"])
def test_real_parser_native_import_keeps_evidence_across_two_months(suffix, decision):
    content, raw = parsed(suffix, decision)
    prior = report(native_update((content,), "proposals"), content.source)
    before = asdict(prior)
    expected = (sources.source_reference(content.source, 1),)
    assert prior.blocks[0].references == expected
    following = new_month_draft(prior, OCTOBER)
    assert following.follow_ups[0].references == expected
    assert following.sources == prior.sources
    assert following.follow_ups[0].status == decision.casefold()
    assert "Replace aging controls" in following.follow_ups[0].text
    later = new_month_draft(following, ReportPeriod(2026, 11))
    assert later.follow_ups[0].references == expected and later.sources == prior.sources
    assert sha256(raw).hexdigest() == content.source.sha256 and asdict(prior) == before
    assert library.draft_from_dict(json.loads(json.dumps(asdict(following)))) == following


@pytest.mark.parametrize("kind", ["narrative", "rows", "explicit_table", "fallback_table"])
def test_new_candidates_keep_source_pages_without_bookkeeping(kind):
    source = parsed()[0].source
    reference = sources.source_reference(source, 1)
    refs = ("report-period:2026-09", reference, "report-origin:2026-08", reference,
            "docx:" + "a" * 64 + ":table-1", "source-scope-use:v1:synthetic")
    block = ResolvedBlock("proposals", "This month", references=refs)
    if kind == "narrative":
        block = replace(block, text="Replace aging controls; Status: Pending")
    elif kind == "rows":
        block = replace(block, rows=(ROW,))
    else:
        block = replace(block, extra_tables=(ReportTable(COLUMNS, (ROW,),
            reference=reference if kind == "explicit_table" else ""),))
    following = new_month_draft(report(block, source), OCTOBER)
    assert following.follow_ups[0].references == (reference,)
    confirmed = replace(following.follow_ups[0],
        reviewed_fingerprint=confirmation(following.follow_ups[0], OCTOBER))
    assert not problems(confirmed, following)


@pytest.mark.parametrize("precise", [True, False])
def test_table_reference_precedes_block_fallback_without_unrelated_sources(precise):
    source = parsed()[0].source
    other = replace(source, id="other-source", filename="other.csv")
    unused = replace(source, id="unused-source", filename="not-attached.csv")
    first, second = sources.source_reference(source, 1), sources.source_reference(other, 1)
    block = ResolvedBlock("proposals", "This month", references=(second,), extra_tables=(
        ReportTable(COLUMNS, (ROW,), reference=first if precise else ""),))
    prior = replace(report(block, source), sources=(source, other, unused))
    following = new_month_draft(prior, OCTOBER)
    assert following.follow_ups[0].references == ((first,) if precise else (second,))
    assert following.sources == ((source,) if precise else (other,))


@pytest.mark.parametrize("reference", ["docx:" + "a" * 64 + ":table-1", "report-period:2026-09"])
def test_explicit_non_page_table_context_never_borrows_another_tables_source(reference):
    source = parsed()[0].source
    block = ResolvedBlock("proposals", "This month", references=(sources.source_reference(source, 1),),
        extra_tables=(ReportTable(COLUMNS, (ROW,), reference=reference),))
    following = new_month_draft(report(block, source), OCTOBER)
    assert following.follow_ups[0].references == () and following.sources == ()


@pytest.mark.parametrize("change", ["missing", "stale"])
def test_missing_or_stale_original_evidence_still_requires_explicit_correction(change):
    prior = report()
    reference = prior.blocks[0].references[0]
    changed = replace(prior, sources=() if change == "missing" else
        (replace(prior.sources[0], findings="Source details were corrected"),))
    following = new_month_draft(changed, OCTOBER)
    item = following.follow_ups[0]
    assert item.references == (reference,)
    item = replace(item, reviewed_fingerprint=confirmation(item, OCTOBER))
    assert any("source changed or is missing" in warning for warning in problems(item, following))
    assert following.sources == changed.sources


@pytest.mark.parametrize("mode", ["same_key", "manual_key", "removed_links"])
def test_existing_matched_proposals_keep_manual_edits_and_source_removal(mode):
    prior = report()
    item = seed_followups(prior)[0]
    reference = prior.blocks[0].references
    item = replace(item, references=() if mode == "removed_links" else reference,
                   update="Manager note", evidence_note="Retain this explanation")
    if mode == "same_key":
        item = replace(item, text="Manager corrected scope", status="declined")
    if mode == "manual_key":
        item = replace(item, key="separately-saved-manual-key")
    prior = replace(prior, follow_ups=(item,))
    following = new_month_draft(prior, OCTOBER)
    assert len(following.follow_ups) == 1
    carried = following.follow_ups[0]
    assert (carried.key, carried.text, carried.status, carried.references, carried.update, carried.evidence_note) == (
        item.key, item.text, item.status, item.references, item.update, item.evidence_note)


@pytest.mark.parametrize("mode", ["omitted", "empty_table", "unreferenced"])
def test_omitted_empty_and_manual_content_does_not_acquire_sources(mode):
    prior = report()
    block = prior.blocks[0]
    if mode == "omitted":
        block = replace(block, source="Omit")
    elif mode == "empty_table":
        block = replace(block, rows=(), extra_tables=(ReportTable(COLUMNS, (), reference=block.references[0]),))
    else:
        block = replace(block, references=())
    following = new_month_draft(replace(prior, blocks=(block,)), OCTOBER)
    assert not any(item.references for item in following.follow_ups) and not following.sources
    if mode in ("omitted", "empty_table"):
        assert not following.follow_ups


def test_precise_sibling_tables_keep_their_own_source_and_price_policy():
    prior = report()
    first = prior.sources[0]
    second = replace(first, id="another-source", filename="second.csv")
    refs = tuple(sources.source_reference(s, 1) for s in (first, second))
    block = ResolvedBlock("proposals", "This month", references=refs, extra_tables=tuple(
        ReportTable((*COLUMNS, "Amount"), ((*ROW[:2], f"Scope {n}", "Pending", "$1200"),), reference=ref)
        for n, ref in enumerate(refs)))
    following = new_month_draft(replace(prior, blocks=(block,), sources=(first, second)), OCTOBER)
    assert tuple(item.references for item in following.follow_ups) == tuple((ref,) for ref in refs)
    assert following.sources == (first, second)
    assert all("1200" not in item.text and "$" not in item.text for item in following.follow_ups)


def test_foreign_source_evidence_keeps_existing_scope_guard_authoritative():
    from app.monthly_report_source_scope import included_scope_valid
    source = replace(parsed()[0].source, facility="Demonstration South Facility")
    following = new_month_draft(report(source=source), OCTOBER)
    assert following.sources == (source,)
    assert not included_scope_valid(following, source)


APP = '''import streamlit as st
from app.monthly_report_followups import render_followups
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state['draft'] = render_followups(st.session_state['draft'], 'evidence', field, category='proposal')
'''


def click(app, label):
    next(item for item in app.button if item.label == label).click().run()
    assert not app.exception


def test_actual_proposal_edit_keeps_supporting_page_after_confirmation_and_word(tmp_path):
    prior = report()
    following = new_month_draft(prior, OCTOBER)
    app = AppTest.from_string(APP)
    app.session_state["draft"] = following
    app.run()
    click(app, "Update proposal")
    control = next(item for item in app.multiselect if item.label == "Supporting source pages (optional)")
    assert control.value == list(prior.blocks[0].references)
    assert control.options == ["synthetic-proposal.csv · page 1"]
    click(app, "Confirm update")
    app.run()
    current = app.session_state["draft"]
    assert current.follow_ups[0].references == prior.blocks[0].references
    assert current.sources == prior.sources and not problems(current.follow_ups[0], current)
    path = template(tmp_path)
    before = path.read_bytes()
    word = Document(BytesIO(_build_native_docx(current, path, section_key="proposals")))
    text = "\n".join(p.text for p in word.paragraphs)
    assert text.count("Replace aging controls") == 1 and "Pending" in text
    assert path.read_bytes() == before


def test_nonproposal_issue_carryover_retains_existing_evidence_behavior():
    prior = report()
    source = prior.sources[0]
    item = ReportFollowUp("issue-key", "issue", "Synthetic valve leak", "2026-09",
                         references=prior.blocks[0].references)
    prior = replace(prior, blocks=(), follow_ups=(item,))
    following = new_month_draft(prior, OCTOBER)
    assert following.follow_ups[0].references == item.references and following.sources == (source,)


def test_actual_missing_source_requires_deliberate_link_removal():
    prior = report()
    following = new_month_draft(replace(prior, sources=()), OCTOBER)
    app = AppTest.from_string(APP)
    app.session_state["draft"] = following
    app.run()
    assert not app.exception
    assert any("source links are unavailable" in warning.value for warning in app.warning)
    assert next(item for item in app.button if item.label == "Confirm update").disabled
    checkbox = next(item for item in app.checkbox if item.label == "Remove unavailable source links")
    checkbox.check().run()
    click(app, "Confirm update")
    current = app.session_state["draft"]
    assert not current.follow_ups[0].references and not problems(current.follow_ups[0], current)
    assert prior.blocks[0].references and prior.sources
    later = new_month_draft(current, ReportPeriod(2026, 11))
    assert not later.follow_ups[0].references


def test_public_storage_original_history_and_saved_rollover_word(tmp_path, monkeypatch):
    """Required real Linux persistence/public output; no lock replacement or skip."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    content, _ = sources.ingest(PROFILE, "synthetic-proposal.csv", CSV)
    from app.monthly_report_source_scope import correct_scope
    content = replace(content, source=correct_scope(content.source, PROFILE, ("north",)))
    prior = report(native_update((content,), "proposals"), content.source)
    saved = library.save_snapshot(prior, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, SEPTEMBER).draft
    following = new_month_draft(reopened, OCTOBER)
    assert following.follow_ups[0].references == prior.blocks[0].references
    following = replace(following, follow_ups=tuple(replace(item,
        reviewed_fingerprint=confirmation(item, OCTOBER)) for item in following.follow_ups))
    library.save_snapshot(following, expected_revision=0, entered_editor="Synthetic Editor")
    current = library.load_snapshot(PROFILE.contract, PROFILE.key, OCTOBER).draft
    assert current == following and current.sources == prior.sources
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, SEPTEMBER, saved.revision).draft == saved.draft
    assert sources.source_bytes(PROFILE, content.source) == CSV
    output = Document(BytesIO(build_native_docx(current, template(tmp_path), section_key="proposals")))
    assert "Replace aging controls" in "\n".join(p.text for p in output.paragraphs)
