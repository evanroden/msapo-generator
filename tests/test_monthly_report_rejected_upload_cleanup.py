"""#284 owner decision: delete rejected uploads right away; never touch old or accepted files.

All inputs are small synthetic bytes in an isolated EPC_DATA_DIR.
"""
import hashlib

import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles

GOOD = b"Technician replaced the condenser pump seal on CP-3."
OTHER = b"Technician verified boiler B-2 low-water cutoff."


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def stored(profile):
    folder = sources._path(profile, "0" * 64, ".txt").parent
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def files_for(profile, raw, suffix):
    digest = hashlib.sha256(raw).hexdigest()
    return sources._path(profile, digest, suffix), sources._path(profile, digest, ".json")


def test_unexpected_fault_is_raised_but_its_upload_is_removed(profile, monkeypatch):
    accepted, _ = sources.ingest_batch(profile, (("accepted.txt", GOOD),))
    keep_raw, keep_cache = files_for(profile, GOOD, ".txt")
    assert keep_raw.exists() and keep_cache.exists()

    def programming_fault(*args, **kwargs):
        raise TypeError("synthetic fault after the upload was written")
    monkeypatch.setattr(sources, "suggest_facts", programming_fault)
    with pytest.raises(TypeError, match="synthetic fault"):
        sources.ingest_batch(profile, (("new.txt", OTHER),), existing=accepted)

    new_raw, new_cache = files_for(profile, OTHER, ".txt")
    assert not new_raw.exists() and not new_cache.exists()
    assert keep_raw.read_bytes() == GOOD and keep_cache.exists()
    assert sources.source_bytes(profile, accepted[0].source) == GOOD


def test_text_budget_rejection_removes_the_written_upload(profile, monkeypatch):
    monkeypatch.setattr(sources, "MAX_REPORT_TEXT", len(GOOD) + 5)
    accepted, messages = sources.ingest_batch(profile, (("first.txt", GOOD), ("second.txt", OTHER)))
    assert [c.source.filename for c in accepted] == ["first.txt"]
    assert any("second.txt" in m and "Total extracted text" in m for m in messages)
    new_raw, new_cache = files_for(profile, OTHER, ".txt")
    assert not new_raw.exists() and not new_cache.exists()
    assert files_for(profile, GOOD, ".txt")[0].read_bytes() == GOOD


def test_damaged_pdf_leaves_nothing_behind(profile):
    damaged = b"%PDF-1.7\nthis is not a readable PDF body"
    before = stored(profile)
    accepted, messages = sources.ingest_batch(profile, (("damaged.pdf", damaged), ("good.txt", GOOD)))
    assert [c.source.filename for c in accepted] == ["good.txt"]
    assert any("damaged.pdf" in m and "Not read" in m for m in messages)
    raw, cache = files_for(profile, damaged, ".pdf")
    assert not raw.exists() and not cache.exists()
    assert set(stored(profile)) - set(before) == {p.name for p in files_for(profile, GOOD, ".txt")}


def test_an_older_identical_file_survives_an_unexpected_fault(profile, monkeypatch):
    old_raw, _ = files_for(profile, OTHER, ".txt")
    library._atomic_write(old_raw, OTHER)

    def programming_fault(*args, **kwargs):
        raise TypeError("synthetic fault")
    monkeypatch.setattr(sources, "suggest_facts", programming_fault)
    with pytest.raises(TypeError):
        sources.ingest_batch(profile, (("again.txt", OTHER),))
    assert old_raw.read_bytes() == OTHER  # the older file is kept, not deleted


def test_a_replaced_blob_is_not_deleted_on_rejection(profile, monkeypatch):
    """Only bytes that still match the rejected upload are removed."""
    raw_path, _ = files_for(profile, OTHER, ".txt")
    real_ingest = sources.ingest

    def write_then_swap(profile_, filename, raw):
        real_ingest(profile_, filename, raw)
        library._atomic_write(raw_path, b"different bytes written by another worker")
        raise ValueError("synthetic rejection")
    monkeypatch.setattr(sources, "ingest", write_then_swap)
    _, messages = sources.ingest_batch(profile, (("swapped.txt", OTHER),))
    assert any("synthetic rejection" in m for m in messages)
    assert raw_path.read_bytes() == b"different bytes written by another worker"
