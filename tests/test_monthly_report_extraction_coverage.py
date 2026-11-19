"""Synthetic A11 ledger controls; manifest is independent of runtime predictions."""
from dataclasses import asdict, replace
from hashlib import sha256
from random import Random

import pytest

from app.monthly_report_extraction_coverage import (
    all_sources_summary, exact_manifest_scores, exclude_from_coverage, source_coverage,
)
from app.monthly_report_model import (BlockSpec, EvidenceFact, ReportDraft, ReportPeriod,
                                      ReportSource, ResolvedBlock, SectionSpec, synthetic_profiles)
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_source_scope import contribution_receipt
from app.monthly_report_library import draft_from_dict


def fixture(*, pages=("Synthetic completed valve inspection.",), suffix=".txt",
            notices=(), vision=(), tables=(), facts=()):
    profile = synthetic_profiles()[0]
    raw_digest = sha256(repr((pages, suffix, notices, vision, tables, facts)).encode()).hexdigest()
    source = ReportSource(raw_digest, "synthetic-source" + suffix, raw_digest, suffix,
                          page_texts=tuple(pages), notices=tuple(notices),
                          needs_vision=tuple(vision), facts=tuple(facts))
    block = ResolvedBlock("activity_summary", "This month")
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic",
        (SectionSpec("activity", "2", "Monthly Activity",
                     (BlockSpec("activity_summary", "rich_text"),)),),
        (block,), sources=(source,), synthetic=True)
    return draft, SourceContent(source, tuple(tables))


def test_unaccepted_file_never_implies_everything_imported_and_cold_reload():
    draft, content = fixture(pages=("Useful technical note.", "Second technical item."))
    ledger = source_coverage(draft, content.source, content)
    assert ledger.pages == 2 and ledger.needs_review == 2
    assert all(item.state == "review" for item in ledger.items)
    item = ledger.items[0]
    updated = exclude_from_coverage(draft, item, "Not needed in this reporting month.")
    restored = draft_from_dict(asdict(updated))
    after = source_coverage(restored, restored.sources[0], content)
    assert after.items[0].state == "excluded" and after.items[1].state == "review"
    assert all_sources_summary((after,))["issues"] == 1
    assert source_coverage(draft, content.source, content).items[0].state == "review"
    assert updated.sources == draft.sources and updated.blocks == draft.blocks


def test_exact_accepted_text_proof_but_not_other_page():
    draft, content = fixture(pages=("Exact synthetic sentence.", "Unimported extra."))
    source = content.source
    from app.monthly_report_sources import source_reference
    reference = source_reference(source, 1)
    old = draft.blocks[0]
    receipt = contribution_receipt(reference, draft.profile, draft.period,
                                    old.key, text=source.page_texts[0],
                                    source=source, prior_block=old)
    block = replace(old, text=source.page_texts[0], references=(reference, receipt))
    ready = replace(draft, blocks=(block,))
    rows = source_coverage(ready, source, content).items
    assert rows[0].state == "applied" and rows[0].destination == "activity_summary"
    assert rows[1].state == "review"
    manifest = ({"source_id": source.id, "item_id": rows[0].item_id,
                 "digest": rows[0].digest, "destination": "activity_summary"},
                {"source_id": source.id, "item_id": rows[1].item_id,
                 "digest": rows[1].digest, "destination": "activity_summary"})
    scored = exact_manifest_scores((source_coverage(ready, source, content),), manifest)
    assert scored["recall_by_destination"]["activity_summary"] == 0.5
    assert scored["exact_supported_precision"] == 1.0


@pytest.mark.parametrize("notices", [
    ("Item 3: unsupported drawing retains its original.",),
    ("Parser item limit reached; remaining native objects are uninspected.",),
    ("AI reader interrupted before completing document.",),
])
def test_parser_limits_and_interruption_are_blocked_not_silent(notices):
    draft, content = fixture(notices=notices)
    ledger = source_coverage(draft, content.source, content)
    assert any(row.kind == "notice" and row.state == "blocked" for row in ledger.items)
    assert ledger.limited
    assert ledger.ai_attempts is None and ledger.ai_pages_covered is None


