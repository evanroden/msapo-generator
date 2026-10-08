from dataclasses import asdict, replace
import json

from app.monthly_report_content_policy import price_free_table, table_has_pricing
from app.monthly_report_library import draft_from_dict
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, ReportPeriod, ReportTable, ResolvedBlock,
    default_sections, synthetic_draft, synthetic_profiles,
)


def test_new_capital_and_proposal_tables_never_request_prices():
    specs = {b.key: b for section in default_sections() for b in section.blocks}
    assert [c.title for c in specs["capital_renewal"].columns] == ["Facility", "Priority", "Recommendation"]
    assert [c.title for c in specs["proposals"].columns] == ["Facility", "Vendor", "Scope", "Status"]


def test_legacy_copy_removes_price_columns_without_mutating_or_shifting_status():
    spec = BlockSpec("proposals", "table", columns=(
        ColumnSpec("facility", "Facility"), ColumnSpec("scope", "Scope"),
        ColumnSpec("amount", "Amount", "currency"), ColumnSpec("status", "Status"),
    ))
    block = ResolvedBlock("proposals", "Library", rows=(("Synthetic site", "Pump repair", "1200", "Pending"),),
                          references=("synthetic-source",), reviewed_fingerprint="old", client_reviewed_fingerprint="old")
    before = asdict(block)
    client_spec, client, removed = price_free_table(spec, block)
    assert [c.title for c in client_spec.columns] == ["Facility", "Scope", "Status"]
    assert client.rows == (("Synthetic site", "Pump repair", "Pending"),)
    assert removed == ("Amount",)
    assert client.references == block.references
    assert not client.reviewed_fingerprint and not client.client_reviewed_fingerprint
    assert asdict(block) == before and len(spec.columns) == 4
    assert price_free_table(client_spec, client) == (client_spec, client, ())


def test_extra_tables_multiline_headers_currency_type_and_unknown_cells():
    spec = BlockSpec("capital_renewal", "table", columns=(
        ColumnSpec("recommendation", "Recommendation"), ColumnSpec("estimate", "Estimate", "currency"),
    ))
    block = ResolvedBlock("capital_renewal", "Library", rows=(("Repair motor", "0", "Keep this unlabelled note"),),
                          extra_tables=(ReportTable(("Task", "Unit"), (("Description", "Price"), ("Inspection", "250")), "source-1"),))
    client_spec, client, removed = price_free_table(spec, block)
    assert [c.title for c in client_spec.columns] == ["Recommendation", "Detail 3"]
    assert client.rows == (("Repair motor", "Keep this unlabelled note"),)
    assert client.extra_tables == (ReportTable(("Task",), (("Description",), ("Inspection",)), "source-1"),)
    assert removed == ("Estimate", "Unit")


def test_inline_prices_stay_for_review_and_technical_counts_zero_false_are_preserved():
    spec = BlockSpec("technical", "table", columns=(ColumnSpec("detail", "Detail"), ColumnSpec("count", "Count", "number"), ColumnSpec("done", "Complete", "boolean")))
    block = ResolvedBlock("technical", "This month", rows=(("Pump repair $150", "0", "False"),), text="Cost $150")
    client_spec, client, removed = price_free_table(spec, block)
    assert (client_spec, client, removed) == (spec, block, ())
    assert table_has_pricing(tuple(c.title for c in client_spec.columns), client.rows)
    assert client.text == "Cost $150"


def test_legacy_schema_still_deserializes_with_full_price_values_for_history():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    legacy = BlockSpec("capital_renewal", "table", columns=(ColumnSpec("asset", "Asset"), ColumnSpec("cost", "Cost", "currency")))
    section = replace(default_sections()[8], blocks=(legacy,))
    block = ResolvedBlock("capital_renewal", "Library", rows=(("Synthetic pump", "1200"),))
    draft = replace(draft, sections=(section,), blocks=(block,))
    restored = draft_from_dict(json.loads(json.dumps(asdict(draft))))
    assert restored == draft
    _, client, removed = price_free_table(restored.sections[0].blocks[0], restored.blocks[0])
    assert client.rows == (("Synthetic pump",),) and removed == ("Cost",)
    assert restored.blocks[0].rows == (("Synthetic pump", "1200"),)
