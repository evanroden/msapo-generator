#!/usr/bin/env python3
"""Offline-only A11 telemetry contract and synthetic alert-threshold exercise.

This does not ingest Application Insights events, deploy Azure rules, contact
action groups, write a real store, call AI, or create external submissions.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import uuid
from pathlib import Path

SPEC = Path(__file__).resolve().parents[1] / "docs/azure/ops/alert-spec.json"
REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,47}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
BACKENDS = {"sqlite", "postgresql", "azure_sql", "azure_files", "blob", "none"}
RESOURCES = {"database", "blob", "filesystem", "temporary", "network", "renderer", "ai", "external", "other"}
PHASES = {"startup", "save", "generate", "convert", "submit", "backup", "restore", "health"}
OPERATIONS = {"read", "write", "render", "submit", "retry", "verify"}
TEST_CORRELATION = "66666666-6666-4666-8666-666666666666"


def check_spec(spec: dict) -> None:
    assert spec["deploy"] is False, "preparation must not deploy rules"
    assert spec["table"] == "AppEvents"
    assert spec["custom_event_name"] == "msapo.op"
    ids = [rule["id"] for rule in spec["rules"]]
    assert len(ids) == len(set(ids)) >= 12, "missing or duplicate alert families"
    assert all(rule["enabled"] is False and rule["production_route"] == "TBD" for rule in spec["rules"])
    assert set(spec["required_properties"]).isdisjoint(spec["forbidden_properties"])
    allowed = set(spec["allowed_codes"])
    assert allowed
    for rule in spec["rules"]:
        assert set(rule["event_codes"]) <= allowed
        assert rule["kind"] in ("count", "p95_duration_ms")
        assert rule["window_minutes"] > 0 and rule["threshold"] > 0
        assert rule["route_role"] and rule["first_action"]


def validate_event(spec: dict, event: dict) -> bool:
    permitted = set(spec["required_properties"]) | set(spec["optional_properties"])
    if set(event) - permitted:
        return False
    if not set(spec["required_properties"]) <= set(event):
        return False
    if event["code"] not in spec["allowed_codes"]:
        return False
    if event["workflow"] not in spec["enum_workflow"] or event["outcome"] not in spec["enum_outcome"]:
        return False
    try:
        cid = uuid.UUID(event["correlation_id"])
        if cid.version != 4 or str(cid) != event["correlation_id"]:
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    if not SHA.fullmatch(event["build_sha"]) or not DIGEST.fullmatch(event["image_digest"]):
        return False
    if "reason_code" in event and not REASON.fullmatch(event["reason_code"]):
        return False
    for key, accepted in (("backend_kind", BACKENDS), ("resource_kind", RESOURCES),
                          ("phase", PHASES), ("operation", OPERATIONS)):
        if key in event and event[key] not in accepted:
            return False
    if "duration_ms" in event:
        val = event["duration_ms"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0:
            return False
    return True


def alert_fires(rule: dict, events: list[dict], now: int) -> bool:
    # This models only simple count and p95 conditions from the contract,
    # not Azure Monitor ingestion/query/evaluation semantics.
    matching = [
        e for e in events
        if now - rule["window_minutes"] * 60 < e["time"] <= now
        and e["props"]["code"] in rule["event_codes"]
    ]
    if rule["kind"] == "count":
        return len(matching) >= rule["threshold"]
    durations = sorted(e["props"].get("duration_ms", 0) for e in matching)
    if not durations:
        return False
    p95 = durations[max(0, math.ceil(0.95 * len(durations)) - 1)]
    return p95 > rule["threshold"]


def simulate(spec: dict) -> int:
    check_spec(spec)
    now = 100_000
    base = {
        "code": "save_failed", "workflow": "monthly",
        "correlation_id": TEST_CORRELATION,
        "build_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64,
        "outcome": "failed", "reason_code": "SYNTHETIC_FAILURE",
    }
    assert validate_event(spec, base), "expected valid allowlisted sample"
    tests = 0
    for rule in spec["rules"]:
        payload = dict(base, code=rule["event_codes"][0])
        if rule["kind"] == "p95_duration_ms":
            payload["duration_ms"] = rule["threshold"] + 1
            assert validate_event(spec, payload)
            positive = [{"time": now, "props": payload}]
            negative = [{"time": now, "props": dict(payload, duration_ms=rule["threshold"] - 1)}]
        else:
            n = rule["threshold"]
            positive = [{"time": now, "props": payload} for _ in range(n)]
            negative = [{"time": now, "props": payload} for _ in range(n - 1)]
        assert alert_fires(rule, positive, now), "missing positive: " + rule["id"]
        assert not alert_fires(rule, negative, now), "false positive: " + rule["id"]
        assert not alert_fires(rule, [{"time": now - 10_000, "props": payload}], now)
        tests += 3
    for bad_key in spec["forbidden_properties"]:
        assert not validate_event(spec, dict(base, **{bad_key: "private-content"})), "field leaked"
        tests += 1
    for invalid in (
        dict(base, reason_code="email@example.com"),
        dict(base, correlation_id="user-or-document-id"),
        dict(base, build_sha="private-document"),
        dict(base, image_digest="https://signed.example/path"),
        dict(base, outcome="customer name"),
    ):
        assert not validate_event(spec, invalid), "unsafe value was accepted"
        tests += 1
    print("PASS: %d alert families; %d synthetic checks; no Azure resources/actions." %
          (len(spec["rules"]), tests))
    return tests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    if args.dry_run:
        simulate(spec)
    else:
        check_spec(spec)
        print("PASS: privacy and disabled-by-default alert contract checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
