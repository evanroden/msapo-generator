"""Offline release gate tests; synthetic receipts are never deployment evidence."""
import json
from scripts.qa_azure_release_gate import CHECKS, main, pair_verdict, summarize, valid_receipt

SHA = "a"*40
DIGEST = "sha256:" + "b"*64


def rec(test, environment, state="PASS", fixture="synthetic_fixture_01", classification="synthetic"):
    return {"test_id": test, "environment": environment, "status": state,
            "source_sha": SHA, "image_digest": DIGEST, "fixture_id": fixture,
            "data_class": classification, "evidence_sha256": "d"*64}


def test_no_evidence_remains_no_go_with_all_sixteen_a01_gates():
    report = summarize([], SHA, DIGEST)
    assert len(report["gates"]) == 16
    assert {row["gate"] for row in report["gates"]} == set(CHECKS)
    assert report["go_no_go"] == "NO_GO"
    assert report["gates"][0]["status"] == "BLOCKED"
    assert report["gates"][-1]["status"] == "FUTURE_ONLY"
    assert report["checks"]["AUTH03"] == "NOT_RUN"


def test_paired_comparison_classification_and_identity_rejection():
    assert pair_verdict(rec("monthly-docx-pdf", "container"), rec("monthly-docx-pdf", "azure-staging")) == "PASS"
    assert pair_verdict(rec("monthly-docx-pdf", "container"),
                        rec("monthly-docx-pdf", "azure-staging", "FAIL")) == "POTENTIAL_MIGRATION_REGRESSION"
    assert pair_verdict(rec("monthly-docx-pdf", "container", "FAIL"),
                        rec("monthly-docx-pdf", "azure-staging", "FAIL")) == "EXISTING_OR_SHARED_DEFECT"
    assert pair_verdict(rec("monthly-docx-pdf", "container"),
                        rec("monthly-docx-pdf", "azure-staging", fixture="mismatch")) == "BLOCKED"
    assert pair_verdict(None, rec("monthly-docx-pdf", "azure-staging")) == "NOT_RUN"


def test_private_auth_scenarios_cannot_pass_from_synthetic():
    assert not valid_receipt(rec("AUTH01", "container"), sha=SHA, digest=DIGEST)
    report = summarize([rec("AUTH01", "container"), rec("AUTH01", "azure-staging")], SHA, DIGEST)
    assert report["invalid_receipts"] == 2
    assert report["checks"]["AUTH01"] == "NOT_RUN"
    private = [rec("AUTH01", "container", classification="authentic_restricted"),
               rec("AUTH01", "azure-staging", classification="authentic_restricted")]
    assert summarize(private, SHA, DIGEST)["checks"]["AUTH01"] == "PASS"
    assert summarize(private, SHA, DIGEST)["go_no_go"] == "NO_GO"


def test_missing_azure_evidence_and_duplicates_never_pass():
    baseline = rec("monthly-first-action", "container")
    assert summarize([baseline], SHA, DIGEST)["checks"]["monthly-first-action"] == "NOT_RUN"
    assert summarize([baseline, baseline, rec("monthly-first-action", "azure-staging")],
                     SHA, DIGEST)["checks"]["monthly-first-action"] == "BLOCKED"


def test_wrong_image_digest_and_invalid_config_receipts_rejected():
    good = rec("image-digest", "azure-staging", classification="configuration")
    assert valid_receipt(good, sha=SHA, digest=DIGEST)
    assert not valid_receipt({**good, "image_digest": "sha256:"+"c"*64}, sha=SHA, digest=DIGEST)
    assert not valid_receipt({**good, "evidence_sha256": "PRIVATE"}, sha=SHA, digest=DIGEST)
    assert summarize([good], SHA, DIGEST)["checks"]["image-digest"] == "PASS"


def test_fail_closed_cli_produces_sanitized_matrix(tmp_path):
    output = tmp_path / "release.json"
    assert main(["--sha", SHA, "--digest", DIGEST, "--output", str(output)]) == 0
    record = json.loads(output.read_text())
    assert record["go_no_go"] == "NO_GO"
    assert main(["--sha", SHA, "--digest", DIGEST, "--enforce",
                 "--output", str(output)]) == 2
    assert (tmp_path / "release.md").is_file()
    bad = tmp_path / "bad.json"
    bad.write_text('{"untrusted": true}')
    assert main(["--sha", SHA, "--digest", DIGEST, "--receipts", str(bad),
                 "--output", str(output)]) == 4
    assert json.loads(output.read_text())["status"] == "BLOCKED"