def test_scanned_only_page_is_not_blank_or_successfully_imported():
    draft, content = fixture(pages=("",), suffix=".pdf", vision=(1,))
    ledger = source_coverage(draft, content.source, content)
    assert ledger.unread_pages == 1
    assert ledger.items[0].kind == "visual"
    assert ledger.items[0].state == "blocked"
    with pytest.raises(ValueError, match="Only reviewable"):
        exclude_from_coverage(draft, ledger.items[0], "It is irrelevant.")


def test_table_rows_are_not_erased_by_page_level_accepted_totals():
    table = SourceTable("Sheet 1", ("ID", "Status"),
                        (("A01", "Completed"), ("A02", "Scheduled")))
    draft, content = fixture(pages=("ID\tStatus\nA01\tCompleted\nA02\tScheduled",),
                             suffix=".csv", tables=(table,))
    ledger = source_coverage(draft, content.source, content)
    assert ledger.rows == 2 and ledger.tables == 1
    assert len([i for i in ledger.items if i.kind == "row"]) == 2
    assert ledger.needs_review >= 3
    missing = source_coverage(draft, content.source)
    assert missing.limited and any(i.item_id == "tables:unavailable" for i in missing.items)


def test_explicit_exclusions_require_current_source_period_and_element():
    draft, content = fixture(pages=("Synthetic irrelevant passage.",))
    item = source_coverage(draft, content.source, content).items[0]
    with pytest.raises(ValueError, match="reason"):
        exclude_from_coverage(draft, item, "none")
    result = exclude_from_coverage(draft, item, "Irrelevant to this month's technical report.")
    assert source_coverage(result, result.sources[0], content).items[0].state == "excluded"
    assert source_coverage(replace(result, period=ReportPeriod(2026, 10)),
                           result.sources[0], content).items[0].state == "review"
    changed = replace(result.sources[0], page_texts=("Different content.",))
    assert source_coverage(replace(result, sources=(changed,)), changed,
                           replace(content, source=changed)).items[0].state == "review"
    assert source_coverage(result, result.sources[0], content).items[0].reason.startswith("Irrelevant")


def test_all_observed_elements_have_one_state_randomized():
    rnd = Random(17)
    for _ in range(60):
        pages = tuple(rnd.choice(("Text.", "", "Price-only quote.", "Another fact."))
                      for _ in range(rnd.randint(1, 8)))
        vision = tuple(n for n, page in enumerate(pages, 1) if not page and rnd.choice((True, False)))
        draft, content = fixture(pages=pages, vision=vision)
        ledger = source_coverage(draft, content.source, content)
        assert len([x for x in ledger.items if x.kind in ("text", "visual")]) >= len(pages)
        assert len({x.item_id for x in ledger.items}) == len(ledger.items)
        assert all(x.state in {"applied", "review", "excluded", "blocked"} for x in ledger.items)
        assert all_sources_summary((ledger,))["files"] == 1


def test_known_reader_descriptions_are_explicitly_excluded_and_do_not_mask_unknown():
    draft, content = fixture(notices=("DOCX selections are extracted items, not Word page numbers.",
                                    "Unsupported native diagram requires repair."))
    items = source_coverage(draft, content.source, content).items
    assert [row.state for row in items[-2:]] == ["excluded", "blocked"]


def test_exclusion_never_changes_preflight_or_generation_gate():
    from app.monthly_report_checks import preflight
    draft, content = fixture(pages=("Source with unresolved site.",))
    baseline = preflight(draft)
    item = source_coverage(draft, content.source, content).items[0]
    updated = exclude_from_coverage(draft, item, "Only a reference for unrelated work.")
    assert [(c.code, c.blocking) for c in preflight(updated)] == [
        (c.code, c.blocking) for c in baseline]


