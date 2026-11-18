"""A73 synthetic source-table decisions, privacy and exclusion replay."""
from dataclasses import asdict, replace
import json

from app import monthly_report_library as library
from app.monthly_report_followups import seed_followups
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ReportTable, ResolvedBlock,
    default_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft
from tests.conftest import requires_libreoffice


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)
NOVEMBER = ReportPeriod(2026, 11)
DECEMBER = ReportPeriod(2026, 12)
COLUMNS = ("Proposal ID", "Vendor", "Scope", "Status", "Amount", "Unit Rate", "Total")
ROWS = (
    ("P-1", "Synthetic Controls", "Check actuator", "Proposed", "$12,321.98", "$40", "$12,321.98"),
    ("P-2", "Synthetic Controls", "Check actuator", "Approved", "$2,222", "$20", "$2,222"),
    ("P-3", "Synthetic Airflow", "Replace damper", "Pending", "$3,333", "$30", "$3,333"),
    ("P-4", "Synthetic Airflow", "Replace damper", "Declined", "$4,444", "$40", "$4,444"),
    ("P-5", "Synthetic Controls", "Investigate controls", "Awaiting review", "$5,555", "$50", "$5,555"),
)


def initial_draft():
    section = next(s for s in default_sections() if s.key == "proposals")
    block = ResolvedBlock("proposals", "This month",
                          extra_tables=(ReportTable(COLUMNS, ROWS, reference="synthetic:table"),))
    return ReportDraft(synthetic_profiles()[0], SEPTEMBER, "Synthetic Reviewer", (section,), (block,))


def test_explicit_decisions_duplicate_vendor_scope_and_price_canaries():
    prior = initial_draft()
    before = asdict(prior)
    carried = new_month_draft(prior, OCTOBER)
    assert [item.status for item in carried.follow_ups] == [
        "not_confirmed", "approved", "pending", "declined", "not_confirmed",
    ]
    assert len({item.key for item in carried.follow_ups}) == len(ROWS)
    assert all("Amount:" not in item.text and "Unit Rate:" not in item.text
               and "Total:" not in item.text and "$" not in item.text
               for item in carried.follow_ups)
    assert "Status: Proposed" in carried.follow_ups[0].text
    assert "Status: Awaiting review" in carried.follow_ups[-1].text
    assert asdict(prior) == before


