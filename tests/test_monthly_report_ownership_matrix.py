"""Validate a review artifact and its references, not application enforcement.

The matrix records current mechanisms separately from policy decisions. These
checks do not exercise shared saves, report rollover, browser gestures, or output.
"""
import ast
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/monthly_report_ownership_matrix.json"
DOCUMENT = ROOT / "docs/monthly_report_ownership_matrix.md"
EXPECTED = {
    "enfra_branding", "client_branding", "cover_photo",
    "workflow_business_hours", "workflow_after_hours", "org_chart",
    "facility_contacts", "thermal_capacity", "subcontractor_contacts",
    "subcontractor_status", "capital_renewal", "proposals", "issues",
    "training_requirements", "training_events", "activity_work_orders",
    "monthly_attachments", "source_originals",
}
SCENARIOS = {
    "workflows_between_contracts", "report_only_contact_correction",
    "vendor_master_promotion", "capacity_site_partition",
    "history_and_monthly_facts", "capital_proposal_revision",
}
VOCABULARIES = {
    "status_definitions": {"explicit_requirement", "meeting_intent", "existing_implementation",
                           "proposed_policy", "open_decision"},
    "scope_definitions": {"organization", "contract", "site", "contract_site", "report",
                          "report_month", "source_archive", "unresolved"},
    "inheritance_values": {"explicit_reuse", "review_before_reuse", "carry_context_only",
                           "never_automatic", "eligible_standing_defaults"},
    "promotion_values": {"approved_shared_save", "review_and_adopt", "decision_required",
                         "not_applicable", "qualified_automatic_keep", "explicit_matrix_edit"},
    "next_month_values": {"reuse_standing", "confirm_current", "carry_context", "reset", "review_source",
                          "retain_pinned", "refresh_eligible_copy"},
    "override_conflict_values": {"report_cas", "standing_cas", "proposed_standing_cas", "immutable_sha256"},
}
POLICY_FIELDS = {
    "scope": "scope_definitions", "decision": "status_definitions", "default": "inheritance_values",
    "promotion": "promotion_values", "next_month": "next_month_values",
    "version_conflict": "override_conflict_values",
}


def _read(path):
    assert path.is_file(), f"Missing ownership review artifact: {path.name}"
    return path.read_text(encoding="utf-8")


def _matrix():
    return json.loads(_read(SOURCE))


def _items(matrix):
    return {item["id"]: item for item in matrix["items"]}


def _text(value, label):
    assert isinstance(value, str) and value.strip(), f"Missing text: {label}"


def _strings(value, label, *, empty=False):
    assert isinstance(value, list) and (empty or value), f"Missing list: {label}"
    for entry in value:
        _text(entry, label)


def _anchor_shape(anchors, label):
    assert isinstance(anchors, list) and anchors, f"Missing anchors: {label}"
    pairs = []
    for anchor in anchors:
        assert isinstance(anchor, dict) and {"path", "symbols"} <= anchor.keys(), label
        _text(anchor["path"], label)
        path = PurePosixPath(anchor["path"])
        assert not path.is_absolute() and ".." not in path.parts and path.suffix == ".py", label
        _strings(anchor["symbols"], label)
        pairs.extend((anchor["path"], symbol) for symbol in anchor["symbols"])
    assert len(pairs) == len(set(pairs)), f"Duplicate anchors: {label}"