def test_native_explicit_page_exclusion_is_preserved_in_coverage():
    from app.monthly_report_content_policy import page_fingerprint
    draft, content = fixture(pages=("Technical source page.",))
    source = content.source
    source = replace(source, client_page_exclusions=((1, page_fingerprint(source, 1)),))
    updated = replace(draft, sources=(source,))
    ledger = source_coverage(updated, source, replace(content, source=source))
    assert ledger.items[0].state == "excluded"
    assert "Explicitly omitted" in ledger.items[0].reason


def test_reviewable_table_row_exclusion_persists_and_rejects_stale_content():
    row = SourceTable("Sheet 1", ("Kind", "Detail"), (("Other", "Irrelevant note"),))
    draft, content = fixture(pages=("Kind\\tDetail\\nOther\\tIrrelevant note",), suffix=".csv",
                             tables=(row,))
    row_item = next(item for item in source_coverage(draft, content.source, content).items
                    if item.kind == "row")
    result = exclude_from_coverage(draft, row_item, "Irrelevant synthetic test row.", content=content)
    assert next(item for item in source_coverage(result, result.sources[0], content).items
                if item.kind == "row").state == "excluded"
    changed = replace(content, tables=(SourceTable("Sheet 1", row.columns,
                                                   (("Other", "Different note"),)),))
    with pytest.raises(ValueError, match="changed"):
        exclude_from_coverage(draft, row_item, "Irrelevant synthetic test row.", content=changed)


def test_maximum_legal_reason_roundtrips_without_corrupting_snapshot():
    draft, content = fixture(pages=("Synthetic content awaiting review.",))
    item = source_coverage(draft, content.source, content).items[0]
    reason = "x" * 300
    updated = exclude_from_coverage(draft, item, reason)
    restored = draft_from_dict(asdict(updated))
    assert len(updated.source_coverage_receipts[0]) > 500
    assert source_coverage(restored, restored.sources[0], content).items[0].reason == reason


def test_large_spreadsheet_hashes_source_once(monkeypatch):
    from app.monthly_report_model import ReportSource
    rows = tuple((str(n), "synthetic") for n in range(3000))
    table = SourceTable("Synthetic", ("ID", "Detail"), rows)
    page = "ID\\tDetail\\n" + "\\n".join("\\t".join(row) for row in rows)
    draft, content = fixture(pages=(page,), suffix=".csv", tables=(table,))
    original = ReportSource.fingerprint.fget
    calls = []
    def counted(source):
        calls.append(1)
        return original(source)
    monkeypatch.setattr(ReportSource, "fingerprint", property(counted))
    ledger = source_coverage(draft, draft.sources[0], content)
    assert ledger.rows == 3000
    assert len(calls) == 1


def test_reviewed_image_with_context_marker_is_not_falsely_unread(monkeypatch):
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_sources import source_reference
    from app import monthly_report_asset_review
    draft, content = fixture(pages=("",), suffix=".pdf", vision=(1,))
    source = replace(content.source, selected_pages=(1,))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    block = replace(draft.blocks[0], asset_hashes=("synthetic.png",))
    monkeypatch.setattr(monthly_report_asset_review, "pending_asset_indexes",
                        lambda *args, **kwargs: ())
    monkeypatch.setattr(monthly_report_asset_review, "asset_context",
                        lambda *args, **kwargs: (
                            source_reference(source, 1), "asset-source-context:v1:demo"))
    ready = replace(draft, sources=(source,), blocks=(block,))
    ledger = source_coverage(ready, source, replace(content, source=source))
    assert ledger.unread_pages == 0
    assert ledger.items[0].state == "applied"


