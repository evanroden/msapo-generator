"""The MR-008A design record is reviewable, complete, and non-authorizing.

These tests validate a *specification*, not production enforcement. The
contract/site/month migration and browser acceptance remain separate work.
"""
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/monthly_report_ownership_matrix.json"
DOCUMENT = ROOT / "docs/monthly_report_ownership_matrix.md"
MATRIX = json.loads(SOURCE.read_text(encoding="utf-8"))
ITEMS = {item["id"]: item for item in MATRIX["items"]}

EXPECTED = {
    "enfra_branding", "client_branding", "cover_photo",
    "workflow_business_hours", "workflow_after_hours", "org_chart",
    "facility_contacts", "thermal_capacity", "subcontractor_contacts",
    "subcontractor_status", "capital_renewal", "proposals", "issues",
    "training_requirements", "training_events", "activity_work_orders",
    "monthly_attachments", "source_originals",
}


def test_complete_scope_matrix_has_unique_sources_and_known_decision_vocabulary():
    assert MATRIX["schema_version"] == 1
    assert len(MATRIX["items"]) == len(ITEMS) == len(EXPECTED)
    assert set(ITEMS) == EXPECTED
    assert set(MATRIX["status_definitions"]) == {
        "explicit_requirement", "meeting_intent", "existing_implementation",
        "proposed_policy", "open_decision",
    }
    assert MATRIX["audited_main"] and len(MATRIX["audited_main"]) == 40
    assert "not authorize" in MATRIX["purpose"] and "migration" in MATRIX["purpose"]
    for item in MATRIX["items"]:
        assert item["scope"] in MATRIX["scope_definitions"], item["id"]
        assert item["decision"] in MATRIX["status_definitions"], item["id"]
        assert item["default"] in MATRIX["inheritance_values"], item["id"]
        assert item["promotion"] in MATRIX["promotion_values"], item["id"]
        assert item["next_month"] in MATRIX["next_month_values"], item["id"]
        assert len(item["notes"].strip()) >= 40
        assert item["source"].strip() and item["label"].strip()
        assert item["code"] and all((ROOT / path).is_file() for path in item["code"])


def test_cross_contract_workflow_reuse_is_a_meeting_requirement_not_a_claim_about_main():
    for name in ("workflow_business_hours", "workflow_after_hours"):
        item = ITEMS[name]
        assert item["scope"] == "contract"
        assert item["decision"] == "explicit_requirement"
        assert item["default"] == "explicit_reuse"
        assert item["promotion"] == "review_and_adopt"
        assert "global" in item["notes"].lower() or "cross-contract" in item["notes"].lower()
    assert "global ENFRA standards path" in DOCUMENT.read_text()
    assert "#533" in DOCUMENT.read_text()


def test_capacity_policy_stays_open_with_site_partitioned_current_code():
    item = ITEMS["thermal_capacity"]
    assert item["scope"] == "unresolved"
    assert item["decision"] == "open_decision"
    assert item["default"] == "review_before_reuse"
    assert item["promotion"] == "decision_required"
    assert "site_keys" in item["source"] and "site" in item["notes"].lower()
    assert "Thermal capacity" in DOCUMENT.read_text()


def test_no_proposed_or_unapproved_standing_content_is_automatically_promoted():
    for item in MATRIX["items"]:
        assert item["promotion"] != "automatic"
        if item["decision"] in {"meeting_intent", "proposed_policy", "open_decision"}:
            assert item["default"] != "never_automatic" or item["next_month"] == "reset"
            assert item["promotion"] in {"approved_shared_save", "review_and_adopt",
                                         "decision_required", "not_applicable"}
    for name in ("subcontractor_contacts", "capital_renewal", "org_chart"):
        assert ITEMS[name]["promotion"] == "approved_shared_save"
    assert ITEMS["source_originals"]["scope"] == "source_archive"
    assert ITEMS["source_originals"]["default"] == "never_automatic"


def test_report_bound_completed_events_and_work_orders_do_not_become_new_month_facts():
    for name in ("training_events", "activity_work_orders"):
        assert ITEMS[name]["scope"] == "report_month"
        assert ITEMS[name]["next_month"] == "reset"
        assert ITEMS[name]["default"] == "never_automatic"
        assert ITEMS[name]["promotion"] == "not_applicable"
    assert ITEMS["issues"]["next_month"] == "carry_context"
    assert ITEMS["training_requirements"]["scope"] == "contract_site"
    assert ITEMS["training_requirements"]["next_month"] == "reuse_standing"
    assert "PR #537" in DOCUMENT.read_text()


def test_six_two_contract_two_site_two_month_examples_have_precise_invariants():
    expected_cases = {
        "workflows_between_contracts", "report_only_contact_correction",
        "vendor_master_promotion", "capacity_site_partition",
        "history_and_monthly_facts", "capital_proposal_revision",
    }
    examples = MATRIX["scenarios"]
    assert len(examples) == len(expected_cases) == len({x["id"] for x in examples})
    assert {x["id"] for x in examples} == expected_cases
    for case in examples:
        assert case["contracts"] == ["A", "B"]
        assert case["sites"] == ["A1", "A2", "B1", "B2"]
        assert case["months"] == ["2026-09", "2026-10"]
        assert len(case["steps"]) >= 3 and len(case["expected"]) >= 3
        assert any("unchanged" in line.lower() or "remain" in line.lower()
                   or "not inherit" in line.lower() or "not" in line.lower()
                   for line in case["expected"])


def test_markdown_is_complete_and_explicitly_rejects_unauthorized_migration():
    content = DOCUMENT.read_text(encoding="utf-8")
    for item in MATRIX["items"]:
        assert "| " + item["id"] + " |" in content, item["id"]
    for case in MATRIX["scenarios"]:
        assert "### " + case["id"] in content
    for required in ("Open choices", "not a production data migration",
                     "original", "version", "Omit", "source", "scope"):
        assert required.casefold() in content.casefold()
    assert len(MATRIX["global_safety_invariants"]) >= 6
    assert any("contract B" in item for item in MATRIX["global_safety_invariants"])


@pytest.mark.parametrize("item_id", sorted(EXPECTED))
def test_each_scope_item_has_traceable_code_anchor_and_lifecycle(item_id):
    item = ITEMS[item_id]
    assert item["next_month"] in MATRIX["next_month_values"]
    assert item["code"]
    assert item["scope"] in MATRIX["scope_definitions"]
