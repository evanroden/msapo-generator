"""Explicit Unicode signatures must never become cells full of NUL characters."""
import codecs
import csv
import hashlib
import json
from dataclasses import asdict, replace
from io import StringIO

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import restore_sources
from app.monthly_report_work_order_csv import is_work_order_source, work_order_evidence


ENCODINGS = (
    ("utf-16-le", codecs.BOM_UTF16_LE),
    ("utf-16-be", codecs.BOM_UTF16_BE),
    ("utf-32-le", codecs.BOM_UTF32_LE),
    ("utf-32-be", codecs.BOM_UTF32_BE),
)
HEADINGS = ("Work order", "Date", "Status", "Reading", "Note")
ROWS = (("001", "2026-09-12", "Closed", "0", "Inspect café 東京 𐐀"),
        ("002", "2026-09-13", "Open", "", "Not completed — parts pending"))


def encoded_csv(codec, bom, *, delimiter=",", rows=ROWS, headings=HEADINGS):
    stream = StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(headings)
    writer.writerows(rows)
    return bom + stream.getvalue().encode(codec)


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    return profile


@pytest.mark.parametrize("codec,bom", ENCODINGS)
@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_signed_unicode_columns_and_cells_remain_exact(profile, codec, bom, delimiter):
    raw = encoded_csv(codec, bom, delimiter=delimiter)
    content, attachments = sources.ingest(profile, "work-orders.csv", raw)
    assert not attachments
    assert content.tables[0].columns == HEADINGS
    assert content.tables[0].rows == ROWS
    assert "\x00" not in content.source.page_texts[0]
    assert content.source.sha256 == hashlib.sha256(raw).hexdigest()
    assert sources.source_bytes(profile, content.source) == raw
    evidence, = work_order_evidence(content, ReportPeriod(2026, 9), profile)
    assert (evidence.total, evidence.completed, evidence.open) == (2, 1, 1)
    assert evidence.rows == (("001", "2026-09-12", "Completed"),
                             ("002", "2026-09-13", "Open"))
    assert evidence.needs_site_confirmation  # Encoding does not establish a site.


@pytest.mark.parametrize("codec,bom", ENCODINGS)
def test_unicode_quoted_multiline_and_empty_cells_are_not_retyped(profile, codec, bom):
    rows = (("0007", "2026-09-12", "Open", "0", 'Inspected, not repaired.\r\nAwaiting "seal".'),
            ("0008", "", "", "", ""))
    content, _ = sources.ingest(profile, "quoted.csv", encoded_csv(codec, bom, rows=rows))
    assert content.tables[0].rows == rows


@pytest.mark.parametrize("codec,bom", [("utf-8", b""), ("utf-8", codecs.BOM_UTF8), ("cp1252", b"")])
def test_existing_unmarked_and_utf8_bom_encodings_remain_unchanged(profile, codec, bom):
    rows = (("001", "2026-09-12", "Closed", "0", "Café – seal"),)
    content, _ = sources.ingest(profile, "existing.csv", encoded_csv(codec, bom, rows=rows))
    assert content.tables[0].columns == HEADINGS
    assert content.tables[0].rows == rows


def _legacy_cached_content(profile, codec, bom):
    # Actual old decoder input with no final newline: old code accepts these
    # fixed-width rows as CP1252 and stores their NUL-containing cells.
    text = "Work order,Date,Status,Reading,Note\n001,2026-09-12,Closed,0,Inspected pump"
    raw = bom + text.encode(codec)
    content, _ = sources.ingest(profile, "legacy.csv", raw)
    decoded = raw.decode("cp1252")
    table = sources._table("CSV", csv.reader(StringIO(decoded), strict=True), strict_columns=True)
    source = replace(content.source, page_texts=("\n".join([
        "\t".join(table.columns), *("\t".join(row) for row in table.rows)]),))
    legacy = replace(content, source=source, tables=(table,))
    data = {"schema": 1, "client_page_policy": 1, "native_action_policy": 1,
            "vendor_passage_policy": 7, **asdict(legacy)}
    cache = sources._path(profile, source.sha256, ".json")
    library._atomic_write(cache, library._json(data))
    return raw, legacy, cache


