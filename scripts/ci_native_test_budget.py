"""Bound a job's native test commands by one shared monotonic deadline.

Setup is deliberately outside this budget. Every test step uses the same file;
failed steps and intervening artifact uploads cannot reset the original ceiling.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def remaining_budget(path: Path, seconds: int, now: float) -> float:
    if seconds <= 0:
        raise ValueError("Test budget must be positive")
    record = {"seconds": seconds, "deadline": now + seconds}
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(record, handle)
    except FileExistsError:
        record = json.loads(path.read_text(encoding="utf-8"))
    if set(record) != {"seconds", "deadline"} or record["seconds"] != seconds:
        raise ValueError("Native test budget changed within the job")
    deadline = record["deadline"]
    if not isinstance(deadline, (int, float)) or not 0 <= deadline <= now + seconds:
        raise ValueError("Invalid native test deadline")
    return max(0.0, deadline - now)


def run_command(command: str, remaining: float) -> int:
    if remaining <= 0:
        print("Native aggregate test budget exhausted", file=sys.stderr)
        return 124
    process = subprocess.Popen(["bash", "-eo", "pipefail", "-c", command], start_new_session=True)
    try:
        return process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # The shell may exit before a TERM-resistant descendant. Kill the
            # group even when waiting for its leader already returned.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        print("Native aggregate test budget exhausted", file=sys.stderr)
        return 124


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args()
    # RUNNER_TEMP is isolated by GitHub per job. Never silently use a shared cwd.
    path = Path(os.environ["RUNNER_TEMP"]) / "msapo-native-test-budget.json"
    remaining = remaining_budget(path, args.minutes * 60, time.monotonic())
    return run_command(sys.stdin.read(), remaining)


if __name__ == "__main__":
    raise SystemExit(main())
