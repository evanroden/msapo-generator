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
