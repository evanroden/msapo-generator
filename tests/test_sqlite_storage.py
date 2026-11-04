"""SQLite keeps WAL on a local disk and uses its rollback journal on a network share."""
import sqlite3
from pathlib import Path

import pytest

from app import memory
from app.memory import record_device_account_manager, remembered_device_account_manager
from app.sqlite_storage import filesystem_type, journal_mode, on_network_filesystem

# Shaped like /proc/self/mountinfo in a container: an overlay root, an NFS
# share at /test1, a lookalike local path, and a CIFS mount whose name holds a
# space (escaped as \040).
MOUNTINFO = "\n".join([
    "100 1 0:50 / / rw,relatime - overlay overlay rw,lowerdir=/x",
    "101 100 0:51 / /test1 rw,relatime - nfs4 store.example:/share rw,vers=4.1",
    "102 100 8:1 / /test1x rw,relatime - ext4 /dev/sda1 rw",
    r"103 100 0:52 / /mnt/my\040share rw,relatime - cifs //store/share rw",
    "104 101 0:53 / /test1/local rw,relatime shared:9 - tmpfs tmpfs rw",
])


@pytest.mark.parametrize(("path", "kind"), [
    ("/test1/epc_memory.db", "nfs4"),
    ("/test1", "nfs4"),
    ("/test1x/epc_memory.db", "ext4"),  # a prefix is not a parent folder
    ("/test1/local/epc_memory.db", "tmpfs"),  # the deepest mount wins
    ("/mnt/my share/epc_memory.db", "cifs"),
    ("/app/data_store/epc_memory.db", "overlay"),
])
def test_the_mount_holding_the_file_decides_its_filesystem(path, kind):
    assert filesystem_type(Path(path), MOUNTINFO) == kind


def test_network_shares_use_the_rollback_journal_and_local_disks_keep_wal(monkeypatch):
    monkeypatch.delenv("EPC_SQLITE_JOURNAL_MODE", raising=False)
    assert on_network_filesystem(Path("/test1/epc_memory.db"), MOUNTINFO)
    assert on_network_filesystem(Path("/mnt/my share/x.db"), MOUNTINFO)
    assert journal_mode(Path("/test1/epc_memory.db"), MOUNTINFO) == "DELETE"
    assert journal_mode(Path("/test1x/epc_memory.db"), MOUNTINFO) == "WAL"
    assert journal_mode(Path("/app/data_store/epc_memory.db"), MOUNTINFO) == "WAL"
    # Unreadable mount information is treated as a local disk (Render today).
    assert journal_mode(Path("/test1/epc_memory.db"), "") == "WAL"


@pytest.mark.parametrize(("setting", "expected_nfs", "expected_local"), [
    ("delete", "DELETE", "DELETE"), ("WAL", "WAL", "WAL"), ("", "DELETE", "WAL"), ("truncate", "DELETE", "WAL"),
])
def test_the_deployment_setting_overrides_detection_only_with_a_known_mode(
        monkeypatch, setting, expected_nfs, expected_local):
    monkeypatch.setenv("EPC_SQLITE_JOURNAL_MODE", setting)
    assert journal_mode(Path("/test1/epc_memory.db"), MOUNTINFO) == expected_nfs
    assert journal_mode(Path("/app/data_store/epc_memory.db"), MOUNTINFO) == expected_local


def _journal(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()  # an open reader would itself block leaving WAL


def _remember(device):
    record_device_account_manager(device_token=device, account="ENFRA RRH",
                                  manager_name="Synthetic Manager", context_id="po-" + device)


def test_the_learning_database_follows_the_storage_it_lives_on(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "_INITIALIZED_DATABASES", {})
    monkeypatch.delenv("EPC_SQLITE_JOURNAL_MODE", raising=False)
    _remember("browser-a")
    assert _journal(tmp_path / "epc_memory.db") == "wal"  # unchanged on a local disk

    # The same database moved onto a network share switches to the rollback
    # journal the next time the app initializes it, keeping its contents.
    monkeypatch.setenv("EPC_SQLITE_JOURNAL_MODE", "delete")
    monkeypatch.setattr(memory, "_INITIALIZED_DATABASES", {})
    _remember("browser-b")
    assert _journal(tmp_path / "epc_memory.db") == "delete"
    assert not (tmp_path / "epc_memory.db-wal").exists()
    assert remembered_device_account_manager("browser-a", "ENFRA RRH") == "Synthetic Manager"
    assert remembered_device_account_manager("browser-b", "ENFRA RRH") == "Synthetic Manager"


def test_a_refused_switch_is_retried_instead_of_remembered(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "_INITIALIZED_DATABASES", {})
    monkeypatch.delenv("EPC_SQLITE_JOURNAL_MODE", raising=False)
    _remember("browser-a")
    monkeypatch.setenv("EPC_SQLITE_JOURNAL_MODE", "delete")
    monkeypatch.setattr(memory, "_INITIALIZED_DATABASES", {})
    # Another open connection (an in-flight request) blocks leaving WAL.
    holder = sqlite3.connect(tmp_path / "epc_memory.db")
    holder.execute("SELECT count(*) FROM device_account_managers").fetchone()
    try:
        _remember("browser-b")
        assert _journal(tmp_path / "epc_memory.db") == "wal"
        assert memory._INITIALIZED_DATABASES == {}
    finally:
        holder.close()
    _remember("browser-c")
    assert _journal(tmp_path / "epc_memory.db") == "delete"
    assert remembered_device_account_manager("browser-b", "ENFRA RRH") == "Synthetic Manager"
