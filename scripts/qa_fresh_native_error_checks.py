"""Strict primary-document native error observation for the fresh fixture only."""
SCHEMA = "enfra-fresh-native-errors-v1"
ORIGIN = "http://127.0.0.1:8529"
LIMIT = 16


def capture_native_window_errors(page, record, stage):
    """Keep a failed read as evidence without replacing the primary task error."""
    snapshot = {"stage": stage}
    try:
        snapshot["evidence"] = page.evaluate("() => window.__enfraFreshNativeErrors || null")
    except Exception as exc:
        snapshot["capture_error"] = type(exc).__name__ + ": " + str(exc)[:500]
    snapshots = record.setdefault("native_window_errors", [])
    if len(snapshots) < 2:
        snapshots.append(snapshot)
    else:
        # Only first-failure and final are expected. Retain the first evidence
        # and latest final read, but never let an unexpected third capture pass.
        snapshot["capture_overflow"] = snapshots[-1].get("capture_overflow", 0) + 1
        snapshots[-1] = snapshot
    return snapshot


def require_no_native_window_errors(snapshots, *, origin=ORIGIN):
    """Every observed native error fails, including missed Playwright pageerrors."""
    assert isinstance(snapshots, list) and 1 <= len(snapshots) <= 2, "Missing or excessive native error snapshots."
    assert all(isinstance(snapshot, dict) for snapshot in snapshots), "Invalid native error snapshot."
    assert snapshots[-1].get("stage") == "final", "A final native error snapshot is required."
    for snapshot in snapshots:
        assert not snapshot.get("capture_overflow"), "Native error snapshot limit was exceeded."
        assert not snapshot.get("capture_error"), "Native error capture failed: " + str(snapshot)
        value = snapshot.get("evidence")
        assert isinstance(value, dict), "Native error collector is missing."
        assert (value.get("schema") == SCHEMA and value.get("installed") is True
                and value.get("origin") == origin and value.get("limit") == LIMIT), "Native error collector was not installed for this fixture."
        errors, total, overflow = value.get("errors"), value.get("total"), value.get("overflow")
        assert isinstance(errors, list) and len(errors) <= LIMIT, "Invalid native error buffer."
        assert (type(total) is int and total >= 0 and type(overflow) is int and overflow >= 0
                and total == len(errors) + overflow), "Invalid native error counts."
        assert not overflow, "Native error buffer overflowed: " + str(snapshot)
        assert total == 0 and not errors, "Native window errors were observed: " + str(snapshot)