def _schema(matrix):
    assert isinstance(matrix, dict) and matrix.get("schema_version") == 2, "Expected review schema v2"
    assert isinstance(matrix.get("audited_main"), str)
    assert re.fullmatch(r"[0-9a-f]{40}", matrix["audited_main"]), "Invalid audited commit"
    _text(matrix.get("purpose"), "purpose")
    for name, expected in VOCABULARIES.items():
        values = matrix.get(name)
        assert isinstance(values, dict if name.endswith("definitions") else list), name
        assert len(values) == len(expected) and set(values) == expected, f"Unknown vocabulary: {name}"
        if isinstance(values, dict):
            for definition in values.values():
                _text(definition, name)
    _strings(matrix.get("global_safety_invariants"), "global_safety_invariants")
    rows = matrix.get("items")
    assert isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "Missing items"
    ids = [row.get("id") for row in rows]
    assert len(ids) == len(set(ids)) == len(EXPECTED) and set(ids) == EXPECTED, "Duplicate or missing item IDs"
    for row in rows:
        label = row["id"]
        for field, vocabulary in POLICY_FIELDS.items():
            assert isinstance(row.get(field), str) and row[field] in VOCABULARIES[vocabulary], \
                f"Invalid {field}: {label}"
        for field in ("label", "source", "report_override", "notes"):
            _text(row.get(field), f"{label}.{field}")
        mechanism = row.get("current_mechanism")
        assert isinstance(mechanism, dict), f"Missing current mechanism: {label}"
        _text(mechanism.get("summary"), f"{label}.current_mechanism.summary")
        _anchor_shape(mechanism.get("anchors"), label)
        _anchor_shape(mechanism.get("tests"), label)
        _strings(mechanism.get("limitations"), f"{label}.limitations", empty=True)
        _strings(row.get("open_choices"), f"{label}.open_choices", empty=True)
        if row["decision"] == "open_decision":
            assert row["open_choices"], f"Open decision needs its question: {label}"
        sources = row.get("decision_sources")
        assert isinstance(sources, list) and sources, f"Missing decision sources: {label}"
        for source in sources:
            assert isinstance(source, dict) and source.get("kind") in {"owner_intake", "implementation_record"}, label
            _text(source.get("supports"), f"{label}.decision_sources.supports")
            _text(source.get("url"), f"{label}.decision_sources.url")
            url = urlsplit(source["url"])
            assert url.scheme == "https" and url.netloc == "github.com" \
                and url.path.startswith("/evanroden/msapo-generator/"), label


