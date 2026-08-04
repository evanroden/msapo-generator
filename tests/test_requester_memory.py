import sqlite3

from app.memory import (
    REQUESTER_SUGGEST_THRESHOLD,
    forget_device_requester,
    record_device_requester,
    remembered_device_requester,
)


def test_requester_is_remembered_after_three_distinct_po_contexts(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    for index in range(1, REQUESTER_SUGGEST_THRESHOLD):
        count = record_device_requester(
            device_token="browser-a",
            requester_name="  Evan   Roden  ",
            context_id=f"po-{index}",
        )
        assert count == index
        assert remembered_device_requester("browser-a") == ""

    count = record_device_requester(
        device_token="browser-a",
        requester_name="Evan Roden",
        context_id="po-3",
    )

    assert count == REQUESTER_SUGGEST_THRESHOLD
    assert remembered_device_requester("browser-a") == "Evan Roden"
    assert remembered_device_requester("browser-b") == ""
    with sqlite3.connect(tmp_path / "epc_memory.db") as conn:
        stored_device = conn.execute(
            "SELECT device_hash FROM device_requesters LIMIT 1"
        ).fetchone()[0]
    assert stored_device != "browser-a"
    assert len(stored_device) == 64


def test_streamlit_reruns_do_not_inflate_requester_count(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    for _ in range(8):
        assert record_device_requester(
            device_token="browser-a",
            requester_name="Evan Roden",
            context_id="same-po",
        ) == 1

    assert remembered_device_requester("browser-a") == ""


def test_correcting_a_requester_moves_the_single_context_use(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    record_device_requester(
        device_token="browser-a",
        requester_name="Wrong Person",
        context_id="po-1",
    )

    assert record_device_requester(
        device_token="browser-a",
        requester_name="Correct Person",
        context_id="po-1",
    ) == 1

    with sqlite3.connect(tmp_path / "epc_memory.db") as conn:
        rows = conn.execute(
            "SELECT display_name, use_count FROM device_requesters"
        ).fetchall()
    assert rows == [("Correct Person", 1)]


def test_forget_only_clears_this_browser_requester_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    for index in range(3):
        record_device_requester(
            device_token="browser-a",
            requester_name="Evan Roden",
            context_id=f"a-{index}",
        )
        record_device_requester(
            device_token="browser-b",
            requester_name="Another Requester",
            context_id=f"b-{index}",
        )

    assert forget_device_requester("browser-a") is True
    assert remembered_device_requester("browser-a") == ""
    assert remembered_device_requester("browser-b") == "Another Requester"


def test_three_uses_let_a_new_primary_user_take_over_the_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    timestamps = iter(range(1, 9))
    monkeypatch.setattr("app.memory.time.time", lambda: next(timestamps))
    for index in range(5):
        record_device_requester(
            device_token="shared-browser",
            requester_name="First Requester",
            context_id=f"first-{index}",
        )
    for index in range(3):
        record_device_requester(
            device_token="shared-browser",
            requester_name="Second Requester",
            context_id=f"second-{index}",
        )

    assert remembered_device_requester("shared-browser") == "Second Requester"


def test_invalid_identity_inputs_do_not_create_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    assert record_device_requester(
        device_token="",
        requester_name="Evan Roden",
        context_id="po-1",
    ) == 0
    assert record_device_requester(
        device_token="browser-a",
        requester_name="",
        context_id="po-1",
    ) == 0
    assert record_device_requester(
        device_token="browser-a",
        requester_name="Evan Roden",
        context_id="",
    ) == 0
    assert not (tmp_path / "epc_memory.db").exists()