def test_edited_and_excluded_source_row_survives_reimport_and_two_rollovers(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    prior = initial_draft()
    current = new_month_draft(prior, OCTOBER)
    changed = tuple(
        replace(item, text=item.text + "; Review note: retain bracket",
                status="on_hold", evidence_note="Operator confirmed revised status")
        if index == 2 else replace(item, included=False)
        if index == 3 else item
        for index, item in enumerate(current.follow_ups)
    )
    current = replace(current, follow_ups=changed)
    library.save_snapshot(current, expected_revision=0)
    reopened = library.load_snapshot(current.profile.contract, current.profile.key, current.period).draft
    assert reopened.follow_ups == changed
    for month in (NOVEMBER, DECEMBER):
        # A separately supplied copy of the same reviewed source table must not
        # erase the author's correction or resurrect an explicitly left-out row.
        repeated = replace(reopened, blocks=prior.blocks)
        seeded = seed_followups(repeated)
        assert len(seeded) == len(ROWS)
        assert seeded[2].status == "on_hold"
        assert seeded[2].evidence_note == "Operator confirmed revised status"
        assert seeded[3].included is False
        following = new_month_draft(repeated, month)
        assert len(following.follow_ups) == len(ROWS)
        assert [item.included for item in following.follow_ups] == [True, True, True, False, True]
        assert following.follow_ups[2].text == changed[2].text
        assert following.follow_ups[2].status == "on_hold"
        assert asdict(prior.blocks[0]) == asdict(initial_draft().blocks[0])
        library.save_snapshot(following, expected_revision=0)
        reopened = library.load_snapshot(following.profile.contract, following.profile.key, month).draft
        assert reopened.follow_ups == following.follow_ups
        assert library.draft_from_dict(json.loads(json.dumps(asdict(reopened)))) == reopened


def test_excluded_proposal_requires_explicit_reinclude_and_fresh_review():
    from app.monthly_report_followups import confirmation, problems
    current = new_month_draft(initial_draft(), OCTOBER)
    excluded = replace(current.follow_ups[3], included=False)
    current = replace(current, follow_ups=(*current.follow_ups[:3], excluded, *current.follow_ups[4:]))
    following = new_month_draft(replace(current, blocks=initial_draft().blocks), NOVEMBER)
    assert following.follow_ups[3].included is False
    restored = replace(following.follow_ups[3], included=True)
    assert any("Confirm this proposal" in issue for issue in problems(restored, following))
    confirmed = replace(restored, reviewed_fingerprint=confirmation(restored, NOVEMBER))
    assert not problems(confirmed, following)


@requires_libreoffice
def test_proposal_source_replay_word_and_pdf_hide_excluded_row_and_prices(tmp_path, monkeypatch):
    from collections import Counter
    from hashlib import sha256
    from io import BytesIO
    import os
    from pathlib import Path

    import pymupdf as fitz
    from docx import Document
    from app import pdf_converter
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_followups import confirmation, report_text
    prior = initial_draft()
    october = new_month_draft(prior, OCTOBER)
    changed = tuple(
        replace(item, status="on_hold", evidence_note="Revised by reviewer")
        if i == 2 else replace(item, included=False) if i == 3 else item
        for i, item in enumerate(october.follow_ups)
    )
    november = new_month_draft(replace(october, blocks=prior.blocks, follow_ups=changed), NOVEMBER)
    assert len(november.follow_ups) == len(ROWS)
    assert not november.follow_ups[3].included
    included = tuple(item for item in november.follow_ups if item.included)
    reviewed = replace(november, follow_ups=tuple(
        replace(item, reviewed_fingerprint=confirmation(item, NOVEMBER))
        if item.included else item for item in november.follow_ups
    ))
    raw = assemble_docx(reviewed, acknowledged_fingerprint=reviewed.fingerprint)
    expected = Counter(report_text(item) for item in included)
    actual_word = "\n".join(p.text for p in Document(BytesIO(raw)).paragraphs)
    for text, count in expected.items():
        assert actual_word.count(text) == count
    assert "P-4" not in actual_word and "$" not in actual_word
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    word_path = tmp_path / "a73-proposals.docx"
    word_path.write_bytes(raw)
    pdf_bytes = pdf_converter.convert_to_pdf(word_path).read_bytes()
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        actual_pdf = " ".join(" ".join(p.get_text().split()) for p in pdf)
        pages = len(pdf)
    for text, count in expected.items():
        assert actual_pdf.count(" ".join(text.split())) == count
    assert "P-4" not in actual_pdf
    assert not any(canary in actual_pdf for canary in ("12,321.98", "2,222", "3,333", "4,444", "5,555"))
    target = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "a73-proposals"
    target.mkdir(parents=True, exist_ok=True)
    (target / "proposals.docx").write_bytes(raw)
    (target / "proposals.pdf").write_bytes(pdf_bytes)
    (target / "manifest.json").write_text(json.dumps({
        "docx_sha256": sha256(raw).hexdigest(),
        "pdf_sha256": sha256(pdf_bytes).hexdigest(),
        "pdf_pages": pages,
        "included_proposals": len(included),
        "excluded_proposals": 1,
        "price_canaries_found": False,
    }, indent=2))


def test_same_month_docx_table_excludes_plain_rate_total_but_keeps_source():
    from types import SimpleNamespace
    from app.monthly_report_sections import table_without_prices

    columns = ("Proposal ID", "Vendor", "Scope", "Status", "Unit Rate", "Total", "Technical note")
    row = ("P-SYN", "Synthetic Controls", "Replace valve", "Pending", "1250", "9999", "Keep bracket")
    source = SimpleNamespace(section="proposals", table_header_row=0, rows=(columns, row))
    before = source.rows
    table, omitted = table_without_prices(source)
    assert omitted == (4, 5)
    assert table.columns == ("Proposal ID", "Vendor", "Scope", "Status", "Technical note")
    assert table.rows == (("P-SYN", "Synthetic Controls", "Replace valve", "Pending", "Keep bracket"),)
    assert source.rows == before


def test_same_month_native_csv_import_excludes_plain_rate_total(tmp_path, monkeypatch):
    from app.monthly_report_sources import ingest
    from app.monthly_report_structured_uploads import native_update

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = synthetic_profiles()[0]
    columns = ("Facility", "Vendor", "Scope", "Status", "Unit Rate", "Total", "Technical note")
    original = ("Demo North,Synthetic Controls,Replace valve,Pending,1250,9999,Keep bracket\n").encode()
    raw = (",".join(columns) + "\n").encode() + original
    content, _ = ingest(profile, "a73-proposal-prices.csv", raw)
    mapped = native_update((content,), "proposals", table_columns=columns)
    assert len(mapped.rows) == 1
    row, = mapped.rows
    assert row[:4] == ("Demo North", "Synthetic Controls", "Replace valve", "Pending")
    assert row[4:6] == ("", "")
    assert row[-1] == "Keep bracket"
    assert content.tables[0].rows[0][4:6] == ("1250", "9999")


def test_report_projection_excludes_proposal_only_totals_and_preserves_technical():
    from app.monthly_report_content_policy import price_free_table
    section = next(s for s in default_sections() if s.key == "proposals")
    spec = next(b for b in section.blocks if b.key == "proposals")
    columns = ("Scope", "Status", "Unit Rate", "Total", "Total runtime")
    raw = ResolvedBlock("proposals", "This month", extra_tables=(
        ReportTable(columns, (("Replace valve", "Pending", "1250", "9999", "120 hours"),)),
    ))
    revised_spec, revised_block, removed = price_free_table(spec, raw)
    assert revised_spec == spec
    assert removed == ("Unit Rate", "Total")
    clean, = revised_block.extra_tables
    assert clean.columns == ("Scope", "Status", "Total runtime")
    assert clean.rows == (("Replace valve", "Pending", "120 hours"),)
    assert raw.extra_tables[0].rows[0][2:4] == ("1250", "9999")
