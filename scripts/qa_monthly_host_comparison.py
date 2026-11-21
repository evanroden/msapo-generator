"""Compare two isolated Monthly latency receipts without contacting either host.

Inputs are synthetic-only bundles of the existing --part sources/native receipts.
Never submit production reports, request logs, URLs, access tokens or customer data.
A matching build/fixture is necessary, but not sufficient, for host attribution.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

WORKLOADS = (
    "pdf-small-2", "pdf-representative-24", "pdf-bounded-large-96",
    "docx-small-1image", "docx-representative-4image", "docx-bounded-large-8image",
)


def _number(value, field, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}: finite number required")
    if (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{field}: positive/nonnegative number required")
    return value


def _samples(values, field):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{field}: nonempty samples required")
    return [_number(value, field) for value in values]


def _summary(samples):
    return {"n": len(samples), "median_ms": round(median(samples), 3),
            "min_ms": round(min(samples), 3), "max_ms": round(max(samples), 3)}


def _sha(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field}: expected lowercase SHA-256")
    return value


def _commit(value):
    if not isinstance(value, str) or len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("build: exact 40-character commit required")
    return value


def _phase(receipt, name, commit):
    if not isinstance(receipt, dict) or receipt.get("part") != name:
        raise ValueError(f"{name}: wrong or missing phase")
    if receipt.get("boundary") != "server_received_bytes_to_first_raster_delivery":
        raise ValueError(f"{name}: measurement boundary differs")
    env = receipt.get("environment")
    if not isinstance(env, dict) or _commit(env.get("commit")) != commit:
        raise ValueError(f"{name}: measured and declared build differ")
    cpu = _number(env.get("cpu_quota"), f"{name} CPU quota", positive=True)
    memory = _number(env.get("memory_limit_bytes"), f"{name} memory limit", positive=True)
    events = receipt.get("memory_events_delta")
    if not isinstance(events, dict) or not all(key in events for key in ("oom", "oom_kill")):
        raise ValueError(f"{name}: OOM evidence missing")
    if any(_number(events[key], f"{name} {key}") != 0 for key in ("oom", "oom_kill")):
        raise ValueError(f"{name}: OOM-tainted measurements")
    metrics = {}
    for output, input_key in (("peak_rss_bytes", "peak_process_rss_bytes"),
                              ("cgroup_peak_bytes", "cgroup_peak_bytes"),
                              ("process_cpu_seconds", "python_process_cpu_seconds"),
                              ("child_office_cpu_seconds", "child_office_cpu_seconds")):
        raw = receipt.get(input_key)
        metrics[output] = None if raw is None else _number(raw, f"{name} {output}")
    return {"cpu": cpu, "memory": memory, "python": env.get("python"),
            "dependencies": env.get("dependencies"), **metrics}


def _bundle(bundle, label):
    if not isinstance(bundle, dict) or bundle.get("synthetic_only") is not True:
        raise ValueError(f"{label}: explicitly synthetic-only bundle required")
    if bundle.get("execution") not in ("isolated", "served_synthetic"):
        raise ValueError(f"{label}: execution must be isolated or served_synthetic")
    commit = _commit(bundle.get("served_commit"))
    sources = bundle.get("sources")
    native = bundle.get("native")
    source_environment = _phase(sources, "sources", commit)
    native_environment = _phase(native, "native", commit)
    if (source_environment["cpu"], source_environment["memory"]) != (native_environment["cpu"], native_environment["memory"]):
        raise ValueError(f"{label}: source and native limits are not identical")
    rows = sources.get("sources")
    if not isinstance(rows, list) or len(rows) != len(WORKLOADS):
        raise ValueError(f"{label}: six source workload receipts required")
    by_workload = {}
    fingerprints = {}
    for row in rows:
        name = row.get("workload") if isinstance(row, dict) else None
        if name not in WORKLOADS or name in by_workload:
            raise ValueError(f"{label}: unsupported or duplicate workload")
        hashes = _sha(row.get("fixture_sha256"), "fixture hash")
        size = _number(row.get("source_bytes"), "source bytes", positive=True)
        fingerprint = row.get("preservation", {})
        if not isinstance(fingerprint, dict):
            raise ValueError("missing preservation receipt")
        _sha(fingerprint.get("source_sha256"), "ingested hash")
        first = fingerprint.get("first_thumbnail")
        if not isinstance(first, dict):
            raise ValueError("missing thumbnail receipt")
        _sha(first.get("hash"), "thumbnail hash")
        fingerprints[name] = (hashes, size, fingerprint["source_sha256"], first["hash"],
                              first.get("width"), first.get("height"))
        measurements = row.get("samples", {})
        by_workload[name] = {}
        for phase in ("cold_total", "warm_total"):
            values = _samples(measurements.get(phase, {}).get("samples_ms"), name + ":" + phase)
            if len(values) != 5:
                raise ValueError(f"{name}:{phase}: five samples required")
            by_workload[name][phase] = _summary(values)
    section = native.get("native_section")
    if not isinstance(section, dict):
        raise ValueError("missing native section")
    native_sha = _sha(section.get("source_sha256"), "native source hash")
    geometry = section.get("output_equivalence")
    if not isinstance(geometry, dict) or not isinstance(geometry.get("rasters"), (list, tuple)) or not geometry["rasters"]:
        raise ValueError("missing native output equivalence")
    for value in geometry["rasters"]:
        _sha(value, "native raster hash")
    runs = section.get("runs", {})
    native_timings = {}
    for phase in ("uncached_control", "owner_scoped_reuse"):
        data = runs.get(phase, {})
        samples = data.get("samples")
        if not isinstance(samples, list) or len(samples) != 3:
            raise ValueError(f"native:{phase}: three samples required")
        values = [_number(s.get("total_seconds"), "native seconds") * 1000 for s in samples]
        native_timings[phase] = _summary(values)
    if runs["uncached_control"].get("native_assemblies") != 3 or runs["owner_scoped_reuse"].get("native_assemblies") != 1:
        raise ValueError("native assembly control counts differ")
    return {"build": commit, "execution": bundle["execution"], "region": bundle.get("region"),
            "service_resource_verified": bundle.get("service_resource_verified") is True,
            "source_env": source_environment, "native_env": native_environment,
            "sources": by_workload, "source_fingerprints": fingerprints,
            "native_source_sha256": native_sha, "native_geometry": geometry,
            "native": native_timings}


def compare(render, azure):
    left, right = _bundle(render, "render"), _bundle(azure, "azure")
    same_fixtures = (left["source_fingerprints"] == right["source_fingerprints"]
                     and left["native_source_sha256"] == right["native_source_sha256"])
    same_outputs = left["native_geometry"] == right["native_geometry"]
    same_build = left["build"] == right["build"]
    same_limits = (left["source_env"]["cpu"], left["source_env"]["memory"]) == (
        right["source_env"]["cpu"], right["source_env"]["memory"])
    same_software = (left["source_env"]["python"], left["source_env"]["dependencies"]) == (
        right["source_env"]["python"], right["source_env"]["dependencies"])
    region_known = (left["service_resource_verified"] and right["service_resource_verified"]
                    and isinstance(left["region"], str) and bool(left["region"].strip())
                    and isinstance(right["region"], str) and bool(right["region"].strip()))
    region_relation = ("same" if left["region"] == right["region"] else "different") if region_known else "unverified"
    reasons = []
    if region_relation == "different":
        reasons.append("different declared regions")
    for condition, reason in ((same_fixtures, "different synthetic bytes/source identities"),
                              (same_outputs, "different PDF page geometry/raster hashes"),
                              (same_build, "different measured build SHAs"),
                              (same_limits, "different CPU/memory limits"),
                              (same_software, "different Python/dependency versions"),
                              (left["execution"] == right["execution"], "different measurement execution boundaries")):
        if not condition:
            reasons.append(reason)
    return {"level": "isolated_synthetic_only" if left["execution"] == right["execution"] == "isolated"
            else "served_synthetic_only" if left["execution"] == right["execution"] == "served_synthetic"
            else "mixed_uncomparable",
            "same_workload": same_fixtures, "same_outputs": same_outputs,
            "same_build": same_build, "same_limits": same_limits, "same_software": same_software,
            "controlled_comparison": not reasons, "confounders": reasons,
            "region_relation": region_relation,
            "hosts": {name: {"build": data["build"], "execution": data["execution"],
                              "region": "declared" if data["service_resource_verified"] else "unverified",
                              "limit_cpu": data["source_env"]["cpu"],
                              "limit_memory_bytes": data["source_env"]["memory"],
                              "resource_verification": data["service_resource_verified"],
                              "source_peak_rss_bytes": data["source_env"]["peak_rss_bytes"],
                              "native_peak_rss_bytes": data["native_env"]["peak_rss_bytes"],
                              "source_cgroup_peak_bytes": data["source_env"]["cgroup_peak_bytes"],
                              "native_cgroup_peak_bytes": data["native_env"]["cgroup_peak_bytes"],
                              "source_cpu_seconds": data["source_env"]["process_cpu_seconds"],
                              "native_cpu_seconds": data["native_env"]["process_cpu_seconds"],
                              "native_office_cpu_seconds": data["native_env"]["child_office_cpu_seconds"],
                              "queue_seconds": None,
                              "source": data["sources"], "native": data["native"]}
                      for name, data in (("render", left), ("azure", right))},
            "attribution": "Measurements alone do not establish a host-caused application regression; "
                           "server-side medians are not browser first paint or queue time."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render", required=True, type=Path, help="synthetic-only JSON bundle")
    parser.add_argument("--azure", required=True, type=Path, help="synthetic-only JSON bundle")
    parser.add_argument("--output", type=Path, help="optional sanitized JSON summary")
    args = parser.parse_args(argv)
    try:
        # Never echo original receipt content or exception payloads: bundles may
        # inadvertently contain host identifiers or sensitive extra fields.
        left = json.loads(args.render.read_text(encoding="utf-8"))
        right = json.loads(args.azure.read_text(encoding="utf-8"))
        result = compare(left, right)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, json.JSONDecodeError) as error:
        parser.exit(2, f"Receipt validation failed: {type(error).__name__}\n")
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["controlled_comparison"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
