"""A repaired original occupies one source's bytes, preserving accepted reviews."""
from dataclasses import replace
import os
from pathlib import Path
import tempfile

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles

ORIGINAL = b"Old data.\n"
NEW = b"New data.\n"


def _temporary_atomic_write(path, raw):
    """Supply persistence only; batch, parser and integrity checks remain real."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


@pytest.fixture
def seam(monkeypatch, tmp_path):
    # The normal storage path imports Linux fcntl. Keep this narrow accounting
    # suite portable without replacing locks or the actual source-byte reader.
    # A separate public-storage case below uses all original persistence code.
    monkeypatch.setattr(sources, "_path", lambda profile, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", _temporary_atomic_write)
    monkeypatch.setattr(sources, "MAX_REPORT_BYTES", len(ORIGINAL) + len(NEW))
    return synthetic_profiles()[0]


def _prepared(profile):
    initial, _ = sources.ingest(profile, "old.txt", ORIGINAL)
    return replace(initial, source=replace(initial.source, vendor="Synthetic saved review",
                                          actions="User's preserved action", selected_pages=(1,)))


@pytest.mark.parametrize("corrupt", [b"X" * 10, b"X" * 3, b"X" * 27],
                         ids=["same_size", "truncated", "oversized"])
def test_repair_counts_only_restored_original_bytes(seam, corrupt):
    reviewed = _prepared(seam)
    path = sources._path(seam, reviewed.source.sha256, reviewed.source.suffix)
    path.write_bytes(corrupt)
    result, messages = sources.ingest_batch(seam, (("reupload.txt", ORIGINAL), ("new.txt", NEW)), (reviewed,))
    assert result[0] == reviewed
    assert sources.source_bytes(seam, reviewed.source) == ORIGINAL
    assert any("Saved source restored" in message for message in messages)
    assert len(result) == 2, messages
    assert sources.source_bytes(seam, result[1].source) == NEW


@pytest.mark.parametrize("missing", [False, True], ids=["intact", "missing"])
def test_intact_and_missing_original_controls(seam, missing):
    reviewed = _prepared(seam)
    if missing:
        sources._path(seam, reviewed.source.sha256, reviewed.source.suffix).unlink()
    result, messages = sources.ingest_batch(seam, (("reupload.txt", ORIGINAL), ("new.txt", NEW)), (reviewed,))
    assert len(result) == 2, messages
    assert result[0] == reviewed
    assert sources.source_bytes(seam, result[0].source) == ORIGINAL
    assert sources.source_bytes(seam, result[1].source) == NEW


@pytest.mark.parametrize("damaged", [False, True])
def test_true_budget_overflow_still_refuses_later_file(seam, damaged):
    reviewed = _prepared(seam)
    if damaged:
        sources._path(seam, reviewed.source.sha256, reviewed.source.suffix).write_bytes(b"X" * 3)
    result, messages = sources.ingest_batch(seam, (("reupload.txt", ORIGINAL), ("new.txt", NEW + b"x")), (reviewed,))
    assert result == (reviewed,)
    assert sources.source_bytes(seam, reviewed.source) == ORIGINAL
    assert any("Not read: new.txt. Report limit" in message for message in messages)


@pytest.mark.parametrize("overflow", [False, True])
def test_failed_repair_retains_existing_accounting_and_review(seam, monkeypatch, overflow):
    reviewed = _prepared(seam)
    path = sources._path(seam, reviewed.source.sha256, reviewed.source.suffix)
    corrupt = b"X" * len(ORIGINAL)
    path.write_bytes(corrupt)

    def fail_original_write(target, raw):
        if target == path:
            raise OSError("Synthetic write failure")
        _temporary_atomic_write(target, raw)

    monkeypatch.setattr(library, "_atomic_write", fail_original_write)
    incoming = NEW + (b"x" if overflow else b"")
    result, messages = sources.ingest_batch(seam, (("reupload.txt", ORIGINAL), ("new.txt", incoming)), (reviewed,))
    assert len(result) == (1 if overflow else 2), messages
    assert result[0] == reviewed
    assert path.read_bytes() == corrupt
    assert any("Could not restore saved source" in message for message in messages)
    assert not any("Saved source restored" in message for message in messages)
    with pytest.raises(ValueError, match="integrity"):
        sources.source_bytes(seam, reviewed.source)
    if not overflow:
        assert sources.source_bytes(seam, result[1].source) == incoming


@pytest.mark.parametrize("missing", [False, True])
def test_repeated_reupload_does_not_add_source_or_bytes_again(seam, missing):
    reviewed = _prepared(seam)
    path = sources._path(seam, reviewed.source.sha256, reviewed.source.suffix)
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"X" * len(ORIGINAL))
    result, messages = sources.ingest_batch(seam,
        (("first.txt", ORIGINAL), ("second.txt", ORIGINAL), ("new.txt", NEW)), (reviewed,))
    assert len(result) == 2, messages
    assert result[0] == reviewed
    assert sum("Saved source restored" in message for message in messages) == 1
    assert "Duplicate skipped: second.txt" in messages
    assert sources.source_bytes(seam, result[0].source) == ORIGINAL
    assert sources.source_bytes(seam, result[1].source) == NEW


def test_other_accepted_sources_keep_their_budget_and_metadata(seam, monkeypatch):
    reviewed = _prepared(seam)
    sibling_raw = b"Sibling.\n"
    sibling, _ = sources.ingest(seam, "sibling.txt", sibling_raw)
    monkeypatch.setattr(sources, "MAX_REPORT_BYTES", len(ORIGINAL) + len(sibling_raw) + len(NEW))
    sources._path(seam, reviewed.source.sha256, reviewed.source.suffix).write_bytes(b"X" * 3)
    result, messages = sources.ingest_batch(seam, (("reupload.txt", ORIGINAL), ("new.txt", NEW)), (reviewed, sibling))
    assert len(result) == 3, messages
    assert result[:2] == (reviewed, sibling)
    assert sources.source_bytes(seam, sibling.source) == sibling_raw


def test_public_storage_repair_budget_keeps_saved_history(monkeypatch, tmp_path):
    """Enabled Linux integration; no supplied path, writer, guard or locks."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sources, "MAX_REPORT_BYTES", len(ORIGINAL) + len(NEW))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    reviewed = _prepared(profile)
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 9)), sources=(reviewed.source,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    path = sources._path(profile, reviewed.source.sha256, reviewed.source.suffix)
    path.unlink()
    path.write_bytes(b"X" * len(ORIGINAL))
    result, messages = sources.ingest_batch(profile, (("reupload.txt", ORIGINAL), ("new.txt", NEW)), (reviewed,))
    assert result[0] == reviewed
    assert sources.source_bytes(profile, reviewed.source) == ORIGINAL
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
    assert len(result) == 2, messages
