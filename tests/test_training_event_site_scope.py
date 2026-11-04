"""Explicit source sites cannot disappear into another site's Training sessions."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from docx import Document
from openpyxl import Workbook
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_training_review_flow as flow
from app.monthly_report_model import (
    BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ReportSource,
    ResolvedBlock, SectionSpec,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_scope import correct_scope
from app.monthly_report_training_import import (
    TrainingTableSource, accepted_training_block, correct_training_row,
    exclude_training_row, reimport_training_review, restore_training_review,
    review_training_table, training_review_record,
)
from app.monthly_report_training_review_ui import apply_request


PROFILE = ReportProfile("Synthetic Training scope", "north", "Site North",
                        (Facility("north", "Site North", ("North",)),))
PERIOD = ReportPeriod(2026, 9)
COLUMNS = ("Topic", "Date", "Format", "Participants", "Hours", "Status")
EVENT = ("North drill", "2026-09-13", "Virtual", "North Staff", "1", "Completed")
FOREIGN = ("Foreign South drill", "2026-09-14", "Virtual", "South Staff", "2", "Completed")
CSV = (",".join((*COLUMNS, "Site")) + "\n" +
       ",".join((*EVENT, "North")) + "\n" +
       ",".join((*FOREIGN, "Site South")) + "\n").encode()


def source_table(columns=(*COLUMNS, "Site"), rows=((*EVENT, "North"), (*FOREIGN, "Site South"))):
    return TrainingTableSource("training.csv", "a" * 64, "a" * 64, "b" * 64,
                               1, "source:" + "a" * 64 + ":1", columns, rows)


def review(columns=(*COLUMNS, "Site"), rows=((*EVENT, "North"), (*FOREIGN, "Site South")), profile=PROFILE):
    return review_training_table(source_table(columns, rows), profile, PERIOD)


@pytest.mark.parametrize("heading", ["Site", "Facility", "Hospital", "Location"])
@pytest.mark.parametrize("value", ["Site South", "Unknown campus", "", "North; South"])
def test_explicit_unresolved_event_site_requires_review(heading, value):
    current = review((*COLUMNS, heading), ((*FOREIGN, value),))
    assert not current.ready_for_import
    assert any("site" in message.casefold() for message in current.rows[0].issues)
    assert current.rows[0].origin.cells[-1] == value
    assert current.unmapped_cells(current.rows[0].key) == ((6, heading, value),)
    block = ResolvedBlock("training_summary", "This month", text="Manual notes")
    with pytest.raises(ValueError, match="Review"):
        accepted_training_block(current, block, expected_block_fingerprint=block.fingerprint)
    assert block.text == "Manual notes" and not block.extra_tables


@pytest.mark.parametrize("value", ["north", "North", "Site North", " SITE NORTH "])
def test_selected_alias_preserves_existing_five_field_event(value):
    current = review(rows=((*EVENT, value),))
    assert current.ready_for_import
    assert current.rows[0].values == EVENT[:5]
    assert current.source.rows[0][-1] == value


def test_no_site_unknown_notes_and_selected_multiple_sites_remain_supported():
    assert review(COLUMNS, (EVENT,)).ready_for_import
    assert review((*COLUMNS, "Source Notes"), ((*EVENT, "South contractor attended"),)).ready_for_import
    both = replace(PROFILE, scope_type="multi_site", facilities=(*PROFILE.facilities, Facility("south", "Site South")))
    assert review(profile=both).ready_for_import
    # Standing requirements keep their separate existing site validation.
    requirements = review_training_table(source_table(("Team member", "Site", "Safety"),
        (("North Staff", "North", "Completed"),)), PROFILE, PERIOD, source_year=2026)
    assert requirements.kind == "requirements" and requirements.ready_for_import


@pytest.mark.parametrize("columns, values", [
    (("Site", "Facility"), ("North", "South")),
    (("Site", "Site"), ("North", "North")),
])
def test_multiple_explicit_site_columns_remain_visible_for_review(columns, values):
    current = review((*COLUMNS, *columns), ((*EVENT, *values),))
    assert not current.ready_for_import
    assert current.rows[0].origin.cells[-2:] == values


def test_ambiguous_selected_alias_does_not_choose_first_facility():
    profile = replace(PROFILE, scope_type="multi_site", facilities=(*PROFILE.facilities, Facility("other", "Other Site", ("No-rth",))))
    assert not review(rows=((*EVENT, "North"),), profile=profile).ready_for_import


def test_unrelated_correction_cannot_clear_site_issue_and_omit_is_explicit():
    current = review()
    row = current.rows[1]
    corrected = correct_training_row(current, row.key, {"Hours": "1.5"},
        expected_revision=current.revision, profile=PROFILE, period=PERIOD)
    assert not corrected.ready_for_import and corrected.rows[1].issues
    assert corrected.rows[1].origin == row.origin
    assert reimport_training_review(corrected, current) == corrected
    omitted = exclude_training_row(corrected, row.key, expected_revision=corrected.revision)
    assert omitted.ready_for_import and len(omitted.rows) == 2
    block = ResolvedBlock("training_summary", "This month", text="Manual notes")
    accepted = accepted_training_block(omitted, block, expected_block_fingerprint=block.fingerprint)
    assert accepted.extra_tables[0].rows == (EVENT[:5],)
    assert accepted.text == block.text and current.source == omitted.source


@pytest.mark.parametrize("kind", ["xlsx", "docx"])
def test_real_workbook_or_word_extraction_retains_site_evidence(tmp_path, kind):
    physical = ((*COLUMNS, "Site"), (*EVENT, "North"), (*FOREIGN, "Site South"))
    if kind == "xlsx":
        book = Workbook()
        for row in physical:
            book.active.append(row)
        buffer = BytesIO()
        book.save(buffer)
        original = buffer.getvalue()
        table, = sources._spreadsheet(original, ".xlsx")
        item = source_table(table.columns, table.rows)
    else:
        from app.monthly_report_import import inspect_docx
        document = Document()
        document.add_heading("12 Training Summary", 1)
        table = document.add_table(rows=0, cols=7)
        for row in physical:
            for cell, value in zip(table.add_row().cells, row):
                cell.text = value
        path = tmp_path / "original.docx"
        document.save(path)
        original = path.read_bytes()
        inspection = inspect_docx(path)
        table, = (item for item in inspection.items if item.kind == "table")
        assert table.section == "training"
        item = replace(source_table(table.rows[0], table.rows), native_word=True,
                       word_item_id=table.id, word_section=table.section)
    current = review_training_table(item, PROFILE, PERIOD)
    assert current.rows[0].issues == ()
    assert any("site" in message.casefold() for message in current.rows[1].issues)
    assert current.rows[1].origin.cells == physical[2]
    assert item == current.source
    if kind == "docx":
        assert path.read_bytes() == original


def draft_for(content):
    section = SectionSpec("training", "12", "Training Summary", (BlockSpec("training_summary", "rich_text"),))
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor", (section,),
        (ResolvedBlock("training_summary", "This month", text="Manual notes"),), sources=(content.source,), synthetic=True)


@pytest.fixture
def read_only_source(monkeypatch):
    """Real CSV parsing; only persisted byte lookup/reingest is supplied in memory."""
    digest = sha256(CSV).hexdigest()
    tables = sources._spreadsheet(CSV, ".csv")
    source = ReportSource(digest, "training.csv", digest, ".csv",
        page_texts=tuple("\n".join(["\t".join(t.columns), *("\t".join(r) for r in t.rows)]) for t in tables))
    source = correct_scope(source, PROFILE, ("north",))
    content = sources.SourceContent(source, tables)
    monkeypatch.setattr(flow, "source_content", lambda draft, original: content)
    monkeypatch.setattr(sources, "source_bytes", lambda profile, original: CSV)
    return draft_for(content)


def prepare(draft):
    source = draft.sources[0]
    request = {"scope": flow.scope(draft), "source_id": source.id, "source": source.fingerprint,
               "table": 1, "expected": "", "action": "prepare", "values": {"year": ""}}
    prepared = apply_request(draft, request)
    value = flow.saved_review(prepared, source, 1)
    return prepared, value, request


def publish(draft, value, request):
    return apply_request(draft, {**request, "action": "publish", "expected": flow.revision(value),
        "block": draft.blocks[0].fingerprint, "values": {}})


@pytest.mark.parametrize("historical", [False, True])
def test_old_ready_receipt_is_revalidated_before_current_or_historical_publication(read_only_source, historical):
    draft, value, request = prepare(read_only_source)
    original = restore_training_review(value["record"])
    # A valid integrity receipt written before site validation, not damaged JSON.
    old = replace(original, rows=tuple(replace(row, issues=()) for row in original.rows))
    if historical:
        row = old.rows[1]
        old = replace(old, rows=(old.rows[0], replace(row,
            values=(row.values[0], "2026-08-14", *row.values[2:]),
            issues=("Historical/other-month session: not completed this month.",))))
    old_value = {**value, "record": training_review_record(old),
                 "history": [old.rows[1].key] if historical else []}
    retained = flow.store_review(draft, old_value, flow.revision(value))
    with pytest.raises(ValueError, match="Review|historical"):
        publish(retained, old_value, request)
    assert retained.blocks == draft.blocks
    assert flow.encoded(flow.saved_review(retained, retained.sources[0], 1)) == flow.encoded(old_value)


@pytest.mark.parametrize("change", ["contract", "facility", "period"])
def test_old_receipt_never_moves_to_another_report_scope(read_only_source, change):
    draft, value, request = prepare(read_only_source)
    if change == "contract":
        other = replace(draft, profile=replace(PROFILE, contract="Another synthetic contract"))
    elif change == "facility":
        other = replace(draft, profile=replace(PROFILE, facilities=(Facility("south", "Site South"),)))
    else:
        other = replace(draft, period=ReportPeriod(2026, 10))
    with pytest.raises(ValueError, match="different report or month"):
        publish(other, value, request)
    assert other.blocks == draft.blocks and other.source_row_reviews == draft.source_row_reviews


def test_already_published_rows_and_later_manual_work_are_not_rewritten(read_only_source):
    draft, value, request = prepare(read_only_source)
    review = restore_training_review(value["record"])
    legacy = replace(review, rows=tuple(replace(row, issues=()) for row in review.rows))
    # Model an intact pre-fix publication, using the unchanged low-level API.
    block = accepted_training_block(legacy, draft.blocks[0],
                                    expected_block_fingerprint=draft.blocks[0].fingerprint)
    from dataclasses import asdict
    old = {**value, "record": training_review_record(legacy)}
    old = {**old, "published": {"decision": flow.revision((old["record"], [], False)),
        "block": block.fingerprint, "before": asdict(draft.blocks[0]),
        "replace_source": False, "replace_matrix": False}}
    saved = flow.store_review(replace(draft, blocks=(block,)), old, flow.revision(value))
    edited = replace(saved, blocks=(replace(block, text="Later manual note", extra_tables=()),))
    assert publish(saved, old, request) == saved
    assert publish(edited, old, request) == edited


def test_changed_original_still_blocks_publication_after_explicit_omission(read_only_source, monkeypatch):
    draft, value, request = prepare(read_only_source)
    review = restore_training_review(value["record"])
    omitted = flow.change_row(draft, value, review.rows[1].key, {"Hours": "2"}, excluded=True)
    retained = flow.store_review(draft, omitted, flow.revision(value))
    monkeypatch.setattr(sources, "source_bytes", lambda profile, source: CSV + b"\n")
    with pytest.raises(ValueError, match="original changed"):
        publish(retained, omitted, request)
    assert retained.blocks == draft.blocks and retained.sources == draft.sources


APP = '''
import streamlit as st
from app.monthly_report_training_review_ui import render_training_import
draft = st.session_state['draft']
draft, _ = render_training_import(draft, {b.key:b for b in draft.blocks}, 'site-review')
st.session_state['draft'] = draft
'''


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def click(app, label):
    widget(app, "button", label).click().run()
    assert not app.exception


def template(tmp_path):
    document = Document()
    document.add_paragraph("Site North")
    document.add_heading("12 Training Summary", 1)
    document.add_paragraph("Original placeholder")
    table = document.add_table(rows=2, cols=5)
    for cell, value in zip(table.rows[0].cells, COLUMNS[:5]):
        cell.text = value
    table.rows[1].cells[0].text = "Native placeholder"
    path = tmp_path / "training-design.docx"
    document.save(path)
    return path


def test_actual_review_widgets_require_omission_and_native_word_keeps_selected_session(read_only_source, tmp_path):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = read_only_source
    app.run()
    assert not app.exception
    click(app, "Review this Training table")
    click(app, "Include reviewed Training rows")
    assert not app.session_state["draft"].blocks[0].extra_tables
    assert any("Review" in item.value for item in app.warning)
    widget(app, "selectbox", "Training row to review").select(1).run()
    assert any("Site South" in item.value for item in app.text)
    widget(app, "text_input", "Hours").set_value("1.5")
    click(app, "Save Training row review")
    click(app, "Include reviewed Training rows")
    assert not app.session_state["draft"].blocks[0].extra_tables
    widget(app, "checkbox", "Omit this Training source row").check()
    click(app, "Save Training row review")
    click(app, "Include reviewed Training rows")
    accepted = app.session_state["draft"]
    assert accepted.blocks[0].extra_tables[0].rows == (EVENT[:5],)
    path = template(tmp_path)
    before = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(accepted, path, section_key="training")))
    rows = [tuple(c.text for c in row.cells) for table in output.tables for row in table.rows]
    assert EVENT[:5] in rows and not any("Foreign South drill" in row for row in rows)
    assert path.read_bytes() == before and accepted.sources == read_only_source.sources


def test_old_ready_receipt_shows_site_problem_without_rewriting_saved_decisions(read_only_source):
    draft, value, _ = prepare(read_only_source)
    original = restore_training_review(value["record"])
    old = replace(original, rows=tuple(replace(row, issues=()) for row in original.rows))
    old_value = {**value, "record": training_review_record(old)}
    retained = flow.store_review(draft, old_value, flow.revision(value))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = retained
    app.run()
    assert not app.exception
    assert "site" in app.dataframe[0].value.iloc[1]["Review needed"].casefold()
    assert app.session_state["draft"] == retained
    click(app, "Include reviewed Training rows")
    assert app.session_state["draft"] == retained
    widget(app, "selectbox", "Training row to review").select(1).run()
    widget(app, "checkbox", "Omit this Training source row").check()
    click(app, "Save Training row review")
    click(app, "Include reviewed Training rows")
    accepted = app.session_state["draft"]
    assert accepted.blocks[0].extra_tables[0].rows == (EVENT[:5],)
    receipt = flow.saved_review(accepted, accepted.sources[0], 1)
    assert restore_training_review(receipt["record"]).rows[1].excluded
    assert restore_training_review(receipt["record"]).source == old.source


def test_public_storage_saved_review_reopen_history_and_word(tmp_path, monkeypatch):
    """Required real persistence/public wrapper coverage; no platform skip or fake lock."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    content, _ = sources.ingest(PROFILE, "training.csv", CSV)
    content = replace(content, source=correct_scope(content.source, PROFILE, ("north",)))
    draft, value, request = prepare(draft_for(content))
    first = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    receipt = flow.saved_review(reopened, reopened.sources[0], 1)
    with pytest.raises(ValueError, match="Review"):
        publish(reopened, receipt, request)
    current = restore_training_review(receipt["record"])
    omitted = flow.change_row(reopened, receipt, current.rows[1].key, {"Hours": "2"}, excluded=True)
    revised = flow.store_review(reopened, omitted, flow.revision(receipt))
    accepted = publish(revised, omitted, request)
    library.save_snapshot(accepted, expected_revision=first.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, first.revision).draft == first.draft
    assert sources.source_bytes(PROFILE, content.source) == CSV
    path = template(tmp_path)
    output = Document(BytesIO(build_native_docx(accepted, path, section_key="training")))
    rows = [tuple(c.text for c in row.cells) for table in output.tables for row in table.rows]
    assert EVENT[:5] in rows and not any("Foreign South drill" in row for row in rows)