def test_independent_expected_data_manifest_including_price_irrelevance():
    """The manifest is authored without consulting ledger-generated digest values."""
    import json
    from pathlib import Path
    from app.monthly_report_sources import source_reference

    manifest = json.loads((Path(__file__).parent / "fixtures" /
                           "a11_coverage_expected.json").read_text())
    assert set(manifest) == {"control", "mixed_price_irrelevant", "interrupted_reader"}
    for name, spec in manifest.items():
        draft, content = fixture(pages=tuple(spec["pages"]),
                                 notices=tuple(spec["notices"]))
        source = content.source
        accepted = [item for item in spec["expected"] if item["state"] == "applied"]
        if accepted:
            # The synthetic acceptance receipt identifies only page one; a
            # price page must never enter the text of the published block.
            first = accepted[0]
            reference = source_reference(source, 1)
            original = draft.blocks[0]
            receipt = contribution_receipt(reference, draft.profile, draft.period,
                original.key, text=first["value"], source=source, prior_block=original)
            draft = replace(draft, blocks=(replace(original, text=first["value"],
                                       references=(reference, receipt)),))
        for entry in spec["expected"]:
            if entry["state"] == "excluded":
                item = next(item for item in source_coverage(draft, source, content).items
                            if item.item_id == entry["item_id"])
                draft = exclude_from_coverage(draft, item, entry["reason"], content=content)
        ledger = source_coverage(draft, source, content)
        observed = {item.item_id: item for item in ledger.items}
        assert len(observed) == len(spec["expected"]), name
        for entry in spec["expected"]:
            item = observed[entry["item_id"]]
            independent_digest = sha256(json.dumps(entry["value"], sort_keys=True,
                ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            assert item.digest == independent_digest, (name, entry["item_id"])
            assert item.state == entry["state"], (name, entry["item_id"])
            if "destination" in entry:
                assert item.destination == entry["destination"]
        expected_supported = [
            {"source_id": source.id, "item_id": entry["item_id"],
             "digest": sha256(json.dumps(entry["value"], sort_keys=True,
                 ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
             "destination": entry["destination"]}
            for entry in spec["expected"] if entry["state"] == "applied"]
        score = exact_manifest_scores((ledger,), expected_supported)
        assert score["manifest_supported"] == len(expected_supported)
        if expected_supported:
            assert score["exact_supported_precision"] == 1.0
            assert all(value == 1 for value in score["recall_by_destination"].values())
        if name == "mixed_price_irrelevant":
            assert ledger.excluded == 2
            assert "Proposal fee" not in draft.blocks[0].text
        if name == "interrupted_reader":
            assert ledger.limited and ledger.needs_review == 2


def test_bulk_receipts_are_parsed_once_for_large_sheet(monkeypatch):
    from app import monthly_report_extraction_coverage as coverage
    table = SourceTable("Synthetic", ("ID",), tuple((str(i),) for i in range(200)))
    draft, content = fixture(pages=("One worksheet text",), suffix=".csv", tables=(table,))
    item = source_coverage(draft, content.source, content).items[0]
    updated = exclude_from_coverage(draft, item, "Standalone synthetic worksheet.")
    original_loads = coverage.json.loads
    count = []
    def counted(value, *args, **kwargs):
        count.append(1)
        return original_loads(value, *args, **kwargs)
    monkeypatch.setattr(coverage.json, "loads", counted)
    ledger = coverage.source_coverage(updated, content.source, content)
    assert ledger.rows == 200
    assert len(count) <= len(updated.source_coverage_receipts) + 1


def test_duplicate_rows_require_separate_accepted_occurrences():
    from app.monthly_report_model import ColumnSpec
    from app.monthly_report_sources import source_reference
    table = SourceTable("Sheet 1", ("ID", "Status"),
                        (("001", "Completed"), ("001", "Completed")))
    draft, content = fixture(pages=("ID\\tStatus\\n001\\tCompleted\\n001\\tCompleted",),
                             suffix=".csv", tables=(table,))
    source = content.source
    reference = source_reference(source, 1)
    columns = (ColumnSpec("id", "ID"), ColumnSpec("status", "Status"))
    accepted_row = (("001", "Completed"),)
    receipt = contribution_receipt(reference, draft.profile, draft.period, "service_calls",
                                   columns=("ID", "Status"), rows=accepted_row, source=source)
    block = ResolvedBlock("service_calls", "This month", rows=accepted_row,
                          references=(reference, receipt))
    draft = replace(draft,
        sections=(SectionSpec("maintenance", "5", "Service Calls",
                             (BlockSpec("service_calls", "table", columns=columns),)),),
        blocks=(block,))
    ledger = source_coverage(draft, source, content)
    row_items = [item for item in ledger.items if item.kind == "row"]
    assert len(row_items) == 2
    assert [item.state for item in row_items] == ["applied", "review"]
    assert ledger.applied == 1


@pytest.mark.parametrize("reason", ("boundary", "limit"))
def test_passage_notice_follows_existing_page_exclusion_receipt(reason):
    from app.monthly_report_vendor_passages import passage_notice
    from app.monthly_report_content_policy import page_fingerprint
    draft, content = fixture(pages=("Synthetic technical operating note.",),
                             suffix=".pdf", notices=(passage_notice(1, reason=reason),))
    source = content.source
    before = source_coverage(draft, source, content)
    assert before.limited and before.items[-1].state == "blocked"
    source = replace(source, client_page_exclusions=((1, page_fingerprint(source, 1)),))
    current = source_coverage(replace(draft, sources=(source,)), source,
                              replace(content, source=source))
    assert current.items[-1].state == "excluded"
    assert not current.limited


def test_unrecognized_page_notice_cannot_be_waived_by_page_decision():
    from app.monthly_report_content_policy import page_fingerprint
    draft, content = fixture(pages=("Synthetic technical note.",), suffix=".pdf",
                             notices=("Page 1: unknown parser failure.",))
    source = content.source
    source = replace(source, client_page_exclusions=((1, page_fingerprint(source, 1)),))
    ledger = source_coverage(replace(draft, sources=(source,)), source,
                             replace(content, source=source))
    assert ledger.items[-1].state == "blocked" and ledger.limited


def test_malformed_extra_table_has_explicit_parser_issue():
    a = SourceTable("One", ("ID",), (("1",),))
    b = SourceTable("Unexpected second table", ("ID",), (("2",),))
    draft, content = fixture(pages=("ID\\n1",), suffix=".csv", tables=(a, b))
    ledger = source_coverage(draft, content.source, content)
    assert ledger.rows == 2
    assert any(item.item_id == "tables:page-mismatch" and item.state == "blocked"
               for item in ledger.items)


def test_native_summary_and_source_item_jump_without_extra_editor_approval(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, content = fixture(pages=("Unaccepted technical statement.",))
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_coverage_ui import render_coverage
draft = st.session_state["test_draft"]
source_content = st.session_state["test_content"]
st.session_state["test_draft"] = render_coverage(
    draft, (source_content,), "a11-native", {block.key: block for block in draft.blocks})
""")
    app.session_state["test_draft"] = draft
    app.session_state["test_content"] = content
    app.run()
    assert not app.exception
    assert any("All sources · 1 files analyzed" in x.value and
               "1 issues need review" in x.value for x in app.caption)
    next(button for button in app.button if button.label == "Review extraction coverage").click().run()
    assert not app.exception
    assert any(widget.label == "Source item needing review" for widget in app.selectbox)
    next(button for button in app.button if button.label == "Open original item for review").click().run()
    assert not app.exception
    assert app.session_state["a11-native_evidence_selected"] == content.source.id
    assert app.session_state["a11-native_evidence_" + content.source.id + "_page"] == 1
    assert app.session_state["test_draft"].blocks == draft.blocks
