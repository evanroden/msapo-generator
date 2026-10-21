"""Unreadable synthetic directory records must not hide unrelated work."""

from dataclasses import asdict, replace
import json

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory, monthly_report_library as library


@pytest.fixture
def records(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    site = directory.DirectorySite("synthetic-site", "Synthetic Site")
    states = [directory.save_directory(name, (site,), expected_revision=0,
              actor="Synthetic Editor", confirmed=True)
              for name in ("Healthy Contract", "Damaged Contract")]
    path = library._root() / "directory" / library._contract_directory(states[1].contract)
    return states[0], states[1], path


def damage(records, kind):
    _, state, path = records
    value = {"schema": 1, **asdict(state)}
    if kind == "json":
        raw = b'{"schema":1,'
    elif kind == "utf8":
        raw = b"\xff\xfe\x00"
    else:
        if kind == "contract":
            value["contract"] = None
        elif kind == "site":
            value["sites"] = [None]
        elif kind == "revision":
            value["revision"] = "not-a-revision"
        elif kind == "contact":
            value["sites"][0]["contacts"] = [{"role": ["Manager"]}]
        raw = json.dumps(value).encode()
    (path / "manifest.json").write_bytes(raw)
    return raw


@pytest.mark.parametrize("kind", ["json", "utf8", "contract", "site", "revision", "contact"])
def test_bad_record_does_not_break_catalog_or_unrelated_lookup(records, kind):
    healthy, _, path = records
    raw = damage(records, kind)
    assert directory.directory_contracts() == (healthy.contract,)
    assert directory.directory_contracts(include_archived=True) == (healthy.contract,)
    assert directory.load_directory(" HEALTHY   CONTRACT ") == healthy
    assert directory.load_directory("Absent Contract") is None
    assert (path / "manifest.json").read_bytes() == raw


def test_healthy_save_and_reload_preserve_corrupt_sibling_and_history(records):
    healthy, damaged, path = records
    raw = damage(records, "json")
    history = (path / "history" / "00000001.json").read_bytes()
    updated = directory.save_directory(" HEALTHY   CONTRACT ",
        (replace(healthy.sites[0], address="100 Example Way"),), expected_revision=1,
        actor="Synthetic Editor", confirmed=True)
    assert directory.load_directory(healthy.contract) == updated
    assert directory.load_directory(healthy.contract, 1) == healthy
    assert updated.revision == 2
    with pytest.raises(library.RevisionConflict):
        directory.save_directory(healthy.contract, healthy.sites, expected_revision=1,
                                 actor="Synthetic Editor", confirmed=True)
    assert (path / "manifest.json").read_bytes() == raw
    assert (path / "history" / "00000001.json").read_bytes() == history


def test_discovery_cannot_turn_unreadable_legacy_identity_into_a_new_directory(records):
    _, damaged, path = records
    raw = damage(records, "json")
    manifests = set(path.parent.glob("*/manifest.json"))
    # Read-only absence still works; a new shared save cannot prove the name
    # does not belong to the unreadable record under a legacy spelling.
    assert directory.load_directory("Absent Contract") is None
    for name in (" DAMAGED   CONTRACT ", "Absent Contract"):
        with pytest.raises(library.LibraryError):
            directory.save_directory(name, damaged.sites, expected_revision=0,
                                     actor="Synthetic Editor", confirmed=True)
    assert set(path.parent.glob("*/manifest.json")) == manifests
    assert (path / "manifest.json").read_bytes() == raw


def test_directory_scan_does_not_swallow_storage_isolation_failure(records, monkeypatch):
    def fail_guard(path):
        raise library.LibraryError("Test report path is outside its isolated storage")
    monkeypatch.setattr(library, "_qa_path_guard", fail_guard)
    with pytest.raises(library.LibraryError, match="outside its isolated storage"):
        directory.directory_contracts()


@pytest.mark.parametrize("kind", ["json", "contract", "site", "revision", "contact"])
def test_damaged_target_stays_blocked_and_cannot_be_overwritten(records, kind):
    _, damaged, path = records
    raw = damage(records, kind)
    with pytest.raises(library.LibraryError):
        directory.load_directory(damaged.contract)
    with pytest.raises(library.LibraryError):
        directory.save_directory(damaged.contract, damaged.sites, expected_revision=0,
                                 actor="Synthetic Editor", confirmed=True)
    assert (path / "manifest.json").read_bytes() == raw
    assert len(list((path / "history").glob("*.json"))) == 1


DIRECTORY_APP = '''
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
'''


def test_directory_admin_warns_and_keeps_healthy_review_controls(records):
    healthy, _, path = records
    raw = damage(records, "json")
    app = AppTest.from_string(DIRECTORY_APP, default_timeout=30).run()
    assert not app.exception and not app.warning
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    app.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not app.exception
    assert app.selectbox("report_directory_existing").options == [healthy.contract]
    assert any("could not be read" in w.value for w in app.warning)
    assert any(b.label == "Save contract directory" for b in app.button)
    assert any(b.label == "Archive contact list" for b in app.button)
    assert any(b.label == "Restore directory" for b in app.button)
    assert (path / "manifest.json").read_bytes() == raw
    assert directory.load_directory(healthy.contract) == healthy


def test_contract_cards_remain_selectable_with_scoped_warning(records):
    healthy, _, _ = records
    damage(records, "json")
    app = AppTest.from_string('''
from app.monthly_report_start_ui import choose_contract
from app.monthly_report_ui import _field
choose_contract('', _field)
''', default_timeout=30).run()
    assert not app.exception
    assert any("could not be read" in w.value for w in app.warning)
    next(b for b in app.button if b.label == healthy.contract).click().run()
    assert not app.exception
    assert app.session_state["report_contract"] == healthy.contract
    assert any(b.label == "Change contract" for b in app.button)


def test_all_unreadable_records_do_not_claim_no_directory_was_saved(records):
    healthy, _, _ = records
    damage(records, "json")
    path = library._root() / "directory" / library._contract_directory(healthy.contract)
    (path / "manifest.json").write_bytes(b"broken")
    app = AppTest.from_string(DIRECTORY_APP, default_timeout=30).run()
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    app.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not app.exception
    assert any("could not be read" in w.value for w in app.warning)
    assert not any("No directory has been saved" in w.value for w in app.info)
    assert app.radio("report_directory_mode")
