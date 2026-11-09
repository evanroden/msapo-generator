"""A browser journal's retained fingerprint must bind its actual saved draft.

These cases use only synthetic data, browser IDs and temporary files. A
corrupted active journal is recoverable but must not replace last-good work.
"""
from dataclasses import replace

import pytest

from app import monthly_report_active_work as active
from app import monthly_report_library as library
from test_monthly_report_active_work import DEVICE_A, DEVICE_B, make_draft


@pytest.fixture
def current(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = replace(make_draft(), prepared_by="Synthetic editor")
    first = active.save(DEVICE_A, draft, expected_revision=0, base_snapshot_revision=0)
    path = (active._directory(DEVICE_A, draft.profile.contract,
                              draft.profile.key, draft.period) / "working.json")
    return draft, first, path


def _change(path, change):
    value = library._read(path)
    change(value)
    path.write_bytes(library._json(value))
    return path.read_bytes()


def _loaded(draft):
    return active.load(DEVICE_A, draft.profile.contract,
                       draft.profile.key, draft.period)


def _save(draft, expected_revision=1):
    return active.save(DEVICE_A, draft, expected_revision=expected_revision,
                       base_snapshot_revision=0)


def test_valid_journal_roundtrip_and_exact_noop_still_work(current):
    draft, first, path = current
    before = path.read_bytes()
    recovered = _loaded(draft)
    assert recovered.draft == draft and recovered.revision == first.revision
    assert recovered.updated_at == first.updated_at
    assert _save(draft) == first
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad", [
    pytest.param(None, id="null"),
    pytest.param("", id="empty"),
    pytest.param("0" * 64, id="wrong-digest"),
    pytest.param(123, id="number"),
    pytest.param(True, id="boolean"),
    pytest.param({"value": "changed"}, id="object"),
    pytest.param(["changed"], id="array"),
])
def test_bad_saved_fingerprint_does_not_reopen_as_valid_work(current, bad):
    draft, first, path = current
    damaged = _change(path, lambda value: value.__setitem__("fingerprint", bad))
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _loaded(draft)
    assert path.read_bytes() == damaged
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


@pytest.mark.parametrize("field,new", [
    pytest.param("prepared_by", "Different synthetic author", id="prepared-by"),
    pytest.param("address_line", "Different synthetic address", id="address"),
    pytest.param("blocks", [{"key": "activity_summary", "source": "This month",
                            "text": "Different synthetic completion claim."}], id="blocks"),
])
def test_modified_saved_draft_cannot_inherit_the_old_fingerprint(current, field, new):
    draft, first, path = current
    _change(path, lambda value: value["draft"].__setitem__(field, new))
    damaged = path.read_bytes()
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _loaded(draft)
    assert path.read_bytes() == damaged
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_false_noop_acknowledgment_is_refused_without_advancing_journal(current):
    draft, first, path = current
    _change(path, lambda value: value["draft"].__setitem__(
        "prepared_by", "Unrelated, damaged saved value"))
    damaged = path.read_bytes()
    # Before the repair, the saved fingerprint alone makes this appear to be
    # an unchanged save even though the actual stored draft differs.
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _save(draft)
    assert path.read_bytes() == damaged
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_new_work_cannot_overwrite_a_journal_with_unverified_old_work(current):
    draft, first, path = current
    _change(path, lambda value: value["draft"].__setitem__(
        "prepared_by", "Other unsaved browser work"))
    damaged = path.read_bytes()
    updated = replace(draft, prepared_by="A new synthetic edit")
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _save(updated)
    assert path.read_bytes() == damaged
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_bad_saved_fingerprint_cannot_make_an_exact_noop_look_saved(current):
    draft, first, path = current
    _change(path, lambda value: value.__setitem__("fingerprint", "0" * 64))
    damaged = path.read_bytes()
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _save(draft)
    assert path.read_bytes() == damaged


def test_recovery_after_restoring_original_bytes_keeps_normal_revision_flow(current):
    draft, first, path = current
    original = path.read_bytes()
    _change(path, lambda value: value["draft"].__setitem__(
        "prepared_by", "Corrupted temporary edit"))
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _loaded(draft)
    path.write_bytes(original)
    assert _loaded(draft).draft == draft
    assert _save(draft) == first
    updated = replace(draft, prepared_by="Next reviewed synthetic edit")
    next_saved = _save(updated)
    assert next_saved.revision == first.revision + 1
    assert _loaded(draft).draft == updated


def test_explicit_discard_remains_available_and_does_not_touch_shared_history(current):
    draft, first, path = current
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor="Synthetic reviewer")
    _change(path, lambda value: value["draft"].__setitem__(
        "prepared_by", "Corrupted, discarded browser copy"))
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _loaded(draft)
    generation = active.discard(
        DEVICE_A, draft.profile.contract, draft.profile.key, draft.period,
        expected_revision=first.revision, expected_generation=first.generation)
    assert generation and _loaded(draft) is None
    assert library.load_snapshot(draft.profile.contract, draft.profile.key,
                                 draft.period) == saved


def test_corruption_is_isolated_from_other_browser_and_report(current):
    draft, first, path = current
    assert active.load(DEVICE_B, draft.profile.contract,
                       draft.profile.key, draft.period) is None
    _change(path, lambda value: value["draft"].__setitem__(
        "prepared_by", "Corrupted synthetic draft"))
    with pytest.raises(library.LibraryError, match="fingerprint"):
        _loaded(draft)
    assert active.load(DEVICE_B, draft.profile.contract,
                       draft.profile.key, draft.period) is None
    assert active.load(DEVICE_A, "Different synthetic contract",
                       draft.profile.key, draft.period) is None
    assert active.load(DEVICE_A, draft.profile.contract,
                       "different-profile", draft.period) is None
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_legacy_journal_without_optional_timestamp_keeps_its_content_binding(current):
    draft, first, path = current
    _change(path, lambda value: value.pop("updated_at", None))
    loaded = _loaded(draft)
    assert loaded.draft == draft and loaded.updated_at == ""
    assert _save(draft).revision == first.revision


def test_exact_operation_receipt_replay_is_still_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = replace(make_draft(), prepared_by="Synthetic operation reviewer")
    operation = "c" * 32
    first = active.save(
        DEVICE_A, draft, expected_revision=0, expected_generation="",
        base_snapshot_revision=0, operation_id=operation)
    path = active._directory(DEVICE_A, draft.profile.contract,
                             draft.profile.key, draft.period) / "working.json"
    before = path.read_bytes()
    replay = active.save(
        DEVICE_A, draft, expected_revision=0, expected_generation="",
        base_snapshot_revision=0, operation_id=operation)
    assert replay == first and path.read_bytes() == before
    _change(path, lambda value: value["draft"].__setitem__(
        "prepared_by", "Different synthetic hidden value"))
    damaged = path.read_bytes()
    with pytest.raises(library.LibraryError, match="fingerprint"):
        active.save(
            DEVICE_A, draft, expected_revision=0, expected_generation="",
            base_snapshot_revision=0, operation_id=operation)
    assert path.read_bytes() == damaged
