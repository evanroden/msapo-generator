import hashlib
import os

import pytest

from app import monthly_report_library as library
from app.monthly_report_objects import object_path, store_file, consolidate_existing
from app.monthly_report_storage import storage_summary


def locations(tmp_path, raw):
    name = hashlib.sha256(raw).hexdigest() + ".png"
    root = tmp_path / "monthly_reports"
    return root / "library" / "contract-a" / "site-a" / "assets" / name, root / "library" / "contract-b" / "site-b" / "assets" / name


def test_assets_share_bytes_across_contracts_and_replacement_keeps_old_versions(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = b"synthetic immutable asset"
    first, second = locations(tmp_path, raw)
    library._atomic_write(first, raw)
    library._atomic_write(second, raw)
    assert os.path.samefile(first, second) and os.path.samefile(first, object_path(first))
    assert storage_summary()["monthly"] == len(raw)
    new = b"synthetic replacement"
    replacement, _ = locations(tmp_path, new)
    library._atomic_write(replacement, new)
    assert first.read_bytes() == second.read_bytes() == raw
    assert replacement.read_bytes() == new
    assert storage_summary()["monthly"] == len(raw) + len(new)
    with pytest.raises(library.LibraryError):
        library._atomic_write(first, b"wrong bytes")
    assert second.read_bytes() == raw


def test_streamed_originals_preserve_input_and_cross_site_deduplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = tmp_path / "supplied.docx"
    original.write_bytes(b"synthetic original" * 10000)
    mode = original.stat().st_mode
    first, second = locations(tmp_path, original.read_bytes())
    first, second = first.with_suffix(".docx"), second.with_suffix(".docx")
    store_file(first, original)
    store_file(second, original)
    assert os.path.samefile(first, second)
    assert not os.path.samefile(first, original)
    assert original.stat().st_mode == mode
    assert original.read_bytes() == first.read_bytes()


def test_consolidation_is_repeatable_bounded_and_keeps_history(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = b"legacy synthetic asset"
    first, second = locations(tmp_path, raw)
    for path in (first, second):
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
    history = first.parent.parent / "history.json"
    history.write_bytes(b'{"reference":"unchanged"}')
    result = consolidate_existing(max_files=1)
    assert result["changed"] == 1 and not result["complete"]
    result = consolidate_existing()
    assert result["changed"] == 1 and result["reclaimed"] == len(raw)
    assert os.path.samefile(first, second)
    assert consolidate_existing()["changed"] == 0
    assert history.read_bytes() == b'{"reference":"unchanged"}'


def test_failed_link_keeps_existing_path_and_retry_is_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = b"synthetic existing"
    first, _ = locations(tmp_path, raw)
    first.parent.mkdir(parents=True)
    first.write_bytes(raw)
    real = os.link
    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("simulated link failure")))
    with pytest.raises(OSError):
        store_file(first, first)
    assert first.read_bytes() == raw
    assert not list(first.parent.glob(".pending-*"))
    monkeypatch.setattr(os, "link", real)
    store_file(first, first)
    assert os.path.samefile(first, object_path(first))


def test_concurrent_contract_writes_publish_one_verified_object(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = b"shared concurrent synthetic asset" * 1000
    first, _ = locations(tmp_path, raw)
    paths = [first.parent.parent / str(n) / first.name for n in range(8)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda path: library._atomic_write(path, raw), paths))
    assert all(os.path.samefile(path, paths[0]) for path in paths)
    assert paths[0].read_bytes() == raw
    assert not list((tmp_path / "monthly_reports").rglob(".pending-*"))
