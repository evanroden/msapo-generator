"""Partition every pytest test across independent full-suite CI jobs.

Durations are from the 14,436-test full run on main 5526fd2b (run
43742773280). The 120 slowest files account for 84.5% of measured time;
unknown/new files receive the measured mean for the remaining 834 files.
Each job computes the same deterministic plan from the checkout, so adding
or renaming a test file cannot silently drop it from the full suite. The
currently slow frontend module is split by function across existing shards;
each parametrized function still runs all cases.
"""

from __future__ import annotations

import argparse
import ast
import math
from pathlib import Path

DURATIONS = Path(__file__).with_name("ci_test_durations.tsv")
# 934.9 seconds across 834 historical files not explicitly listed.
UNKNOWN_SECONDS = 934.9 / 834
# Only this benchmarked hot file is eligible for conservative function splitting.
SPLIT_FILE = "tests/test_streamlit_frontend_compat.py"


def test_files(repo: Path) -> list[str]:
    """Discover every pytest test module, including newly introduced files."""
    return sorted(path.relative_to(repo).as_posix()
                  for path in (repo / "tests").rglob("test_*.py") if path.is_file())


def read_durations(path: Path = DURATIONS) -> dict[str, float]:
    """Fail closed on a malformed duration snapshot instead of mis-sharding."""
    durations: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        rel, seconds = line.split("\t")
        duration = float(seconds)
        file_path, separator, node_id = rel.partition("::")
        valid_path = file_path.startswith("tests/test_") and file_path.endswith(".py")
        valid_node = not separator or (
            file_path == SPLIT_FILE and node_id.startswith("test_") and "::" not in node_id
        )
        if not valid_path or not valid_node or not math.isfinite(duration) or duration <= 0 or rel in durations:
            raise ValueError(f"Invalid or duplicated test duration: {rel!r}")
        durations[rel] = duration
    if not durations:
        raise ValueError("No recorded durations supplied")
    return durations



def expanded_test_items(
    repo: Path, files: list[str], durations: dict[str, float]
) -> tuple[list[str], dict[str, float]]:
    """Spread the pinned hot file using measured function times; preserve cases.

    Pytest function node selectors collect *all* parameters. When the module
    cannot be parsed or gains class/custom collection hooks, run the whole
    original file instead of silently dropping an unrecognized test.
    """
    if SPLIT_FILE not in files:
        return files, durations
    try:
        tree = ast.parse((repo / SPLIT_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return files, durations
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            return files, durations
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "pytest_generate_tests", "pytest_collect_file",
            "pytest_pycollect_makeitem", "pytest_collection_modifyitems",
            "load_tests",
        }:
            return files, durations
    functions = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    if len(functions) < 2 or len(functions) != len(set(functions)):
        return files, durations
    items = [f"{SPLIT_FILE}::{name}" for name in functions]
    estimates = dict(durations)
    estimates.update({
        item: durations.get(item, durations.get(SPLIT_FILE, UNKNOWN_SECONDS) / len(items))
        for item in items
    })
    return sorted([rel for rel in files if rel != SPLIT_FILE] + items), estimates


def partition(files: list[str], durations: dict[str, float], count: int) -> list[list[str]]:
    """Largest-processing-time-first; each selector goes into exactly one job."""
    if count < 1:
        raise ValueError("Shard count must be positive")
    if len(set(files)) != len(files) or len(files) < count:
        raise ValueError("Expected unique test files and at least one per shard")
    groups: list[list[str]] = [[] for _ in range(count)]
    loads = [0.0] * count
    for rel in sorted(files, key=lambda name: (-durations.get(name, UNKNOWN_SECONDS), name)):
        shard = min(range(count), key=lambda idx: (loads[idx], idx))
        groups[shard].append(rel)
        loads[shard] += durations.get(rel, UNKNOWN_SECONDS)
    # Keep the output deterministic for review and for each matrix job.
    return [sorted(group) for group in groups]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    if not 0 <= args.shard < args.shards:
        parser.error("Shard must be between zero and shards-1")
    repo = args.repo.resolve()
    files = test_files(repo)
    durations = read_durations()
    items, estimates = expanded_test_items(repo, files, durations)
    groups = partition(items, estimates, args.shards)
    assigned = [rel for group in groups for rel in group]
    if (sorted(assigned) != items or not groups[args.shard]
            or sorted({rel.split("::", 1)[0] for rel in assigned}) != files):
        raise RuntimeError("Full-suite shards must cover every test file and function exactly once")
    selected = groups[args.shard]
    estimate = sum(estimates.get(rel, UNKNOWN_SECONDS) for rel in selected)
    args.out.write_text("".join(f"{rel}\n" for rel in selected), encoding="utf-8")
    print(f"[ci_full_test_shards] shard={args.shard + 1}/{args.shards} "
          f"items={len(selected)}/{len(items)} test_files={len(files)} estimated_minutes={estimate / 60:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