@lru_cache(maxsize=None)
def _source_symbols(path):
    source = ROOT / path
    assert source.is_file(), f"Missing referenced source: {path}"
    symbols = set()

    def visit(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                symbols.add(name)
                visit(node.body, name + ".")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    symbols.update(prefix + part.id for part in ast.walk(target) if isinstance(part, ast.Name))

    visit(ast.parse(source.read_text(encoding="utf-8")).body)
    return symbols


def _existing_anchors(anchors, *, tests=False):
    _anchor_shape(anchors, "source references")
    for anchor in anchors:
        if tests:
            assert anchor["path"].startswith("tests/"), anchor["path"]
        else:
            assert not anchor["path"].startswith("tests/"), anchor["path"]
        missing = set(anchor["symbols"]) - _source_symbols(anchor["path"])
        assert not missing, f"Missing symbols in {anchor['path']}: {sorted(missing)}"


def _normalized(text):
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return " ".join(text.replace("`", "").replace("*", "").split())


def _section(document, heading):
    match = re.search(r"^### " + re.escape(heading) + r"\s*$", document, re.M)
    assert match, f"Missing document section: {heading}"
    tail = document[match.end():]
    end = re.search(r"^#{1,3} ", tail, re.M)
    return tail[:end.start()] if end else tail


def test_review_schema_has_complete_unique_items_and_qualified_vocabulary():
    _schema(_matrix())


@pytest.mark.parametrize("item_id", sorted(EXPECTED))
def test_each_item_has_current_source_and_test_symbols_in_both_artifacts(item_id):
    item = _items(_matrix())[item_id]
    mechanism = item.get("current_mechanism")
    assert isinstance(mechanism, dict), f"Missing current mechanism: {item_id}"
    _existing_anchors(mechanism["anchors"])
    _existing_anchors(mechanism["tests"], tests=True)
    section = _section(_read(DOCUMENT), item_id)
    assert _normalized(mechanism["summary"]) in _normalized(section), item_id
    for anchor in mechanism["anchors"] + mechanism["tests"]:
        assert anchor["path"] in section, (item_id, anchor["path"])
        assert all(symbol in section for symbol in anchor["symbols"]), item_id


def test_markdown_policy_rows_agree_with_machine_readable_decisions():
    matrix, document = _matrix(), _read(DOCUMENT)
    rows = {}
    for line in document.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [_normalized(cell.strip()) for cell in line.strip().strip("|").split("|")]
        if cells[0] not in EXPECTED:
            continue
        assert cells[0] not in rows, f"Duplicate Markdown row: {cells[0]}"
        assert len(cells) == 9, cells
        rows[cells[0]] = cells
    assert set(rows) == EXPECTED, "Markdown policy rows are missing or duplicated"
    for item in matrix["items"]:
        for column, field in ((1, "scope"), (2, "decision"), (3, "source"), (4, "default"),
                              (5, "report_override"), (6, "promotion"),
                              (7, "version_conflict"), (8, "next_month")):
            assert rows[item["id"]][column] == _normalized(item[field]), (item["id"], field)


def test_synthetic_scenarios_distinguish_current_results_from_pending_decisions():
    matrix, document = _matrix(), _read(DOCUMENT)
    scenarios = matrix["scenarios"]
    assert len(scenarios) == len(SCENARIOS) and {case["id"] for case in scenarios} == SCENARIOS
    for case in scenarios:
        assert case["contracts"] == ["A", "B"]
        assert case["sites"] == ["A1", "A2", "B1", "B2"]
        assert len(case["months"]) == 2 and len(set(case["months"])) == 2
        assert all(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) for month in case["months"])
        ordinals = [int(month[:4]) * 12 + int(month[5:]) for month in case["months"]]
        assert ordinals[1] - ordinals[0] == 1, f"Scenario months must be consecutive: {case['id']}"
        for field in ("steps", "expected", "current_expected"):
            _strings(case.get(field), f"{case['id']}.{field}")
        _strings(case.get("pending_or_decisions"), case["id"], empty=True)
        anchors = case.get("anchors")
        _anchor_shape(anchors, case["id"])
        _existing_anchors([anchor for anchor in anchors if not anchor["path"].startswith("tests/")])
        _existing_anchors([anchor for anchor in anchors if anchor["path"].startswith("tests/")], tests=True)
        section = _normalized(_section(document, case["id"]))
        for statement in case["current_expected"] + case["pending_or_decisions"]:
            assert _normalized(statement) in section, case["id"]
    vendor = next(case for case in scenarios if case["id"] == "vendor_master_promotion")
    assert vendor["pending_or_decisions"], "Planned vendor promotion must not be presented as current acceptance"


def test_index_and_machine_readable_companion_are_real_local_links():
    index, document = _read(ROOT / "docs/README.md"), _read(DOCUMENT)
    assert re.search(r"\[[^\]]+\]\(monthly_report_ownership_matrix\.md\)", index)
    assert re.search(r"\[[^\]]+\]\(monthly_report_ownership_matrix\.json\)", document)
    assert SOURCE.is_file()


def test_audited_snapshot_is_a_non_authorizing_decision_record():
    matrix, document = _matrix(), _read(DOCUMENT)
    assert matrix["audited_main"] in document
    purpose = matrix["purpose"].casefold()
    assert "does not authorize" in purpose and "migration" in purpose and "promotion" in purpose
    assert "not a production data migration" in _normalized(document[:2000]).casefold()


def test_narrow_policy_boundaries_do_not_turn_prior_month_facts_into_current_work():
    items = _items(_matrix())
    for name in ("workflow_business_hours", "workflow_after_hours"):
        assert items[name]["scope"] == "contract"
    capacity = items["thermal_capacity"]
    assert capacity["scope"] == "unresolved" and capacity["decision"] == "open_decision"
    for name in ("training_events", "activity_work_orders"):
        assert items[name]["scope"] == "report_month" and items[name]["next_month"] == "reset"
        assert items[name]["default"] == "never_automatic"
    assert items["issues"]["next_month"] == "carry_context"
    assert items["source_originals"]["scope"] == "source_archive"
    assert items["source_originals"]["version_conflict"] == "immutable_sha256"