@pytest.mark.parametrize("codec,bom", ENCODINGS)
def test_legacy_unicode_cache_rebuilds_once_without_rewriting_original(profile, monkeypatch, codec, bom):
    raw, legacy, cache = _legacy_cached_content(profile, codec, bom)
    path = sources._path(profile, legacy.source.sha256, ".csv")
    before = (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
    fixed, _ = sources.ingest(profile, "legacy.csv", raw)
    assert fixed.tables[0].columns == HEADINGS
    assert fixed.tables[0].rows == (("001", "2026-09-12", "Closed", "0", "Inspected pump"),)
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before
    assert json.loads(cache.read_bytes())["csv_unicode_policy"] == 1
    updated = cache.read_bytes()
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Warm cache was reparsed"))
    reopened, _ = sources.ingest(profile, "renamed.csv", raw)
    assert reopened.tables == fixed.tables and reopened.source.filename == "renamed.csv"
    assert cache.read_bytes() == updated


def test_unmarked_legacy_cache_stays_warm_without_encoding_stamp(profile, monkeypatch):
    raw = b"Work order,Date,Status\n001,2026-09-12,Closed"
    content, _ = sources.ingest(profile, "legacy-utf8.csv", raw)
    cache = sources._path(profile, content.source.sha256, ".json")
    value = json.loads(cache.read_bytes()); value.pop("csv_unicode_policy", None)
    library._atomic_write(cache, library._json(value))
    before = cache.read_bytes()
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Unaffected cache reparsed"))
    assert sources.ingest(profile, "legacy-utf8.csv", raw)[0].tables == content.tables
    assert cache.read_bytes() == before


@pytest.mark.parametrize("raw", [
    codecs.BOM_UTF16_LE + b"\x00\xd8",  # incomplete surrogate
    codecs.BOM_UTF16_BE + b"\xd8\x00",
    codecs.BOM_UTF16_LE + b"A",          # incomplete code unit
    codecs.BOM_UTF32_LE + b"\x00\x00\x11\x00",  # above Unicode range
    codecs.BOM_UTF32_BE + b"\x00\x11\x00\x00",
    codecs.BOM_UTF32_BE + b"\x00\x00\x00",
])
def test_invalid_signed_unicode_rejects_one_file_and_preserves_siblings(profile, raw):
    accepted, notices = sources.ingest_batch(profile, (
        ("before.txt", b"Inspected first synthetic pump."),
        ("invalid.csv", raw),
        ("after.txt", b"Inspected second synthetic pump."),
    ))
    assert [c.source.filename for c in accepted] == ["before.txt", "after.txt"]
    assert len(notices) == 1 and "CSV Unicode encoding could not be read" in notices[0]
    assert not sources._path(profile, hashlib.sha256(raw).hexdigest(), ".csv").exists()
    assert not sources._path(profile, hashlib.sha256(raw).hexdigest(), ".json").exists()
    fixed = encoded_csv("utf-16-le", codecs.BOM_UTF16_LE)
    retried, messages = sources.ingest_batch(profile, (("invalid.csv", fixed),), accepted)
    assert not messages and retried[:2] == accepted
    assert retried[-1].tables[0].rows == ROWS


@pytest.mark.parametrize("codec,bom", ENCODINGS)
def test_unicode_csv_does_not_relax_column_or_row_budgets(codec, bom, monkeypatch):
    raw = bom + "Work order,Date\n001,2026-09-12,extra".encode(codec)
    with pytest.raises(ValueError, match="different column counts"):
        sources._spreadsheet(raw, ".csv")
    monkeypatch.setattr(sources, "MAX_TABLE_ROWS", 2)
    with pytest.raises(ValueError, match="review budget"):
        sources._spreadsheet(encoded_csv(codec, bom), ".csv")


def test_reopen_retains_reviewed_source_manual_text_and_immutable_history(profile):
    raw, legacy, cache = _legacy_cached_content(profile, "utf-16-le", codecs.BOM_UTF16_LE)
    reviewed = replace(legacy.source, classification="CMMS export", vendor="Reviewed vendor",
                       service_date="2026-09-12", facility=profile.facilities[0].key,
                       findings="User correction; do not replace", actions="")
    period = ReportPeriod(2026, 9)
    draft = replace(synthetic_draft(profile, period), sources=(reviewed,), blocks=(
        ResolvedBlock("activity_summary", "This month", text="User-authored wording."),))
    first = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    blank = replace(draft, blocks=(replace(draft.blocks[0], text=""),))
    library.save_snapshot(blank, expected_revision=first.revision, entered_editor="Synthetic Editor")
    saved = library.load_snapshot(profile.contract, profile.key, period)
    recovered, unavailable = restore_sources(profile, saved.draft.sources)
    assert not unavailable and recovered[0].source == reviewed
    assert recovered[0].tables[0].columns == HEADINGS
    assert recovered[0].tables[0].rows[0][0] == "001"
    assert saved.draft == blank
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1).draft == draft
    assert library.load_snapshot(profile.contract, profile.key, period).draft == blank
    assert sources.source_bytes(profile, reviewed) == raw
    assert is_work_order_source(recovered[0])


