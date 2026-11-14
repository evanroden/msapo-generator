"""A10 offline release-blocker ledger; no production service or credentials accessed.

Inputs are sanitized, independently verified evidence receipts from a restricted
runner. JSON records are claims, not Azure attestation. This never promotes
synthetic output to AUTH01/02/03 or authorizes cutover.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_HASH = re.compile(r"^[0-9a-f]{64}$")
# scope 'pair' requires matching container and Azure-staging receipts;
# scope 'stage' requires a staging receipt; 'approval' is restricted signoff.
CHECKS = {
    "M01": {"release-sha": "approval", "repair-ledger": "approval"},
    "M02": {"enterprise-repo-policy": "approval"},
    "M03": {"isolated-approved-resources": "approval"},
    "M04": {"image-digest": "stage", "health-and-websocket": "stage", "upload-route": "stage"},
    "M05": {"entra-deny-and-rbac": "stage", "sessions-and-expiry": "stage",
            "protected-downloads": "stage"},
    "M06": {"tls-and-outbound": "stage"},
    "M07": {"database-and-file-locks": "stage", "restart-and-concurrent-writer": "stage"},
    "M08": {"dry-run-restore": "stage", "record-reconciliation": "stage"},
    "M09": {"monthly-first-action": "pair", "monthly-edit-save-reopen": "pair",
            "monthly-docx-pdf": "pair", "AUTH01": "pair", "AUTH02": "pair", "AUTH03": "pair"},
    "M10": {"po-first-action": "pair", "po-edit-save-download": "pair",
            "smartsheet-fake-idempotency": "pair"},
    "M11": {"expense-first-action": "pair", "expense-edit-save-download": "pair",
            "expense-attachment-handoff": "pair"},
    "M12": {"financial-exclusions": "pair"},
    "M13": {"two-user-conflict": "stage", "contract-site-isolation": "stage"},
    "M14": {"large-upload-and-conversion": "pair", "resource-restart-recovery": "stage",
            "native-word": "stage", "physical-device": "stage"},
    "M15": {"oidc-and-digest-provenance": "stage", "production-write-denial": "stage",
            "telemetry-and-recovery": "stage"},
    "M16": {"approved-cutover-and-rollback": "approval"},
}
PRIVATE = {"AUTH01", "AUTH02", "AUTH03"}
START_BLOCKED = {"M01", "M02", "M03"}


def valid_receipt(r: dict, *, sha: str, digest: str) -> bool:
    if (not isinstance(r, dict) or r.get("source_sha") != sha or
            r.get("image_digest") != digest or
            r.get("environment") not in ("container", "azure-staging", "approval") or
            r.get("status") not in ("PASS", "FAIL", "NOT_RUN", "BLOCKED") or
            not isinstance(r.get("test_id"), str) or
            not isinstance(r.get("fixture_id"), str) or
            not r["fixture_id"].strip() or
            not isinstance(r.get("evidence_sha256"), str) or
            not EVIDENCE_HASH.fullmatch(r["evidence_sha256"]) or
            r.get("data_class") not in ("synthetic", "authentic_restricted", "configuration")):
        return False
    if r["test_id"] in PRIVATE and r["data_class"] != "authentic_restricted":
        return False
    if r["test_id"] not in PRIVATE and r["data_class"] == "authentic_restricted":
        return False
    return True


def pair_verdict(base: dict | None, stage: dict | None) -> str:
    """Flag candidate regressions without claiming their root cause."""
    if not base or not stage:
        return "NOT_RUN"
    if any(base.get(k) != stage.get(k) for k in
           ("source_sha", "image_digest", "fixture_id", "test_id", "data_class")):
        return "BLOCKED"
    if base.get("environment") != "container" or stage.get("environment") != "azure-staging":
        return "BLOCKED"
    b, a = base["status"], stage["status"]
    if b in ("NOT_RUN", "BLOCKED") or a in ("NOT_RUN", "BLOCKED"):
        return "NOT_RUN" if "NOT_RUN" in (b, a) else "BLOCKED"
    if b == "PASS" and a == "PASS":
        return "PASS"
    if b == "FAIL" and a == "FAIL":
        return "EXISTING_OR_SHARED_DEFECT"
    if b == "PASS" and a == "FAIL":
        return "POTENTIAL_MIGRATION_REGRESSION"
    return "UNDETERMINED"


def summarize(receipts: list[dict], sha: str, digest: str) -> dict:
    if not SHA.fullmatch(sha) or not DIGEST.fullmatch(digest):
        raise ValueError("An exact source SHA and immutable image digest are required")
    indexed = defaultdict(list)
    invalid = 0
    for record in receipts:
        if not valid_receipt(record, sha=sha, digest=digest):
            invalid += 1
            continue
        indexed[record["test_id"], record["environment"]].append(record)
    checks = {}
    rows = []
    for gate, conditions in CHECKS.items():
        statuses = []
        for name, scope in conditions.items():
            records = {env: indexed.get((name, env), []) for env in
                       ("container", "azure-staging", "approval")}
            # Conflicting/duplicate receipts never select the convenient PASS.
            if any(len(values) > 1 for values in records.values()):
                status = "BLOCKED"
            elif scope == "pair":
                status = pair_verdict((records["container"] or [None])[0],
                                      (records["azure-staging"] or [None])[0])
            else:
                expected = "approval" if scope == "approval" else "azure-staging"
                receipt = (records[expected] or [None])[0]
                status = receipt["status"] if receipt else "NOT_RUN"
            if name in PRIVATE and status == "PASS":
                a = records["container"][0]
                b = records["azure-staging"][0]
                if any(x["data_class"] != "authentic_restricted" for x in (a, b)):
                    status = "BLOCKED"
            statuses.append(status)
            checks[name] = status
        if gate == "M16":
            state = "FUTURE_ONLY"
        elif any(s in ("FAIL", "POTENTIAL_MIGRATION_REGRESSION",
                       "EXISTING_OR_SHARED_DEFECT", "UNDETERMINED") for s in statuses):
            state = "FAIL"
        elif "BLOCKED" in statuses:
            state = "BLOCKED"
        elif "NOT_RUN" in statuses:
            state = "BLOCKED" if gate in START_BLOCKED else "NOT_RUN"
        else:
            state = "PASS"
        rows.append({"gate": gate, "status": state, "passed": sum(s == "PASS" for s in statuses),
                     "required": len(statuses)})
    return {"kind": "A10-azure-release-blockers",
            "at_utc": datetime.now(timezone.utc).isoformat(), "source_sha": sha,
            "image_digest": digest, "invalid_receipts": invalid, "gates": rows, "checks": checks,
            "go_no_go": "NO_GO",
            "limitations": ["Public CI cannot hold authentic-source acceptance evidence.",
                            "Receipts require independent restricted-runner verification.",
                            "M16 cutover is never authorized by this script."]}


def markdown_report(data: dict) -> str:
    rows = ["# A10 Azure release blocker report", "", "**Release decision: NO GO**", "",
            "| A01 gate | Verdict | Checks passed |", "|---|---|---:|"]
    rows += [f"| {r['gate']} | {r['status']} | {r['passed']}/{r['required']} |"
             for r in data["gates"]]
    rows += ["", "Only independently verified, restricted evidence can clear a gate. "
            "The release is never authorized by this report."]
    return "\n".join(rows) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--receipts", type=Path, help="Restricted local JSON array; omit for missing evidence")
    parser.add_argument("--enforce", action="store_true", help="Nonzero exit if release gate is not cleared")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipts = json.loads(args.receipts.read_text()) if args.receipts else []
        if not isinstance(receipts, list):
            raise ValueError("Receipt file must contain a list")
        data = summarize(receipts, args.sha, args.digest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        data = {"kind": "A10-azure-release-blockers", "go_no_go": "NO_GO",
                "status": "BLOCKED", "error_type": type(error).__name__}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(".md").write_text(
        markdown_report(data) if "gates" in data else "# A10 blocked: invalid evidence input\n")
    print("A10 release gate: " + data["go_no_go"])
    return 4 if data.get("status") == "BLOCKED" else (
        2 if args.enforce and data["go_no_go"] != "GO" else 0)


if __name__ == "__main__":
    raise SystemExit(main())
