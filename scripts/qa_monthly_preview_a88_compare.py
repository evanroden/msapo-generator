"""A88 exact-image resource comparison for the synthetic MR-021 receipts.

No invented p95, synthetic client content, or inferred native queue timing.
Input receipts come from actual Docker runs of ONE production image at two caps.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics


def _read(path):
    return json.loads(Path(path).read_text())


def _samples(summary, count=3):
    values = summary["samples_ms"]
    assert len(values) == summary["n"] and len(values) >= count
    assert min(values) == summary["min_ms"]
    assert max(values) == summary["max_ms"]
    assert abs(statistics.median(values) - summary["median_ms"]) < 0.001
    if len(values) < 20:
        assert "p95_ms" not in summary, "Tiny samples cannot claim a p95"
    return summary["median_ms"]


def _resource(receipt, limit, cpu):
    environment = receipt["environment"]
    assert environment["memory_limit_bytes"] == limit
    assert environment["cpu_quota"] == cpu
    assert receipt["memory_events_delta"].get("oom", 0) == 0
    assert receipt["memory_events_delta"].get("oom_kill", 0) == 0
    assert receipt["peak_process_rss_bytes"] > 0
    assert receipt["elapsed_seconds"] >= 0
    assert receipt["python_process_cpu_seconds"] >= 0
    assert receipt["child_office_cpu_seconds"] >= 0
    return {"wall_seconds": receipt["elapsed_seconds"],
            "python_cpu_seconds": receipt["python_process_cpu_seconds"],
            "office_cpu_seconds": receipt["child_office_cpu_seconds"],
            "peak_process_rss_bytes": receipt["peak_process_rss_bytes"],
            "cgroup_peak_bytes": receipt["cgroup_peak_bytes"],
            "oom_events_delta": receipt["memory_events_delta"]}


def backend(root):
    receipts = {}
    for capacity, (memory, cpu) in {"capped": (512 * 1024 ** 2, 0.5),
                                    "larger": (1024 ** 3, 1.0)}.items():
        receipts[capacity] = {}
        for part in ("sources", "native"):
            data = _read(root / capacity / f"backend-{part}.json")
            assert data["part"] == part
            resources = _resource(data, memory, cpu)
            receipts[capacity][part] = {"raw": data, "resources": resources}
    out = {"scope": "synthetic same Docker image; not served production",
           "caps": {"capped": {"memory_mib": 512, "cpu": 0.5},
                    "larger": {"memory_mib": 1024, "cpu": 1.0}},
           "results": {}, "exact_checks": {}}
    for capacity in ("capped", "larger"):
        source = receipts[capacity]["sources"]["raw"]
        native = receipts[capacity]["native"]["raw"]["native_section"]
        cases = {case["workload"]: case for case in source["sources"]}
        expected = ("pdf-representative-24", "pdf-bounded-large-96", "docx-bounded-large-8image")
        assert all(name in cases for name in expected)
        assert native["runs"]["uncached_control"]["native_assemblies"] == 3
        assert native["runs"]["owner_scoped_reuse"]["native_assemblies"] == 1
        assert len(native["runs"]["uncached_control"]["samples"]) >= 3
        assert len(native["runs"]["owner_scoped_reuse"]["samples"]) >= 3
        contender = native["two_visitor_native"]
        assert len(contender["runs"]) == 3
        assert all(len(pair) == 2 and len({r["owner"] for r in pair}) == 2
                   and all(r["status"] in {"busy", "decoded"} for r in pair)
                   for pair in contender["runs"])
        native_total = [
            round(1000 * sample["total_seconds"], 3)
            for sample in native["runs"]["uncached_control"]["samples"]
        ]
        out["results"][capacity] = {
            "resources": {part: receipts[capacity][part]["resources"]
                          for part in ("sources", "native")},
            "source_cases": {name: {"fixture_sha256": cases[name]["fixture_sha256"],
                                       "source_bytes": cases[name]["source_bytes"],
                                   "source_pages_or_items": cases[name]["preservation"]["source_pages_or_items"],
                                   "first_thumbnail_sha256": cases[name]["preservation"]["first_thumbnail"]["hash"],
                                   "first_middle_last_thumbnail_sha256": [
                                       entry["hash"] for entry in cases[name]["preservation"].get(
                                           "first_middle_last_thumbnail_geometry_and_hash", ())]
                                   or None,
                                   "cold_median_ms": _samples(cases[name]["samples"]["cold_total"]),
                                   "warm_median_ms": _samples(cases[name]["samples"]["warm_total"])}
                             for name in expected},
            "native_uncached_three_run_ms": native_total,
            "native_uncached_min_median_max_ms": [
                min(native_total), statistics.median(native_total), max(native_total)],
            "native_competing_requests": [
                [{"status": entry["status"], "first_response_seconds": entry["first_response_seconds"],
                  "retry_status": entry.get("retry_status")}
                 for entry in pair] for pair in contender["runs"]],
            "concurrent_source_cases": {},
        }
        for name in ("pdf-24-page", "pdf-96-page"):
            row = source["concurrent_visitor_sources"][name]
            assert len(row["runs"]) == 3 and all(len(p) == 2 for p in row["runs"])
            out["results"][capacity]["concurrent_source_cases"][name] = {
                "cold_median_ms": _samples(row["cold"]),
                "warm_median_ms": _samples(row["warm"]),
                "source_sha256": row["source_sha256"],
                "queue_wait_measured": False}
    a, b = out["results"]["capped"], out["results"]["larger"]
    # Each run regenerates its fixtures, so raw fixture bytes are never
    # identical across runs: PyMuPDF writes a fresh random trailer /ID on
    # every save (the only differing bytes; rendered first thumbnails match).
    # Compare the rendered source instead: byte length, page/item count and
    # the first (and, for PDFs, first/middle/last) thumbnail hashes.
    for name in a["source_cases"]:
        for key in ("source_bytes", "source_pages_or_items", "first_thumbnail_sha256",
                    "first_middle_last_thumbnail_sha256"):
            assert a["source_cases"][name][key] == b["source_cases"][name][key], (
                f"Different rendered source between capped and larger runs: {name} ({key})")
    first = receipts["capped"]["native"]["raw"]["native_section"]
    second = receipts["larger"]["native"]["raw"]["native_section"]
    # The native DOCX fixture is regenerated per run, so its raw bytes differ
    # (python-docx container timestamps); the assembled package members are
    # byte-identical and the rendered rasters/geometry match. Compare those.
    assert first["source_docx_bytes"] == second["source_docx_bytes"], "Native input source size differs"
    assert first["runs"]["uncached_control"]["native_docx_package_sha256"] == (
        second["runs"]["uncached_control"]["native_docx_package_sha256"]), (
        "Native DOCX package contents differ across resource caps")
    assert first["output_equivalence"] == second["output_equivalence"], (
        "Native raster hash/page geometry differs across resource caps")
    out["exact_checks"] = {"same_rendered_source": True,
                           "same_native_package_sha256_and_size": True,
                           "same_native_raster_sha256_and_geometry": True,
                           "native_layout": first["output_equivalence"]}
    out["comparison"] = {
        name: {"capped_cold_ms": a["source_cases"][name]["cold_median_ms"],
               "larger_cold_ms": b["source_cases"][name]["cold_median_ms"]}
        for name in a["source_cases"]
    }
    return out


def browser(root):
    capped = _read(root / "browser-capped.json")
    larger = _read(root / "browser-larger.json")
    result = {"scope": "headless browser on host / same image under two container caps",
              "engines": {}}
    for name in ("chromium", "webkit"):
        summaries = {}
        for capacity, data in (("capped", capped), ("larger", larger)):
            rows = data["engines"][name]
            assert len(rows) >= 3
            for row in rows:
                for key in ("first_section_image", "thumbnail", "latest_section_image"):
                    im = row[key]
                    assert im["width"] > 0 and im["height"] > 0
                    assert len(im["decoded_png_sha256"]) == 64
                assert row["preview_generation_changed"] and row["manual_edit_retained"]
            names = ("fresh_report_press_to_decoded_section_seconds",
                     "native_upload_to_requested_decoded_thumbnail_seconds",
                     "edit_commit_to_current_section_seconds")
            summaries[capacity] = {
                key: {"n": len(rows),
                      "min_seconds": min(r[key] for r in rows),
                      "median_seconds": statistics.median(r[key] for r in rows),
                      "max_seconds": max(r[key] for r in rows)}
                for key in names}
        result["engines"][name] = summaries
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("backend", "browser"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = backend(args.root) if args.kind == "backend" else browser(args.root)
    output = args.root / f"a88-{args.kind}-comparison.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"receipt": str(output), "sha256": sha256(output.read_bytes()).hexdigest(),
                      "result": result}, indent=2), flush=True)


if __name__ == "__main__":
    main()
