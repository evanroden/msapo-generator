#!/usr/bin/env python3
"""Read-only enterprise migration preflight. NOT deployment authorization."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

CONTROL = Path("docs/azure/ENTERPRISE_DEPLOYMENT_CONTROL.json")
REQUIRED = [
    Path("docs/azure/MIGRATION_MANIFEST.md"),
    Path("docs/azure/GITHUB_ENTERPRISE_MIGRATION_RUNBOOK.md"),
    Path("docs/azure/GITHUB_ENTERPRISE_GOVERNANCE.md"),
]
AZURE_DEPLOY = re.compile(
    r"(azure/(?:login|webapps-deploy|cli|container-apps-deploy-action)@|\baz\s+(?:webapp\s+deploy|containerapp\s+update|acr\s+build)\b|\bazd\s+deploy\b)",
    re.I,
)

def check(root: Path) -> list[str]:
    problems = []
    for rel in REQUIRED:
        if not (root / rel).is_file():
            problems.append(f"Missing required document: {rel}")
    try:
        config = json.loads((root / CONTROL).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return problems + [f"Missing or invalid control file: {type(exc).__name__}"]
    azure = config.get("azure_deployment_enabled")
    render_retired = config.get("render_automation_retired")
    phase = config.get("phase")
    if config.get("schema_version") != 1:
        problems.append("Unsupported control schema")
    if phase not in ("preparation", "approved_cutover"):
        problems.append("Unknown phase")
    if not isinstance(azure, bool) or not isinstance(render_retired, bool):
        problems.append("Deployment flags must be booleans")
    if azure and not render_retired:
        problems.append("Duplicate deployment authority: Azure enabled while Render automation remains")
    if phase == "preparation" and (azure or render_retired):
        problems.append("Preparation must not enable Azure or claim Render retired")
    workflow_dir = root / ".github/workflows"
    active = sorted(
        p.relative_to(root).as_posix()
        for p in workflow_dir.glob("*")
        if p.suffix in (".yml", ".yaml") and AZURE_DEPLOY.search(p.read_text(encoding="utf-8"))
    )
    if active and (not azure or phase != "approved_cutover"):
        problems.append("Azure deployment workflow exists before approved cutover: " + ", ".join(active))
    return problems

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    errors = check(args.root.resolve())
    for message in errors:
        print("FAIL: " + message, file=sys.stderr)
    if errors:
        return 1
    print("PASS: read-only migration governance preflight (no destination or policy approval implied)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
