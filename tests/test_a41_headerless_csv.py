"""A41: synthetic, position-preserving CSV headerless and dialect canaries.

Never treat the first physical data record as a header or silently accept
unmapped site/date/status evidence. Uses the actual saved-source intake.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from io import StringIO
import codecs
import csv
import json

import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, ResolvedBlock
from app.monthly_report_work_order_csv_review import (
    correct_csv_row, csv_review_record, exclude_csv_row, mapped_columns,
    physical_columns, reimport_csv_review, restore_csv_review, review_csv,
)
from app.monthly_report_work_order_normalized import suggest_mapping, unmapped_cells
from app.monthly_report_work_order_csv import (
    is_work_order_source, requires_work_order_column_mapping, work_order_evidence,
)
from app.monthly_report_structured_uploads import (
    native_update, reader_notices, reader_sources,
)


ROWS = (
    ("0001", "North", "2026-09-03", "Closed", "", "Inspect, verify\nAwait follow-up"),
    ("0002", "South", "2026-09-04", "Open", "0", 'Await "seal"'),
    ("0003", "Foreign", "2026-09-05", "Closed", "", "Other site"),
)
HEADERS = ("Work Order", "Site", "Date", "Status", "Hours", "Notes")


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = ReportProfile(
        "A41 synthetic contract", "a41-two-site", "Synthetic group",
        (Facility("north", "North Campus", ("North",)),
         Facility("south", "South Campus", ("South",))),
        scope_type="multi_site",
    )
    return profile, ReportPeriod(2026, 9)


def _csv(delimiter, *, rows=ROWS, header=False, codec="utf-8", bom=b""):
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\r\n")
    if header:
        writer.writerow(HEADERS)
    writer.writerows(rows)
    return bom + output.getvalue().encode(codec)


@pytest.mark.parametrize("delimiter", (",", ";", "\t"))
@pytest.mark.parametrize("codec,bom", (
    ("utf-8", b""), ("utf-8", codecs.BOM_UTF8),
    ("utf-16-le", codecs.BOM_UTF16_LE), ("utf-32-be", codecs.BOM_UTF32_BE),
))
def test_headerless_data_records_keep_every_source_cell_and_physical_position(
        context, delimiter, codec, bom):
    profile, period = context
    raw = _csv(delimiter, codec=codec, bom=bom)
    content, _ = sources.ingest(profile, "headerless.csv", raw)
    table, = content.tables
    assert table.columns == tuple(f"Column {i}" for i in range(1, 7))
    assert table.rows == ROWS
    assert (len(table.rows), len(table.columns), sum(map(len, table.rows))) == (3, 6, 18)
    assert physical_columns(content) == tuple(
        (index, f"{index + 1} · Column {index + 1}") for index in range(6))
    assert sources.source_bytes(profile, content.source) == raw
    assert content.source.sha256 == sha256(raw).hexdigest()
    assert requires_work_order_column_mapping(content)
    assert not is_work_order_source(content)
    assert work_order_evidence(content, period, profile) == ()
    assert "headerless" in reader_notices((content,), "activity_summary")[0]
    assert not reader_sources((content,), "activity_summary")
    manual_activity = ResolvedBlock("activity_summary", "This month",
                                    text="Previously accepted technician account.")
    assert native_update((content,), "activity_summary",
                         existing=manual_activity).text == manual_activity.text

    # The source is reviewable, not automatically declared a work-order match.
    initial = review_csv(content, profile, period)
    assert not initial.ready_for_inclusion
    assert initial.workorders.kind == "unresolved"
    mapping = mapped_columns(table.columns, {
        "work_order": 0, "site": 1, "work_date": 2, "status": 3,
    }, suggested=suggest_mapping(table.columns))
    reviewed = review_csv(content, profile, period, mapping=mapping)
    assert len(reviewed.workorders.rows) == 3
    assert reviewed.workorders.counts() == {
        "source_rows": 3, "included": 2, "needs_review": 1,
        "excluded": 0, "unmapped_rows": 0}
    assert reviewed.workorders.rows[2].site == ""
    assert "site needs review" in reviewed.workorders.rows[2].issues
    assert unmapped_cells(reviewed.workorders, reviewed.workorders.rows[0].key) == (
        (4, "Column 5", ""), (5, "Column 6", ROWS[0][5]))
    safe = exclude_csv_row(reviewed, reviewed.workorders.rows[2].key,
                           expected_revision=reviewed.revision, excluded=True)
    assert safe.ready_for_inclusion
    assert [row.work_order for row in safe.workorders.rows if not row.excluded] == ["0001", "0002"]


def test_single_headerless_record_is_not_silently_eaten(context):
    profile, period = context
    original = _csv(";", rows=ROWS[:1])
    content, _ = sources.ingest(profile, "only.csv", original)
    assert content.tables[0].rows == ROWS[:1]
    assert content.tables[0].columns == tuple(f"Column {n}" for n in range(1, 7))
    assert not review_csv(content, profile, period).ready_for_inclusion


def test_known_header_and_duplicate_physical_headings_are_not_reshaped(context):
    profile, period = context
    raw = _csv(",", header=True)
    content, _ = sources.ingest(profile, "normal.csv", raw)
    assert content.tables[0].columns == HEADERS
    assert content.tables[0].rows == ROWS
    evidence, = work_order_evidence(content, period, profile)
    assert (evidence.total, evidence.completed, evidence.open) == (2, 1, 1)
    assert any("did not match" in note for note in evidence.notices)
    data = (b"Work Order,Facility,Date,Status,Status\n"
            b"001,North,2026-09-03,Closed,Open\n")
    repeated, _ = sources.ingest(profile, "repeated.csv", data)
    assert repeated.tables[0].columns == (
        "Work Order", "Facility", "Date", "Status", "Status (2)")
    assert repeated.tables[0].rows == (("001", "North", "2026-09-03", "Closed", "Open"),)
    assert physical_columns(repeated)[-2:] == (
        (3, "4 · Status"), (4, "5 · Status (2)"))
    suggestion = suggest_mapping(repeated.tables[0].columns)
    assert suggestion.status is None and suggestion.ambiguous == ("status",)
    needs_review = review_csv(repeated, profile, period)
    assert "Ambiguous status column" in needs_review.questions
    assert not needs_review.ready_for_inclusion
    manual = mapped_columns(repeated.tables[0].columns, {
        "work_order": 0, "site": 1, "work_date": 2, "status": 4})
    review = review_csv(repeated, profile, period, mapping=manual)
    assert review.workorders.rows[0].status == "Open"
    assert unmapped_cells(review.workorders, review.workorders.rows[0].key) == (
        (3, "Status", "Closed"),)
    assert sources.source_bytes(profile, repeated.source) == data
    assert requires_work_order_column_mapping(repeated)
    assert not is_work_order_source(repeated)
    assert work_order_evidence(repeated, period, profile) == ()
    assert "duplicate physical" in reader_notices(
        (repeated,), "activity_summary")[0]


def test_legacy_headerless_cache_rebuilds_once_but_preserves_manual_review(context, monkeypatch, tmp_path):
    profile, period = context
    raw = _csv(";", rows=ROWS[:2])
    current, _ = sources.ingest(profile, "initial.csv", raw)
    original = sources._path(profile, current.source.sha256, ".csv")
    before = (original.read_bytes(), original.stat().st_ino, original.stat().st_mtime_ns)
    legacy = sources._table("CSV", csv.reader(
        StringIO(raw.decode("utf-8"), newline=""), delimiter=";", strict=True),
        strict_columns=True)
    assert len(legacy.rows) == 1  # baseline: physical first source row lost
    cached_source = replace(current.source, page_texts=("\n".join(
        ("\t".join(legacy.columns), *("\t".join(row) for row in legacy.rows))),))
    cache = sources._path(profile, current.source.sha256, ".json")
    record = {"schema": 1, "client_page_policy": 1, "native_action_policy": 1,
              "vendor_passage_policy": 7, "csv_dialect_policy": 1,
              "source": asdict(cached_source), "tables": [asdict(legacy)],
              "image_items": []}
    library._atomic_write(cache, library._json(record))
    corrected, _ = sources.ingest(profile, "renamed.csv", raw)
    assert corrected.tables == current.tables
    assert json.loads(cache.read_bytes())["csv_headerless_policy"] == 1
    assert (original.read_bytes(), original.stat().st_ino, original.stat().st_mtime_ns) == before

    mapping = mapped_columns(corrected.tables[0].columns,
                             {"work_order": 0, "site": 1, "work_date": 2, "status": 3})
    candidate = review_csv(corrected, profile, period, mapping=mapping)
    changed = correct_csv_row(candidate, candidate.workorders.rows[0].key,
                              {"status": "Open"}, expected_revision=candidate.revision)
    savefile = tmp_path / "manual-review.json"
    savefile.write_text(json.dumps(csv_review_record(changed)))
    reopened = restore_csv_review(json.loads(savefile.read_text()))
    same = review_csv(corrected, profile, period, mapping=mapping)
    assert reimport_csv_review(reopened, same) == changed
    assert reopened.workorders.rows[0].origin.cells == ROWS[0]

    warm_bytes = cache.read_bytes()
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Warm cache reparsed"))
    assert sources.ingest(profile, "again.csv", raw)[0].tables == current.tables
    assert cache.read_bytes() == warm_bytes


def test_old_known_good_multi_column_cache_stays_warm(context, monkeypatch):
    profile, _ = context
    raw = _csv(",", header=True)
    content, _ = sources.ingest(profile, "known.csv", raw)
    cache = sources._path(profile, content.source.sha256, ".json")
    record = json.loads(cache.read_bytes())
    record.pop("csv_headerless_policy")
    library._atomic_write(cache, library._json(record))
    before = cache.read_bytes()
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Valid cache reparsed"))
    assert sources.ingest(profile, "same.csv", raw)[0].tables == content.tables
    assert cache.read_bytes() == before


def test_bad_input_is_per_file_and_does_not_remove_accepted_siblings(context):
    profile, _ = context
    good = _csv("\t", rows=ROWS[:2])
    malformed = b'Work Order;Site;Status\n0001;North;"unterminated\n'
    accepted, notices = sources.ingest_batch(profile, (
        ("valid.csv", good), ("broken.csv", malformed), ("after.txt", b"Inspected synthetic pump."),
    ))
    assert [item.source.filename for item in accepted] == ["valid.csv", "after.txt"]
    assert len(notices) == 1 and "broken.csv" in notices[0]
    assert sources.source_bytes(profile, accepted[0].source) == good
    assert not sources._path(profile, sha256(malformed).hexdigest(), ".csv").exists()
    assert not sources._path(profile, sha256(malformed).hexdigest(), ".json").exists()
    with pytest.raises(ValueError, match="empty"):
        sources.ingest(profile, "empty.csv", b"")
    with pytest.raises(ValueError, match="Unsupported"):
        sources.ingest(profile, "file.exe", b"not a CSV")



@pytest.mark.parametrize("columns,row", (
    ("Work Order,Site,Date,Status,Status",
     "0005,North,2026-09-07,Open,Closed"),
    ("Work Order,Work Order,Site,Date,Status",
     "0005,ALTERNATE,North,2026-09-07,Closed"),
    ("Work Order,Site,Date,Status,Facility",
     "0005,North,2026-09-07,Closed,Foreign"),
    ("Work Order,Facility,Facility,Date,Status",
     "0005,North,Foreign,2026-09-07,Closed"),
))
def test_ambiguous_identity_and_site_headings_require_review_not_auto_count(
        context, columns, row):
    profile, period = context
    raw = (columns + "\n" + row + "\n").encode()
    content, _ = sources.ingest(profile, "conflicting.csv", raw)
    if columns == "Work Order,Site,Date,Status,Facility":
        # Two different aliases may indicate two sites, even without a
        # literal repeated heading. Both are physical site candidates.
        assert content.tables[0].rows[0][1] == "North"
    assert requires_work_order_column_mapping(content)
    initial = review_csv(content, profile, period)
    assert initial.workorders.original_rows == content.tables[0].rows
    assert any(question.startswith("Ambiguous ") for question in initial.questions)
    assert not initial.ready_for_inclusion
    assert not is_work_order_source(content)
    assert not work_order_evidence(content, period, profile)
    assert "duplicate physical" in reader_notices(
        (content,), "activity_summary")[0]
    manual = ResolvedBlock("activity_summary", "This month",
                           text="Accepted human-authored activity.")
    result = native_update((content,), "activity_summary", existing=manual)
    assert result.text == manual.text and result.references == manual.references
    assert sources.source_bytes(profile, content.source) == raw


def test_two_competing_work_and_status_labels_do_not_become_auto_activity(context):
    profile, _ = context
    raw = (b"Work,Work,Status,Status,Date\n"
           b"Inspected fan,Scheduled repair,Closed,Pending,2026-09-03\n")
    content, _ = sources.ingest(profile, "vendor.csv", raw)
    assert content.tables[0].columns == (
        "Work", "Work (2)", "Status", "Status (2)", "Date")
    notice, = reader_notices((content,), "activity_summary")
    assert "ambiguous Activity CSV columns" in notice
    assert "work" in notice and "status" in notice
    assert not reader_sources((content,), "activity_summary")
    block = native_update((content,), "activity_summary")
    assert not block.text and not block.references
    assert sources.source_bytes(profile, content.source) == raw


def test_ambiguous_file_keeps_unrelated_source_eligible(context):
    profile, _ = context
    ambiguous, _ = sources.ingest(profile, "duplicated.csv",
        b"Work Order,Date,Status,Status\n0004,2026-09-03,Closed,Open\n")
    sibling, _ = sources.ingest(profile, "sibling.txt",
        b"Inspected synthetic north campus fan, checked belts and filters.")
    assert reader_sources((ambiguous, sibling), "activity_summary") == (sibling,)
    assert sources.source_bytes(profile, sibling.source) == (
        b"Inspected synthetic north campus fan, checked belts and filters.")



def test_unrecognized_first_status_is_data_and_needs_manual_review(context):
    profile, period = context
    rows = (
        ("WO-0009", "North", "2026-09-12", "Deferred", "", "Awaiting parts"),
        ("0002", "South", "2026-09-13", "Closed", "", "Inspected pump"),
    )
    raw = _csv(";", rows=rows)
    content, _ = sources.ingest(profile, "deferred.csv", raw)
    table, = content.tables
    assert table.rows == rows
    assert table.columns == tuple(f"Column {n}" for n in range(1, 7))
    manual = mapped_columns(table.columns, {
        "work_order": 0, "site": 1, "work_date": 2, "status": 3,
    })
    review = review_csv(content, profile, period, mapping=manual)
    assert review.workorders.rows[0].work_order == "WO-0009"
    assert review.workorders.rows[0].origin.cells[3] == "Deferred"
    assert "status needs review" in review.workorders.rows[0].issues
    assert review.workorders.rows[1].status == "Completed"
    assert review.workorders.counts()["unmapped_rows"] == 0
    assert not review.ready_for_inclusion
    assert sources.source_bytes(profile, content.source) == raw
