"""Partition every pytest test file across independent main-push CI jobs.

Durations are from the 14,436-test full run on main 5526fd2b (run
43742773280). The 120 slowest files account for 84.5% of measured time;
unknown/new files receive the measured mean for the remaining 834 files.
Each job computes the same deterministic plan from the checkout, so adding
or renaming a test file cannot silently drop it from the full suite.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

DURATIONS = Path(__file__).with_name("ci_test_durations.tsv")
# 934.9 seconds across 834 historical files not explicitly listed.
UNKNOWN_SECONDS = 934.9 / 834


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
        if not rel.startswith("tests/test_") or not rel.endswith(".py") or not math.isfinite(duration) or duration <= 0 or rel in durations:
            raise ValueError(f"Invalid or duplicated test duration: {rel!r}")
        durations[rel] = duration
    if not durations:
        raise ValueError("No recorded durations supplied")
    return durations


def partition(files: list[str], durations: dict[str, float], count: int) -> list[list[str]]:
    """Largest-processing-time-first; each file goes into exactly one job."""
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
    groups = partition(files, durations, args.shards)
    assigned = [rel for group in groups for rel in group]
    if sorted(assigned) != files or not groups[args.shard]:
        raise RuntimeError("Full-suite shards must cover every test file exactly once")
    selected = groups[args.shard]
    estimate = sum(durations.get(rel, UNKNOWN_SECONDS) for rel in selected)
    args.out.write_text("".join(f"{rel}\n" for rel in selected), encoding="utf-8")
    print(f"[ci_full_test_shards] shard={args.shard + 1}/{args.shards} "
          f"files={len(selected)}/{len(files)} estimated_minutes={estimate / 60:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
