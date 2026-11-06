"""Hold only regular, whole-file tabular text with explicit site and work columns."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import ReportPeriod, ReportSource, ResolvedBlock
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_recovery import restore_sources
from tests.test_activity_docx_site_table_boundaries import PROFILE, PERIOD, draft_for, template


LOCAL = "Inspected target pump P-1."
FOREIGN = "Repaired foreign pump F-9."
SAFE = "Calibrated separate sensor Z-4."
MANUAL = "Operator retained the earlier verified wording."
TABLE = f"Site\tWork performed\nNorth\t{LOCAL}\nForeign South\t{FOREIGN}"


def txt(text, name="synthetic.txt"):
    digest = sha256(text.encode()).hexdigest()
    return sources.SourceContent(ReportSource(digest, name, digest, ".txt",
        facility="north", service_date="2026-09-04", page_texts=(text,), selected_pages=(1,)))


@pytest.mark.parametrize("site,work", [
    ("Site", "Work performed"), ("Facility Name", "Activity"), ("BuildingCode", "Actions"),
    ("Location ID", "Work description"), ("Client", "Service notes"),
    ("Customer", "Service details"), ("HospitalKey", "Findings"),
])
@pytest.mark.parametrize("site_last", [True, False])
def test_regular_table_requires_mapping_in_either_order(site, work, site_last):
    rows = ((site, work), ("North", LOCAL), ("Foreign South", FOREIGN))
    text = "\r\n".join("\t".join(reversed(row) if site_last else row) for row in rows)
    item = txt("\r\n" + text + "\r\n")
    block = structured.native_update((item,), "activity_summary")
    assert not block.text and not block.references
    assert structured.reader_sources((item,), "activity_summary") == ()
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]
    assert structured.reader_sources((item,), "proposals") == (item,)
    assert item.source.page_texts == ("\r\n" + text + "\r\n",)


@pytest.mark.parametrize("text", [
    "Site\tWork performed",
    "Site\tWork performed\n\t",
    "Site\tWork performed\n" + FOREIGN,
    TABLE + "\nA separate narrative paragraph.",
    "Service report\n" + TABLE,
    "Inspected site conditions.\tRecorded a finding.\nNorth\t" + FOREIGN,
    TABLE.replace("Site\t", "Website\t"),
    TABLE.replace("Site\t", "Site inspection notes\t"),
    TABLE.replace("Work performed", "Scope notes"),
    TABLE.replace("Site\t", "Asset\t"),
    TABLE + "\nForeign South\t" + FOREIGN + "\tPending",
    TABLE.replace("\t", "|"),
    "2026-09-04 | Synthetic | Activity\n" + LOCAL,
])
def test_prose_ragged_rows_unrelated_headings_and_other_delimiters_keep_their_route(text):
    item = txt(text)
    assert structured.reader_sources((item,), "activity_summary") == (item,)
    assert not structured.reader_notices((item,), "activity_summary")


@pytest.mark.parametrize("text,expected", [
    (SAFE, SAFE),
    ("Asset\tWork performed\nP-1\t" + LOCAL, LOCAL),
    ("2026-09-04 | WO-01 | Vendor service\n" + LOCAL, LOCAL),
])
def test_ordinary_narrative_asset_table_and_dated_entry_keep_legitimate_work(text, expected):
    assert expected in structured.native_update((txt(text),), "activity_summary").text


def test_legacy_multiple_text_items_do_not_invent_a_whole_file_table():
    item = txt(TABLE)
    item = replace(item, source=replace(item.source, page_texts=(TABLE, SAFE)))
    assert structured.reader_sources((item,), "activity_summary") == (item,)
    assert SAFE in structured.native_update((item,), "activity_summary").text


def test_extra_regular_columns_and_blank_site_cell_still_require_mapping():
    item = txt("Asset\tSite\tActions\nP-1\t\t" + LOCAL + "\nF-9\tForeign South\t" + FOREIGN)
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]
    assert not structured.native_update((item,), "activity_summary").text


def test_reader_requests_and_old_mixed_result_keep_only_safe_sibling_evidence():
    item, sibling = txt(TABLE), txt(SAFE, "sibling.txt")
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    payload = structured.reader_batches(PROFILE, (item, sibling), "activity_summary")
    assert item.source.id not in str(payload) and sibling.source.id in str(payload)
    result = {"items": [
        {"source": item.source.id, "page": 1, "text": FOREIGN, "row": []},
        {"source": sibling.source.id, "page": 1, "text": SAFE, "row": []},
    ]}
    block, pages = structured.reader_update((item, sibling), "activity_summary", result, manual)
    assert block.text == MANUAL + "\n\n" + SAFE and not pages
    assert block.references == (sources.source_reference(sibling.source, 1),)
    with pytest.raises(ValueError, match="site-specific"):
        structured.reader_update((item,), "activity_summary", {"items": result["items"][:1]}, manual)


@pytest.mark.parametrize("saved_text", [MANUAL, ""])
def test_previously_reviewed_or_deleted_narrative_stays_as_saved(saved_text):
    item = txt(TABLE)
    prior = ResolvedBlock("activity_summary", "This month", text=saved_text,
                          references=(sources.source_reference(item.source, 1),))
    assert structured.native_update((item,), "activity_summary", prior) == prior


def test_counted_work_order_route_still_has_first_choice(monkeypatch):
    from app import monthly_report_work_order_csv as work_orders
    # Simulate the classified source only to test route precedence.
    monkeypatch.setattr(work_orders, "is_work_order_source", lambda content: True)
    assert "Review counted work-order rows" in structured.reader_notices((txt(TABLE),), "activity_summary")[0]


def test_real_txt_source_details_and_internal_word_keep_manual_and_sibling(tmp_path, monkeypatch):
    # Supply temporary storage for fresh ingest only. Public persistence is exercised below.
    monkeypatch.setattr(sources, "_path", lambda profile, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    raw = TABLE.encode("utf-8-sig")
    contents, messages = sources.ingest_batch(PROFILE, (("source.txt", raw), ("sibling.txt", SAFE.encode())))
    assert len(contents) == 2 and not messages
    item, sibling = contents
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state['source'] = render_source_details(st.session_state['source'], st.session_state['profile'], 'txt-table', field)
""")
    app.session_state["source"], app.session_state["profile"] = item.source, PROFILE
    app.run()
    assert not app.exception
    next(w for w in app.selectbox if w.label == "Source facility").set_value("north")
    next(w for w in app.button if w.label == "Use these source details").click().run()
    assert not app.exception
    item = replace(item, source=app.session_state["source"])
    assert item.source.facility == "north" and item.source.page_texts == (TABLE,)
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    block = structured.native_update((item, sibling), "activity_summary", manual)
    doc = Document(BytesIO(_build_native_docx(draft_for(block, (item, sibling)), template(tmp_path), section_key="activity")))
    output = "\n".join(p.text for p in doc.paragraphs)
    assert MANUAL in output and SAFE in output and FOREIGN not in output and LOCAL not in output
    assert sources.source_bytes(PROFILE, item.source) == raw