@pytest.mark.parametrize("item_id,decision,source_file,source_symbol", [
    ("subcontractor_contacts", "existing_implementation",
     "app/monthly_report_subcontractor_roster.py", "save_roster"),
    ("subcontractor_status", "proposed_policy",
     "app/monthly_report_subcontractor_roster.py", "apply_roster"),
    ("capital_renewal", "existing_implementation",
     "app/monthly_report_capital_master.py", "select_capital"),
    ("training_requirements", "existing_implementation",
     "app/monthly_report_training.py", "_requirement_columns"),
    ("training_events", "existing_implementation",
     "app/monthly_report_training_import.py", "review_training_event_sites"),
])
def test_november_merged_ownership_mechanisms_are_current(
    item_id, decision, source_file, source_symbol,
):
    row = _items(_matrix())[item_id]
    assert row["decision"] == decision
    anchors = row["current_mechanism"]["anchors"]
    assert any(a["path"] == source_file and source_symbol in a["symbols"]
               for a in anchors)
    if item_id in {"subcontractor_contacts", "subcontractor_status", "capital_renewal"}:
        assert row["version_conflict"] == "standing_cas"
    section = _section(_read(DOCUMENT), item_id)
    assert source_file in section and source_symbol in section


def test_merged_starting_report_reversal_is_not_marked_unmerged():
    document = _read(DOCUMENT)
    assert "#687" in document
    assert "#687 remains unmerged" not in document
    assert "is unmerged at the audited main" not in document


@pytest.mark.parametrize("item_ids,obsolete_claim", [
    (("workflow_business_hours", "workflow_after_hours"), "still contains a global ENFRA standards path"),
    (("training_requirements",), "year-specific annual schema in PR #537 is not treated as merged"),
])
def test_current_mechanisms_do_not_repeat_obsolete_implementation_claims(item_ids, obsolete_claim):
    matrix, document = _matrix(), _read(DOCUMENT)
    items = _items(matrix)
    summaries = [item.get("current_mechanism", {}).get("summary", "") for name, item in items.items()
                 if name in item_ids]
    if not any(summaries):
        # The historical v1 artifact put current-code claims in this one block.
        summaries = [document.split("## Verified code behavior versus pending integration", 1)[-1]
                     .split("## Six worked scenarios", 1)[0]]
    assert obsolete_claim.casefold() not in _normalized(" ".join(summaries)).casefold()


@pytest.mark.parametrize("mutation,message", [
    ("duplicate_id", "Duplicate or missing item IDs"),
    ("missing_scope", "Invalid scope"),
    ("unknown_scope", "Invalid scope"),
    ("unqualified_approval", "Invalid decision"),
    ("unqualified_promotion", "Invalid promotion"),
    ("missing_mechanism", "Missing current mechanism"),
    ("missing_support", "Missing text"),
])
def test_schema_gate_rejects_corrupted_review_artifacts(mutation, message):
    matrix = _matrix()
    _schema(matrix)  # A mutant must not fail merely because its control was invalid.
    changed = deepcopy(matrix)
    row = changed["items"][0]
    if mutation == "duplicate_id":
        changed["items"][-1]["id"] = row["id"]
    elif mutation == "missing_scope":
        row.pop("scope")
    elif mutation == "unknown_scope":
        row["scope"] = "unrelated_global_default"
    elif mutation == "unqualified_approval":
        row["decision"] = "approved"
    elif mutation == "unqualified_promotion":
        row["promotion"] = "automatic"
    elif mutation == "missing_mechanism":
        row.pop("current_mechanism")
    elif mutation == "missing_support":
        row["decision_sources"][0]["supports"] = ""
    with pytest.raises(AssertionError, match=message):
        _schema(changed)
