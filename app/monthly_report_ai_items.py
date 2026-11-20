"""Durable, scoped per-page AI request receipts; no Streamlit or API calls.

The budget and claim share one advisory lock so two browser sessions cannot
start the same paid page while its first read is in flight. Only an owning
token can publish the result. "accepted" means model output is validated and
cached, not that its facts have been approved for a report.
"""
from __future__ import annotations

import re
import time
from uuid import uuid4

from app import monthly_report_ai as ai, monthly_report_library as library

_KEY = re.compile(r"[0-9a-f]{64}\Z")


def _paths(profile, period, key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError("Invalid source page request identity.")
    root = library._profile_path(profile.contract, profile.key) / "ai" / "budgets"
    return root, root / (period.key + ".json"), root / (period.key + "-page-" + key + ".json")


def _receipt(path):
    return library._read(path) if path.exists() else {}


def _fresh(record):
    # The network operation has a bounded deadline; an abandoned browser
    # cannot own this page forever. Late completions need their original token.
    return (record.get("status") == "pending"
            and isinstance(record.get("started"), (int, float))
            and 0 <= time.time() - record["started"] < ai.OPERATION_BUDGET_SECONDS + 60)


def status(profile, period, key):
    # Reads of the atomically replaced cache/receipt are safe without a write
    # lock. A routine Streamlit rerun must not create lock files or wait for
    # another session's network claim just to show page progress.
    _, _, path = _paths(profile, period, key)
    if ai.cached(profile, "extraction", key) is not None:
        return "accepted"
    record = _receipt(path)
    if _fresh(record):
        return "pending"
    return "failed" if record else "unread"


def claim(profile, period, key):
    """Return (accepted|pending|claimed, token). Only claimed permits payment."""
    root, budget_path, path = _paths(profile, period, key)
    with library._locked(root):
        if ai.cached(profile, "extraction", key) is not None:
            return "accepted", None
        if _fresh(_receipt(path)):
            return "pending", None
        budget = _receipt(budget_path) or {"schema": 1, "calls": 0}
        if budget["calls"] >= ai.MAX_CALLS:
            raise ValueError(
                "This report/month's 80-request drafting allowance is used. "
                "Cached pages and manual editing remain available."
            )
        token = uuid4().hex
        # Persist receipt before the budget charge. A write failure must never
        # launch a paid call or silently steal another session's pending work.
        library._atomic_write(path, library._json({
            "schema": 1, "status": "pending", "token": token, "started": time.time()
        }))
        library._atomic_write(budget_path, library._json({
            "schema": 1, "calls": budget["calls"] + 1
        }))
        return "claimed", token


def accept(profile, period, key, token, value):
    """Cache and acknowledge together under the claim lock; reject stale work."""
    root, _, path = _paths(profile, period, key)
    with library._locked(root):
        record = _receipt(path)
        if not token or record.get("token") != token or record.get("status") != "pending":
            return False
        ai.save_cache(profile, "extraction", key, value)
        library._atomic_write(path, library._json({
            "schema": 1, "status": "accepted", "token": token,
            "started": record["started"]
        }))
        return True


def fail(profile, period, key, token):
    """A failed page becomes retryable, without touching its successful peers."""
    root, _, path = _paths(profile, period, key)
    with library._locked(root):
        record = _receipt(path)
        if not token or record.get("token") != token or record.get("status") != "pending":
            return False
        library._atomic_write(path, library._json({
            "schema": 1, "status": "failed", "token": token,
            "started": record["started"]
        }))
        return True
