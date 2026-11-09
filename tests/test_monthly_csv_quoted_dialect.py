"""Quoted CSV dialect fallback: synthetic files and immutable saved-source recovery."""
import codecs
import csv
from dataclasses import asdict, replace
from hashlib import sha256
from io import StringIO
import json

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import restore_sources
from app.monthly_report_work_order_csv import work_order_evidence

HEADERS = ("Work order", "Date", "Status", "Reading", "Note")
ROWS = (
    ("001", "2026-09-12", "Closed", "0", "Inspect pump"),
    ("002", "2026-09-13", "Open", "", 'Not completed; parts pending\nAwait "seal".'),
)


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    result = synthetic_profiles()[0]
    library.save_profile(result, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    return result


def csv_bytes(delimiter=";", *, rows=ROWS, codec="utf-8", bom=b""):
    text = StringIO(newline="")
    writer = csv.writer(text, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return bom + text.getvalue().encode(codec)


def test_exact_reported_semicolon_sniffer_failure_is_five_columns(profile):
    raw = (
        b"Work order;Date;Status;Reading;Note\r\n"
        b"001;2026-09-12;Closed;0;Inspect pump\r\n"
        b'002;2026-09-13;Open;;"Not completed; parts pending"\r\n'
    )
    # Baseline on main: Sniffer raises and its comma default makes one column.
    with pytest.raises(csv.Error):
        csv.Sniffer().sniff(raw.decode()[:8192], delimiters=",;\t|")
    content, _ = sources.ingest(profile, "reported.csv", raw)
    assert content.tables[0].columns == HEADERS
    assert content.tables[0].rows == (
        ("001", "2026-09-12", "Closed", "0", "Inspect pump"),
        ("002", "2026-09-13", "Open", "", "Not completed; parts pending"),
    )
    assert sources.source_bytes(profile, content.source) == raw
    evidence, = work_order_evidence(content, ReportPeriod(2026, 9), profile)
    assert (evidence.total, evidence.completed, evidence.open) == (2, 1, 1)


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
@pytest.mark.parametrize("codec,bom", [
    ("utf-8", b""), ("utf-8", codecs.BOM_UTF8), ("cp1252", b""),
    ("utf-16-le", codecs.BOM_UTF16_LE), ("utf-32-be", codecs.BOM_UTF32_BE),
])
def test_quoted_separator_and_multiline_preserve_five_physical_columns(profile, delimiter, codec, bom):
    rows = (("0001", "2026-09-12", "Closed", "0", f"Part{delimiter} ordered\nCheck next day"),
            ("0002", "2026-09-13", "Open", "", 'Awaiting "seal"'))
    raw = csv_bytes(delimiter, rows=rows, codec=codec, bom=bom)
    content, _ = sources.ingest(profile, "multiline.csv", raw)
    table, = content.tables
    assert table.columns == HEADERS
    assert table.rows == rows
    assert sources.source_bytes(profile, content.source) == raw


@pytest.mark.parametrize("raw,message", [
    (b"Work order,Date;Status\n001,2026-09-12;Open\n", "ambiguous"),
    (b"Work order;Date;Status\n001;2026-09-12;Open\n002;2026-09-13;Closed;extra\n",
     "different column counts"),
    (b'Work order;Date\n001;"unfinished\n', "quoting"),
])
def test_ambiguity_ragged_rows_and_bad_quotes_refuse_explicitly(raw, message):
    with pytest.raises(ValueError, match=message):
        sources._spreadsheet(raw, ".csv")


def test_actual_single_column_without_delimiters_remains_supported():
    raw = b'Note\n"Parts; waiting"\n'
    assert sources._spreadsheet(raw, ".csv")[0].columns == ("Note",)
    assert sources._spreadsheet(raw, ".csv")[0].rows == (("Parts; waiting",),)


def test_ambiguous_batch_failure_preserves_accepted_sibling_and_retries(profile):
    good = csv_bytes()
    bad = b"Work order,Date;Status\n001,2026-09-12;Open\n"
    accepted, messages = sources.ingest_batch(profile, (
        ("good.csv", good), ("ambiguous.csv", bad), ("after.txt", b"Synthetic inspection notes."),
    ))
    assert [item.source.filename for item in accepted] == ["good.csv", "after.txt"]
    assert len(messages) == 1 and "ambiguous" in messages[0]
    assert sources.source_bytes(profile, accepted[0].source) == good
    assert not sources._path(profile, sha256(bad).hexdigest(), ".csv").exists()
    fixed = bad.replace(b"Work order,Date;Status", b"Work order,Date,Status").replace(
        b"001,2026-09-12;Open", b"001,2026-09-12,Open")
    resumed, messages = sources.ingest_batch(profile, (("fixed.csv", fixed),), accepted)
    assert not messages and resumed[:2] == accepted
    assert resumed[-1].tables[0].columns == ("Work order", "Date", "Status")


@pytest.mark.parametrize("budget,limit", [
    ("MAX_TABLE_ROWS", 2), ("MAX_TABLE_CELLS", 9),
])
def test_row_and_cell_budgets_reject_without_one_column_escape(monkeypatch, budget, limit):
    monkeypatch.setattr(sources, budget, limit)
    with pytest.raises(ValueError, match="review budget"):
        sources._spreadsheet(csv_bytes(), ".csv")


def test_column_budget_rejects_csv_without_fallback():
    headers = ";".join(f"Field{n}" for n in range(201))
    raw = (headers + "\n" + ";".join("x" for _ in range(201))).encode()
    with pytest.raises(ValueError, match="review budget"):
        sources._spreadsheet(raw, ".csv")


def _replace_cache_with_legacy_one_column(profile, content, raw):
    # Reproduce the real pre-fix comma fallback; original source is untouched.
    old = sources._table("CSV", csv.reader(StringIO(raw.decode()), csv.excel, strict=True),
                         strict_columns=True)
    source = replace(content.source, page_texts=("\n".join([
        "\t".join(old.columns), *("\t".join(row) for row in old.rows)]),))
    record = {"schema": 1, "client_page_policy": 1, "native_action_policy": 1,
              "vendor_passage_policy": 7, "source": asdict(source),
              "tables": [asdict(old)], "image_items": []}
    cache = sources._path(profile, content.source.sha256, ".json")
    library._atomic_write(cache, library._json(record))
    return cache


def test_legacy_single_column_cache_rebuilds_once_without_rewriting_original(profile, monkeypatch):
    raw = csv_bytes(rows=(ROWS[0], ("002", "2026-09-13", "Open", "", "Waiting; part")))
    original, _ = sources.ingest(profile, "original.csv", raw)
    saved_path = sources._path(profile, original.source.sha256, ".csv")
    old_identity = (saved_path.read_bytes(), saved_path.stat().st_ino, saved_path.stat().st_mtime_ns)
    cache = _replace_cache_with_legacy_one_column(profile, original, raw)
    assert json.loads(cache.read_bytes()).get("csv_dialect_policy") is None
    corrected, _ = sources.ingest(profile, "renamed.csv", raw)
    assert corrected.tables == original.tables
    assert corrected.source.filename == "renamed.csv"
    assert json.loads(cache.read_bytes())["csv_dialect_policy"] == 1
    assert (saved_path.read_bytes(), saved_path.stat().st_ino, saved_path.stat().st_mtime_ns) == old_identity
    fixed_cache = cache.read_bytes()
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Warm CSV cache was reparsed"))
    assert sources.ingest(profile, "again.csv", raw)[0].tables == original.tables
    assert cache.read_bytes() == fixed_cache


def test_pre_fix_five_column_cache_stays_warm_without_dialect_stamp(profile, monkeypatch):
    raw = csv_bytes(rows=(ROWS[0],))
    content, _ = sources.ingest(profile, "original.csv", raw)
    cache = sources._path(profile, content.source.sha256, ".json")
    record = json.loads(cache.read_bytes())
    record.pop("csv_dialect_policy")
    library._atomic_write(cache, library._json(record))
    original_cache = cache.read_bytes()
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Correct cache was reparsed"))
    assert sources.ingest(profile, "renamed.csv", raw)[0].tables == content.tables
    assert cache.read_bytes() == original_cache


def test_saved_source_review_reopens_after_legacy_cache_repair(profile):
    raw = csv_bytes(rows=(ROWS[0], ("002", "2026-09-13", "Open", "", "Waiting; part")))
    content, _ = sources.ingest(profile, "original.csv", raw)
    _replace_cache_with_legacy_one_column(profile, content, raw)
    reviewed = replace(content.source, classification="CMMS export",
                       findings="Synthetic manual correction; retain this note",
                       facility=profile.facilities[0].key)
    period = ReportPeriod(2026, 9)
    draft = replace(synthetic_draft(profile, period), sources=(reviewed,), blocks=(
        ResolvedBlock("activity_summary", "This month", text="Synthetic manual update"),))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    assert saved.revision >= 1
    restored, unavailable = restore_sources(profile, (reviewed,))
    assert not unavailable
    assert restored[0].tables == content.tables
    assert restored[0].source == reviewed
    assert sources.source_bytes(profile, reviewed) == raw
    reopened = library.load_snapshot(profile.contract, profile.key, period)
    assert reopened.draft == draft
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1).draft == draft