def test_public_storage_warm_cache_history_and_word_keep_existing_report(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = TABLE.encode()
    contents, messages = sources.ingest_batch(PROFILE, (("source.txt", raw), ("sibling.txt", SAFE.encode())))
    assert len(contents) == 2 and not messages
    contents = tuple(replace(c, source=correct_source_details(c.source, PROFILE, date(2026, 9, 4), "north"))
                     for c in contents)
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    previous = library.save_snapshot(replace(draft_for(manual, contents), period=ReportPeriod(2026, 8)),
                                     expected_revision=0, entered_editor="Synthetic Editor")
    saved = library.save_snapshot(draft_for(manual, contents), expected_revision=0, entered_editor="Synthetic Editor")
    restored, missing = restore_sources(PROFILE, saved.draft.sources)
    assert not missing and tuple(c.source for c in restored) == saved.draft.sources
    block = structured.native_update(restored, "activity_summary", manual)
    current = replace(saved.draft, blocks=(block,))
    library.save_snapshot(current, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft == current
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, previous.draft.period) == previous
    doc = Document(BytesIO(build_native_docx(current, template(tmp_path), section_key="activity")))
    output = "\n".join(p.text for p in doc.paragraphs)
    assert MANUAL in output and SAFE in output and FOREIGN not in output and LOCAL not in output
    assert sources.source_bytes(PROFILE, restored[0].source) == raw


def test_public_storage_guided_upload_shows_mapping_notice_and_keeps_manual(monkeypatch, tmp_path):
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft, editor
    from app import monthly_report_ai as ai
    app, profile = setup_app(monkeypatch, tmp_path)
    editor(app).set_value(MANUAL).run()
    raw = TABLE.encode()
    original = st.file_uploader
    def uploaded(label, *args, **kwargs):
        native = original(label, *args, **kwargs)
        if label != "Add source files":
            return native
        stream = BytesIO(raw)
        stream.name = "synthetic.txt"
        return [stream]
    monkeypatch.setattr(st, "file_uploader", uploaded)
    monkeypatch.setattr(ai, "request_json", lambda *args: pytest.fail("Blocked TXT reached external reading"))
    app.run()
    assert not app.exception and app.get("file_uploader")
    assert any("site-specific" in warning.value for warning in app.warning)
    assert activity(app).text == MANUAL and editor(app).value == MANUAL
    assert sources.source_bytes(profile, draft(app).sources[0]) == raw