@pytest.mark.parametrize("codec,bom", ENCODINGS)
def test_header_only_unicode_file_retains_schema_without_inventing_rows(profile, codec, bom):
    content, _ = sources.ingest(profile, "headers.csv", encoded_csv(codec, bom, rows=()))
    assert content.tables[0].columns == HEADINGS and content.tables[0].rows == ()
    assert not work_order_evidence(content, ReportPeriod(2026, 9), profile)


def test_changed_original_still_fails_restore_even_with_good_unicode_cache(profile):
    raw = encoded_csv("utf-16-le", codecs.BOM_UTF16_LE)
    content, _ = sources.ingest(profile, "work-orders.csv", raw)
    path = sources._path(profile, content.source.sha256, ".csv")
    cache = sources._path(profile, content.source.sha256, ".json")
    cache_before = cache.read_bytes()
    path.unlink()  # Change only the test profile link, never the pooled original.
    path.write_bytes(b"changed source")
    recovered, unavailable = restore_sources(profile, (content.source,))
    assert not recovered and unavailable == (content.source,)
    assert cache.read_bytes() == cache_before
    assert path.read_bytes() == b"changed source"


def test_later_programming_error_is_not_mislabeled_as_csv_encoding(profile, monkeypatch):
    def fail(*a, **k):
        raise TypeError("Synthetic downstream programming error")
    monkeypatch.setattr(sources, "suggest_facts", fail)
    with pytest.raises(TypeError, match="downstream programming error"):
        sources.ingest(profile, "work-orders.csv", encoded_csv("utf-16-le", codecs.BOM_UTF16_LE))


@pytest.mark.parametrize("manual", ["Human-authored monthly update.", ""])
def test_guided_unicode_upload_and_fresh_reopen_preserve_human_edits(monkeypatch, tmp_path, manual):
    import streamlit as st
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_activity_intake_commit import APP, activity, draft, editor, setup_app
    from app import monthly_report_active_work as active_work
    from test_monthly_report_activity_intake_commit import TOKEN

    app, profile = setup_app(monkeypatch, tmp_path)
    editor(app).set_value(manual).run()
    assert not app.exception
    raw = encoded_csv("utf-16-le", codecs.BOM_UTF16_LE,
                      rows=(("001", "2026-10-12", "Closed", "0", "Inspect café"),))
    original = st.file_uploader
    def upload(label, *a, **k):
        if label == "Add source files":
            stream = BytesIO(raw); stream.name = "unicode-work-orders.csv"
            return [stream]
        return original(label, *a, **k)
    monkeypatch.setattr(st, "file_uploader", upload)
    app.run()
    assert not app.exception
    assert activity(app).text == manual
    batches = [value for key, value in app.session_state.filtered_state.items()
               if key.endswith("_evidence") and isinstance(value, tuple)
               and value and hasattr(value[0], "source")]
    assert batches, "The Unicode CSV must reach source review, not an upload rejection."
    contents = batches[0]
    assert contents[0].tables[0].columns == HEADINGS
    assert contents[0].tables[0].rows[0][0] == "001"
    assert draft(app).sources and sources.source_bytes(profile, draft(app).sources[0]) == raw
    journal = active_work.load(TOKEN, profile.contract, profile.key, ReportPeriod(2026, 10))
    assert journal and next(b.text for b in journal.draft.blocks if b.key == "activity_summary") == manual
    monkeypatch.setattr(st, "file_uploader", original)
    reopened = AppTest.from_string(APP, default_timeout=45).run()
    assert not reopened.exception and activity(reopened).text == manual
    resumed_batches = [value for key, value in reopened.session_state.filtered_state.items()
                       if key.endswith("_evidence") and isinstance(value, tuple)
                       and value and hasattr(value[0], "source")]
    assert resumed_batches, "Saved Unicode source review must be available after reopening."
    reopened_contents = resumed_batches[0]
    assert reopened_contents[0].tables == contents[0].tables
    assert draft(reopened).sources == draft(app).sources
