"""Synthetic controls and failure-path coverage for two-host latency receipts."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.qa_monthly_host_comparison import WORKLOADS, compare

SHA = "a" * 40
DIGEST = "b" * 64
OUTPUT = "c" * 64


def _phase(name, commit=SHA, cpu=.5, memory=512 * 1024 * 1024):
    return {"part": name, "boundary": "server_received_bytes_to_first_raster_delivery",
            "environment": {"commit": commit, "cpu_quota": cpu, "memory_limit_bytes": memory,
                            "python": "3.12.1", "dependencies": {"PyMuPDF": "1.25.1"}},
            "memory_events_delta": {"oom": 0, "oom_kill": 0},
            "python_process_cpu_seconds": 1.2, "child_office_cpu_seconds": .3,
            "peak_process_rss_bytes": 200_000_000, "cgroup_peak_bytes": 250_000_000}


def bundle(commit=SHA):
    sources = _phase("sources", commit)
    sources["sources"] = [
        {"workload": name, "fixture_sha256": DIGEST, "source_bytes": 4096,
         "preservation": {"source_sha256": DIGEST,
                          "first_thumbnail": {"hash": OUTPUT, "width": 300, "height": 200}},
         "samples": {"cold_total": {"samples_ms": [8, 3, 6, 10, 4]},
                     "warm_total": {"samples_ms": [2, 1, 3, 2, 2]}}}
        for name in WORKLOADS
    ]
    native = _phase("native", commit)
    native["native_section"] = {
        "source_sha256": DIGEST,
        "output_equivalence": {"pages": 2, "sizes": [[612, 792], [612, 792]],
                               "rasters": [OUTPUT, OUTPUT]},
        "runs": {"uncached_control": {"native_assemblies": 3,
                                      "samples": [{"total_seconds": v} for v in [1, 2, 3]]},
                 "owner_scoped_reuse": {"native_assemblies": 1,
                                        "samples": [{"total_seconds": v} for v in [.1, .2, .3]]}},
    }
    return {"synthetic_only": True, "execution": "isolated", "served_commit": commit,
            "region": "synthetic-region", "service_resource_verified": False,
            "sources": sources, "native": native}


def test_equal_controls_report_cold_warm_medians_and_no_production_claim():
    result = compare(bundle(), bundle())
    assert result["controlled_comparison"] is True
    assert result["same_workload"] is True
    assert result["level"] == "isolated_synthetic_only"
    row = result["hosts"]["render"]["source"][WORKLOADS[0]]
    assert row["cold_total"] == {"n": 5, "median_ms": 6, "min_ms": 3, "max_ms": 10}
    assert row["warm_total"]["median_ms"] == 2
    assert result["hosts"]["azure"]["native"]["uncached_control"]["median_ms"] == 2000
    assert result["hosts"]["azure"]["native"]["owner_scoped_reuse"]["median_ms"] == 200
    assert result["hosts"]["render"]["region"] == "unverified"
    assert "not browser first paint" in result["attribution"]


def test_differing_build_never_claims_software_regression():
    result = compare(bundle(), bundle("d" * 40))
    assert not result["controlled_comparison"]
    assert result["same_build"] is False
    assert "different measured build SHAs" in result["confounders"]


def test_same_build_different_limits_is_confounder():
    azure = bundle()
    for name in ("sources", "native"):
        azure[name]["environment"]["cpu_quota"] = 1
        azure[name]["environment"]["memory_limit_bytes"] = 2 * 1024 ** 3
    result = compare(bundle(), azure)
    assert result["same_build"] and result["same_workload"]
    assert not result["same_limits"] and not result["controlled_comparison"]


def test_stale_receipt_and_conflicting_source_native_limits_rejected():
    azure = bundle()
    azure["sources"]["environment"]["commit"] = "e" * 40
    with pytest.raises(ValueError, match="measured and declared"):
        compare(bundle(), azure)
    azure = bundle()
    azure["native"]["environment"]["memory_limit_bytes"] += 1
    with pytest.raises(ValueError, match="not identical"):
        compare(bundle(), azure)


@pytest.mark.parametrize("change", [
    lambda b: b.pop("sources"),
    lambda b: b.update(synthetic_only=False),
    lambda b: b["sources"]["sources"].pop(),
    lambda b: b["sources"]["sources"].append(copy.deepcopy(b["sources"]["sources"][0])),
    lambda b: b["sources"]["sources"][0]["samples"]["cold_total"].update(samples_ms=[1]),
    lambda b: b["sources"]["sources"][0]["samples"]["warm_total"].update(samples_ms=[1, 2, float("nan"), 4, 5]),
    lambda b: b["native"]["native_section"]["runs"]["owner_scoped_reuse"].update(native_assemblies=3),
    lambda b: b["sources"]["memory_events_delta"].update(oom=1),
    lambda b: b["sources"].update(part="native"),
    lambda b: b.update(execution="customer_report"),
])
def test_missing_malformed_duplicate_oom_or_unsupported_rejected(change):
    azure = bundle()
    change(azure)
    with pytest.raises((ValueError, AttributeError, TypeError)):
        compare(bundle(), azure)


def test_different_input_hash_or_native_page_identity_not_comparable():
    different = bundle()
    different["sources"]["sources"][0]["fixture_sha256"] = "e" * 64
    result = compare(bundle(), different)
    assert not result["same_workload"] and not result["controlled_comparison"]
    different = bundle()
    different["native"]["native_section"]["output_equivalence"]["sizes"][0] = [595, 842]
    result = compare(bundle(), different)
    assert not result["same_outputs"] and not result["controlled_comparison"]


def test_cli_ignores_extra_private_keys_and_fails_closed_without_echo(tmp_path):
    left, right = bundle(), bundle()
    secret = "NEVER_PRINT_PRIVATE_HOST_OR_USER_TOKEN"
    left["private_host"] = secret
    right["sources"]["customer_dump"] = secret
    rpath, apath = tmp_path / "render.json", tmp_path / "azure.json"
    rpath.write_text(json.dumps(left))
    apath.write_text(json.dumps(right))
    script = Path(__file__).resolve().parents[1] / "scripts" / "qa_monthly_host_comparison.py"
    completed = subprocess.run([sys.executable, str(script), "--render", str(rpath), "--azure", str(apath)],
                               capture_output=True, text=True)
    assert completed.returncode == 0
    assert secret not in completed.stdout + completed.stderr
    apath.write_text(secret)
    completed = subprocess.run([sys.executable, str(script), "--render", str(rpath), "--azure", str(apath)],
                               capture_output=True, text=True)
    assert completed.returncode == 2
    assert secret not in completed.stdout + completed.stderr

def test_verified_region_mismatch_is_confounder_without_leaking_private_identity():
    left, right = bundle(), bundle()
    private1, private2 = "PRIVATE-REGION-A", "PRIVATE-REGION-B"
    left["region"] = private1
    right["region"] = private2
    left["service_resource_verified"] = True
    right["service_resource_verified"] = True
    result = compare(left, right)
    assert not result["controlled_comparison"]
    assert result["region_relation"] == "different"
    assert "different declared regions" in result["confounders"]
    assert private1 not in json.dumps(result)
    assert private2 not in json.dumps(result)
