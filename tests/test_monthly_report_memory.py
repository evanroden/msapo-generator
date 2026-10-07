import sqlite3

from app.memory import record_report_preparer, remembered_report_preparer


def test_preparer_memory_is_scoped_and_upserts_without_plain_device_token(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    record_report_preparer("synthetic-browser", "Synthetic Contract", "north", "Synthetic Preparer")
    record_report_preparer("synthetic-browser", "Synthetic Contract", "north", "Synthetic Replacement")
    assert remembered_report_preparer("synthetic-browser", "Synthetic Contract", "north") == "Synthetic Replacement"
    assert not remembered_report_preparer("other-browser", "Synthetic Contract", "north")
    assert not remembered_report_preparer("synthetic-browser", "Other Contract", "north")
    assert not remembered_report_preparer("synthetic-browser", "Synthetic Contract", "south")
    with sqlite3.connect(tmp_path / "epc_memory.db") as connection:
        rows = connection.execute("SELECT device_hash FROM device_report_preparers").fetchall()
        assert len(rows) == 1 and len(rows[0][0]) == 64
        assert rows[0][0] != "synthetic-browser"


def test_additive_preparer_table_preserves_existing_database(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with sqlite3.connect(tmp_path / "epc_memory.db") as connection:
        connection.execute("CREATE TABLE synthetic_legacy (value TEXT)")
        connection.execute("INSERT INTO synthetic_legacy VALUES ('preserved')")
    record_report_preparer("synthetic-browser", "Synthetic Contract", "north", "Synthetic Preparer")
    with sqlite3.connect(tmp_path / "epc_memory.db") as connection:
        assert connection.execute("SELECT value FROM synthetic_legacy").fetchone() == ("preserved",)
    assert remembered_report_preparer("synthetic-browser", "Synthetic Contract", "north") == "Synthetic Preparer"


def test_missing_device_does_not_initialize_database(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    record_report_preparer("", "Synthetic Contract", "north", "Synthetic Preparer")
    assert not remembered_report_preparer("", "Synthetic Contract", "north")
    assert not (tmp_path / "epc_memory.db").exists()
