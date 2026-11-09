"""Ambiguous free-text CMMS sites need explicit review before counts or output.

All evidence and report history are synthetic. AppTest emits the real native
uploader; only its byte transport, initial scope/date, and preview rendering are
supplied here. No paid reader or browser/production acceptance is implied.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from io import BytesIO, StringIO
import csv
import json
import os
from pathlib import Path

from docx import Document
from openpyxl import Workbook
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_cmms import CMMSMapping, map_cmms, month_window
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
    default_sections, profile_sections,
)
from app.monthly_report_native_layout import build_native_docx
from tests.conftest import requires_libreoffice


PERIOD = ReportPeriod(2026, 10)
COLUMNS = ("ID", "Finished", "Facility", "Type", "Status", "Task", "Area", "Tag")
TASK = "Inspected synthetic pump P-TEST-1."
SAFE_TASK = "Repaired synthetic valve V-SAFE-2."
MANUAL = "Operator retained a separate inspection note."
MANUAL_ROW = ("West Plant", "WO-MANUAL-9", "2026-10-09", "Manual area",
              "Operator entered a previously confirmed inspection.", "MANUAL-9")
APP = """
from app.monthly_report_guided import render_guided_workflow
from app.monthly_report_ui import _field, _move
render_guided_workflow('afafafafafafafafafafafafafafafaf', 'UTC', _field, _move)
"""


@pytest.fixture(autouse=True)
def synthetic_runtime(tmp_path, monkeypatch):
    from app import monthly_report_ai as ai
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(ai, "cached", lambda *args, **kwargs: None)

    def forbidden(*args, **kwargs):
        pytest.fail("Synthetic CMMS regression cannot call a paid model")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(ai, "request_json", forbidden)


def profile(relationship="title", reverse=False):
    east = Facility("east", "North") if relationship == "title" else Facility(
        "east", "East Plant", ("NORTH",))
    facilities = (Facility("north", "West Plant"), east)
    if reverse:
        facilities = tuple(reversed(facilities))
    return ReportProfile("Synthetic CMMS ambiguity", "both-plants", "Both plants",
                         facilities, "multi_site")


def row(site="north", *, identity="WO-TEST-1", finished="2026-10-12",
        category="Preventive", status="Closed", task=TASK):
    return (identity, finished, site, category, status, task, "Plant room", "P-TEST-1")


def mapping(profile, **changes):
    value = CMMSMapping(
        "Finished", "ID", facility="Facility", description="Task", area="Area", tag="Tag",
        category="Type", status="Status", completed_statuses=("Closed",),
        pm_values=("Preventive",), cm_values=("Corrective",),
        complete_months=month_window(PERIOD),
        complete_facilities=tuple(site.key for site in profile.facilities),
    )
    return replace(value, **changes)


def source(profile, rows, suffix=".csv"):
    if suffix == ".csv":
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        raw = output.getvalue().encode()
    else:
        workbook = Workbook()
        workbook.active.append(COLUMNS)
        for values in rows:
            workbook.active.append(values)
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        raw = output.getvalue()
    content, attachments = sources.ingest(profile, "synthetic-cmms" + suffix, raw)
    assert not attachments
    assert sources.source_bytes(profile, content.source) == raw
    return content, raw


def mapped(profile, content, selected=None):
    return map_cmms(content.tables[0], selected or mapping(profile), profile, PERIOD,
                    sources.source_reference(content.source, 1), scope_source=content.source)


def october(result):
    return {row[1]: row[2:] for row in result.blocks[1].rows if row[0] == PERIOD.key}


def assert_unresolved(result):
    assert all(row[2:] == ("", "", "") for row in result.blocks[1].rows), (
        "Ambiguous completed work cannot authorize any complete count or invented zero"
    )
    assert any("ambig" in notice.casefold() for notice in result.notices), result.notices


@pytest.mark.parametrize("relationship", ["title", "alias"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("label", ["north", " \tNoRtH\t "])
def test_public_import_never_assigns_cross_site_label_by_membership_order(
        relationship, reverse, suffix, label):
    selected = profile(relationship, reverse)
    content, raw = source(selected, (row(label),), suffix)
    before = asdict(content)
    result = mapped(selected, content)
    assert result.blocks[0].rows == (), "No site is authorized by this competing free-text label"
    assert_unresolved(result)
    assert not any("outside this profile" in notice for notice in result.notices)
    assert sources.source_reference(content.source, 1) in result.blocks[0].references
    assert asdict(content) == before
    assert sources.source_bytes(selected, content.source) == raw


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("same_identity", [False, True])
def test_ambiguous_row_does_not_remove_safe_sibling_or_assert_partial_totals(reverse, same_identity):
    selected = profile(reverse=reverse)
    content, raw = source(selected, (
        row(),
        row("West Plant", identity="WO-TEST-1" if same_identity else "WO-SAFE-2",
            category="Corrective", task=SAFE_TASK),
    ))
    result = mapped(selected, content)
    assert result.blocks[0].rows == ((
        "West Plant", "WO-TEST-1" if same_identity else "WO-SAFE-2",
        "2026-10-12", "Plant room", SAFE_TASK, "P-TEST-1",
    ),)
    assert_unresolved(result)
    assert sources.source_bytes(selected, content.source) == raw


@pytest.mark.parametrize("label", ["north", " NORTH ", "West Plant", "WEST PLANT"])
def test_repeated_key_title_alias_of_one_site_stays_a_single_candidate(label):
    selected = ReportProfile("Synthetic CMMS ambiguity", "repeated", "Repeated",
        (Facility("north", "West Plant", ("north", "NORTH", "West Plant")),
         Facility("east", "East Plant")), "multi_site")
    content, _ = source(selected, (row(label),))
    result = mapped(selected, content)
    assert result.blocks[0].rows[0][0] == "West Plant"
    assert october(result) == {"West Plant": ("1", "0", "1"), "East Plant": ("0", "0", "0")}
    assert not any("ambig" in notice.casefold() for notice in result.notices)


@pytest.mark.parametrize("both_sites", [False, True])
@pytest.mark.parametrize("label", ["", " ", "\t"])
def test_permitted_empty_aliases_do_not_resolve_a_blank_source_site(both_sites, label):
    selected = ReportProfile("Synthetic CMMS ambiguity", "blanks", "Blank aliases",
        (Facility("north", "West Plant", ("", " \t")),
         Facility("east", "East Plant", ("",) if both_sites else ())), "multi_site")
    content, raw = source(selected, (row(label),))
    result = mapped(selected, content)
    assert not result.blocks[0].rows
    assert all(values[2:] == ("", "", "") for values in result.blocks[1].rows)
    assert any("outside this profile" in notice for notice in result.notices)
    assert not any("ambig" in notice.casefold() for notice in result.notices)
    assert sources.source_bytes(selected, content.source) == raw


@pytest.mark.parametrize("label", ["Unlisted Plant", "North  Bay"])
def test_genuine_unknown_and_internal_space_difference_keep_existing_review(label):
    selected = ReportProfile("Synthetic CMMS ambiguity", "unknown", "Unknown",
        (Facility("north", "West Plant", ("North Bay",)), Facility("east", "East Plant")),
        "multi_site")
    content, _ = source(selected, (row(label), row("West Plant", identity="WO-SAFE-2", task=SAFE_TASK)))
    result = mapped(selected, content)
    assert len(result.blocks[0].rows) == 1 and result.blocks[0].rows[0][1] == "WO-SAFE-2"
    assert all(values[2:] == ("", "", "") for values in result.blocks[1].rows)
    assert any("outside this profile" in notice for notice in result.notices)
    assert not any("ambig" in notice.casefold() for notice in result.notices)


@pytest.mark.parametrize("assigned", ["north", "east"])
@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_assignment_is_authority_only_when_no_facility_column_is_mapped(assigned, reverse):
    selected = profile(reverse=reverse)
    content, _ = source(selected, (row(),))
    competing = mapped(selected, content, mapping(selected, assigned_facility=assigned))
    assert not competing.blocks[0].rows
    assert_unresolved(competing)
    corrected = mapped(selected, content, mapping(selected, facility="", assigned_facility=assigned))
    title = next(site.title for site in selected.facilities if site.key == assigned)
    assert corrected.blocks[0].rows[0][0] == title
    assert october(corrected)[title] == ("1", "0", "1")
    assert all(values == (("1", "0", "1") if name == title else ("0", "0", "0"))
               for name, values in october(corrected).items())
    assert not any("ambig" in notice.casefold() for notice in corrected.notices)


@pytest.mark.parametrize("category_mapped", [False, True])
def test_confirmation_of_all_months_and_sites_cannot_override_ambiguous_work(category_mapped):
    selected = profile()
    content, _ = source(selected, (row(category="Corrective"),))
    result = mapped(selected, content, mapping(selected, category="Type" if category_mapped else ""))
    assert_unresolved(result)
    assert not result.blocks[0].rows


def test_open_ambiguous_rows_do_not_invalidate_genuinely_complete_empty_export():
    selected = profile()
    content, _ = source(selected, (row(status="Open"),))
    result = mapped(selected, content)
    assert not result.blocks[0].rows
    assert all(values[2:] == ("0", "0", "0") for values in result.blocks[1].rows)
    assert not any("ambig" in notice.casefold() for notice in result.notices)


@pytest.mark.parametrize("conflicting", [False, True])
def test_known_site_duplicate_and_conflicting_work_order_rules_are_preserved(conflicting):
    selected = profile()
    first = row("West Plant")
    second = row("West Plant", task="Different confirmed task.") if conflicting else first
    content, _ = source(selected, (first, second))
    result = mapped(selected, content)
    assert not any("ambig" in notice.casefold() for notice in result.notices)
    if conflicting:
        assert not result.blocks[0].rows
        assert all(values[2:] == ("", "", "") for values in result.blocks[1].rows)
        assert any("conflicting" in notice for notice in result.notices)
    else:
        assert len(result.blocks[0].rows) == 1
        assert october(result)["West Plant"] == ("1", "0", "1")
        assert any("counted once" in notice for notice in result.notices)


def test_explicit_assignment_without_category_retains_total_but_no_pm_cm_invention():
    selected = profile()
    content, _ = source(selected, (row(),))
    result = mapped(selected, content, mapping(selected, facility="", assigned_facility="north", category=""))
    assert october(result)["West Plant"] == ("", "", "1")


def draft_from_result(selected, content, result):
    selected = replace(selected, block_overrides=tuple(spec for spec in result.specs if spec.type == "table"),
        excluded_sections=tuple(section.key for section in default_sections()
                                if section.key not in ("activity", "maintenance")))
    blocks = list(result.blocks)
    blocks.append(ResolvedBlock("activity_summary", "This month", text=MANUAL))
    specs = {spec.key: spec for spec in result.specs}
    sections = tuple(replace(section, blocks=tuple(specs.get(block.key, block) for block in section.blocks))
                     for section in profile_sections(selected))
    return ReportDraft(selected, PERIOD, "Synthetic Reviewer", sections,
                       tuple(blocks), sources=(content.source,))


def assert_word_rows(raw, draft):
    document = Document(BytesIO(raw))
    tables = [tuple(tuple(cell.text for cell in row.cells) for row in table.rows)
              for table in document.tables]
    for block in draft.blocks:
        if block.key in ("service_calls", "work_orders") and block.rows:
            assert any(all(row in table for row in block.rows) for table in tables), (
                block.key, block.rows, tables,
            )
    text = "\n".join([p.text for p in document.paragraphs] +
                     [cell for table in tables for row in table for cell in row])
    assert MANUAL in text
    return text


def native_word(draft, tmp_path, name):
    template = Document()
    template.add_paragraph("Both plants")
    template.add_paragraph("October 2026")
    template.add_heading("2 Monthly Activity Summary", 1)
    template.add_paragraph("Prior activity placeholder.")
    counts = template.add_table(rows=2, cols=5)
    for cell, title in zip(counts.rows[0].cells,
                           ("Month", "Facility", "PM completed", "CM completed", "Total completed")):
        cell.text = title
    template.add_heading("5 Maintenance Schedule / In-House Maintenance", 1)
    template.add_paragraph("Prior maintenance placeholder.")
    calls = template.add_table(rows=2, cols=6)
    for cell, title in zip(calls.rows[0].cells,
                           ("Facility", "WO #", "Finish Date", "Area", "Task Code-Description", "Tag #")):
        cell.text = title
    path = tmp_path / (name + "-design.docx")
    template.save(path)
    original = path.read_bytes()
    output = build_native_docx(draft, path)
    assert path.read_bytes() == original
    return output


@pytest.mark.parametrize("assigned", [False, True])
def test_both_word_routes_keep_unknown_counts_and_deliberate_assignment(assigned, tmp_path):
    selected = profile()
    content, raw = source(selected, (row(),))
    choice = mapping(selected, facility="", assigned_facility="north") if assigned else mapping(selected)
    result = mapped(selected, content, choice)
    draft = draft_from_result(selected, content, result)
    if assigned:
        assert october(result) == {"West Plant": ("1", "0", "1"), "North": ("0", "0", "0")}
    else:
        assert_unresolved(result)
        assert not result.blocks[0].rows
    for word in (assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint),
                 native_word(draft, tmp_path, "assigned" if assigned else "unresolved")):
        text = assert_word_rows(word, draft)
        assert ("WO-TEST-1" in text) is assigned
    assert sources.source_bytes(selected, content.source) == raw


def current_draft(app):
    return next(value for key, value in app.session_state.filtered_state.items()
                if key.startswith("report_guided_") and key.endswith("_draft") and hasattr(value, "blocks"))


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def guided_app(monkeypatch, raw, reverse):
    from app import monthly_report_guided as guided
    from app import monthly_report_start_ui as start
    from app import monthly_report_section_preview_ui as preview

    selected = profile(reverse=reverse)
    empty = sources.SourceTable("Empty", COLUMNS, ())
    specs = map_cmms(empty, mapping(selected), selected, PERIOD, "synthetic-empty").specs
    selected = replace(selected, block_overrides=(specs[0],),
        excluded_sections=tuple(section.key for section in default_sections()
                                if section.key not in ("activity", "maintenance")))
    first = ReportDraft(selected, PERIOD, "Synthetic Reviewer", profile_sections(selected), (
        ResolvedBlock("service_calls", "This month", rows=(MANUAL_ROW,)),
        ResolvedBlock("activity_summary", "This month", text=MANUAL),
    ))
    library.save_profile(selected, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    saved = library.save_snapshot(first, expected_revision=0, entered_editor="Synthetic Reviewer")
    monkeypatch.setattr(guided, "operator_today", lambda tz: date(2026, 11, 7))
    monkeypatch.setattr(start, "choose_contract", lambda *args: selected.contract)
    monkeypatch.setattr(start, "select_sites", lambda *args, **kwargs: (selected, selected))
    monkeypatch.setattr(preview, "render_section_preview", lambda *args, **kwargs: None)
    app = AppTest.from_string(APP, default_timeout=45).run()
    assert not app.exception
    widget(app, "text_input", "Prepared by").set_value("Synthetic Reviewer").run()
    assert not app.exception
    assert next(block.rows for block in current_draft(app).blocks if block.key == "service_calls") == (MANUAL_ROW,)
    native_uploader = st.file_uploader

    def uploaded(label, *args, **kwargs):
        emitted = native_uploader(label, *args, **kwargs)
        if label == "Add source files":
            stream = BytesIO(raw)
            stream.name = "synthetic-cmms.csv"
            return [stream]
        return emitted

    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    assert not app.exception and len(app.get("file_uploader")) >= 1
    for label, value in (
        ("Finish date column", "Finished"), ("Work-order identity column", "ID"),
        ("Facility column", "Facility"), ("Description column", "Task"),
        ("Area column", "Area"), ("Equipment tag column", "Tag"),
        ("PM/CM category column", "Type"), ("Completion status column", "Status"),
    ):
        widget(app, "selectbox", label).select(value)
    app.run()
    widget(app, "multiselect", "Statuses that mean completed").set_value(["Closed"])
    widget(app, "multiselect", "Category values that mean PM").set_value(["Preventive"])
    widget(app, "multiselect", "Months with complete export coverage").set_value([PERIOD.key])
    widget(app, "multiselect", "Facilities covered completely in those months").set_value(["north", "east"])
    widget(app, "button", "Use these spreadsheet columns").click().run()
    assert not app.exception
    return app, selected, saved, native_uploader, uploaded


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("add_unresolved_first", [False, True])
def test_guided_mapping_correction_word_save_reopen_and_history_preserve_manual_work(
        reverse, add_unresolved_first, tmp_path, monkeypatch):
    selected = profile(reverse=reverse)
    _, raw = source(selected, (row(),))
    app, selected, first, native_uploader, uploaded = guided_app(monkeypatch, raw, reverse)
    versions = [first]
    if add_unresolved_first:
        assert any("ambig" in notice.value.casefold() for notice in app.warning)
        widget(app, "button", "Add selected pages and tables to report").click().run()
        assert not app.exception and not app.error, [item.value for item in app.error]
        unresolved = current_draft(app)
        pending = {block.key: block for block in unresolved.blocks}
        assert pending["service_calls"].rows == (MANUAL_ROW,)
        assert len(pending["work_orders"].rows) == 24
        assert all(row[2:] == ("", "", "") for row in pending["work_orders"].rows)
        word = assemble_docx(unresolved, acknowledged_fingerprint=unresolved.fingerprint)
        assert "WO-TEST-1" not in assert_word_rows(word, unresolved)
        widget(app, "button", "Save shared version").click().run()
        assert not app.exception
        versions.append(library.load_snapshot(selected.contract, selected.key, PERIOD))

    widget(app, "selectbox", "Facility column").select("").run()
    widget(app, "selectbox", "Assign this export to a facility").select("north")
    widget(app, "button", "Use these spreadsheet columns").click().run()
    assert not app.exception
    assert not any("ambig" in notice.value.casefold() for notice in app.warning)
    widget(app, "button", "Add selected pages and tables to report").click().run()
    assert not app.exception and not app.error, [item.value for item in app.error]
    corrected = current_draft(app)
    blocks = {block.key: block for block in corrected.blocks}
    assert MANUAL_ROW in blocks["service_calls"].rows
    imported = [row for row in blocks["service_calls"].rows if row[1] == "WO-TEST-1"]
    assert imported == [("West Plant", "WO-TEST-1", "2026-10-12", "Plant room", TASK, "P-TEST-1")]
    assert {row[1]: row[2:] for row in blocks["work_orders"].rows if row[0] == PERIOD.key} == {
        "West Plant": ("1", "0", "1"), "North": ("0", "0", "0"),
    }
    assert blocks["activity_summary"].text == MANUAL
    for word in (assemble_docx(corrected, acknowledged_fingerprint=corrected.fingerprint),
                 native_word(corrected, tmp_path, "guided")):
        assert "WO-TEST-1" in assert_word_rows(word, corrected)
    original = corrected.sources[0]
    original_path = sources._path(selected, original.sha256, original.suffix)
    original_state = (original_path.read_bytes(), original_path.stat().st_ino, original_path.stat().st_mtime_ns)
    assert original_state[0] == raw
    widget(app, "button", "Save shared version").click().run()
    assert not app.exception
    saved = library.load_snapshot(selected.contract, selected.key, PERIOD)
    assert saved.revision == len(versions) + 1
    for version in versions:
        assert library.load_snapshot_version(selected.contract, selected.key, PERIOD, version.revision) == version

    monkeypatch.setattr(st, "file_uploader", native_uploader)
    app.run()
    reopened = AppTest.from_string(APP, default_timeout=45).run()
    assert not reopened.exception
    assert {block.key: block.rows for block in current_draft(reopened).blocks
            if block.key in ("service_calls", "work_orders")} == {
        key: blocks[key].rows for key in ("service_calls", "work_orders")
    }
    monkeypatch.setattr(st, "file_uploader", uploaded)
    reopened.run()
    assert not reopened.exception
    assert next(block.text for block in current_draft(reopened).blocks if block.key == "activity_summary") == MANUAL
    assert {block.key: block.rows for block in current_draft(reopened).blocks
            if block.key in ("service_calls", "work_orders")} == {
        key: blocks[key].rows for key in ("service_calls", "work_orders")
    }
    assert current_draft(reopened).sources == saved.draft.sources
    assert library.load_snapshot(selected.contract, selected.key, PERIOD) == saved
    assert (original_path.read_bytes(), original_path.stat().st_ino, original_path.stat().st_mtime_ns) == original_state


@requires_libreoffice
def test_real_native_pdf_preserves_unresolved_and_explicit_site_evidence(tmp_path, monkeypatch):
    import fitz
    from app import pdf_converter

    selected = profile()
    content, original = source(selected, (row(),))
    artifacts = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "cmms-ambiguous-facilities"
    artifacts.mkdir(parents=True, exist_ok=True)
    records = []

    def rendered_rows(pages, token):
        # Anchor by actual word position, independent of PDF page breaks and
        # text-block reading order. These short site labels fit on one line.
        result = []
        for words in pages:
            for anchor in (word for word in words if word[4] == token):
                middle = (anchor[1] + anchor[3]) / 2
                result.append(tuple(word[4] for word in sorted(words, key=lambda word: word[0])
                                    if word[1] - 2 <= middle <= word[3] + 2))
        return result

    for assigned in (False, True):
        choice = mapping(selected, facility="", assigned_facility="north") if assigned else mapping(selected)
        result = mapped(selected, content, choice)
        draft = draft_from_result(selected, content, result)
        if not assigned:
            assert_unresolved(result)
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
        name = "assigned" if assigned else "unresolved"
        word = native_word(draft, tmp_path, name)
        assert_word_rows(word, draft)
        path = tmp_path / (name + ".docx")
        path.write_bytes(word)
        monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
        pdf = pdf_converter.convert_to_pdf(path).read_bytes()
        with fitz.open(stream=pdf, filetype="pdf") as document:
            text = " ".join(" ".join(page.get_text().split()) for page in document)
            pages = [page.get_text("words") for page in document]
        assert MANUAL in text
        assert ("WO-TEST-1" in text) is assigned
        count_rows = rendered_rows(pages, PERIOD.key)
        expected = [
            ("2026-10", "West", "Plant", *(("1", "0", "1") if assigned else ())),
            ("2026-10", "North", *(("0", "0", "0") if assigned else ())),
        ]
        assert sorted(count_rows) == sorted(expected), count_rows
        service_rows = rendered_rows(pages, "WO-TEST-1")
        if assigned:
            assert len(service_rows) == 1 and service_rows[0][:3] == ("West", "Plant", "WO-TEST-1")
        else:
            assert not service_rows
        (artifacts / (name + ".docx")).write_bytes(word)
        (artifacts / (name + ".pdf")).write_bytes(pdf)
        records.append({"name": name, "docx_sha256": sha256(word).hexdigest(),
                        "pdf_sha256": sha256(pdf).hexdigest(), "assigned_work_order_present": assigned,
                        "rendered_october_rows": count_rows, "rendered_service_rows": service_rows})
    assert sources.source_bytes(selected, content.source) == original
    (artifacts / "synthetic-source.csv").write_bytes(original)
    (artifacts / "manifest.json").write_text(json.dumps({
        "synthetic_only": True, "commit": os.environ.get("MSAPO_SHA", ""),
        "source_sha256": sha256(original).hexdigest(), "source_unchanged": True,
        "outputs": records, "model_calls": 0,
    }, indent=2))
