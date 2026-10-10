"""Mixed damaged monthly files are isolated and rejected temporary files cleaned."""
import hashlib
from dataclasses import replace

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles


@pytest.fixture
def scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def test_invalid_image_docx_and_zip_do_not_hide_valid_file_or_leave_new_raw(scoped):
    invalid_png, invalid_docx = b"not an actual image", b"not an OOXML package"
    batch = (("bad.png", invalid_png), ("good.txt", b"Completed synthetic pump inspection."),
             ("bad.docx", invalid_docx), ("broken.zip", b"invalid zip"))
    accepted, messages = sources.ingest_batch(scoped, batch)
    assert len(accepted) == 1 and accepted[0].source.filename == "good.txt"
    assert any("bad.png" in m and "Not read" in m for m in messages)
    assert any("bad.docx" in m and "Not read" in m for m in messages)
    assert any("broken.zip" in m and "Not read" in m for m in messages)
    for raw, suffix in ((invalid_png, ".png"), (invalid_docx, ".docx")):
        path = sources._path(scoped, hashlib.sha256(raw).hexdigest(), suffix)
        assert not path.exists()
    assert sources.source_bytes(scoped, accepted[0].source) == batch[1][1]


def test_missing_saved_source_does_not_block_new_upload_and_keeps_original_metadata(scoped):
    previous, _ = sources.ingest(scoped, "prior.txt", b"Synthetic checked valve.")
    path = sources._path(scoped, previous.source.sha256, previous.source.suffix)
    path.unlink()
    results, messages = sources.ingest_batch(scoped,
        (("new.txt", b"Completed synthetic fan inspection."),), (previous,))
    assert len(results) == 2 and results[0].source == previous.source
    assert any(m.startswith("Saved source unavailable: prior.txt") for m in messages)
    assert sources.source_bytes(scoped, results[1].source) == b"Completed synthetic fan inspection."
    assert not path.exists()  # unrelated upload does not fabricate restoration


def test_exact_reupload_repairs_missing_original_without_rewriting_review(scoped):
    raw = b"Replaced pump filter in a synthetic source."
    accepted, _ = sources.ingest(scoped, "original.txt", raw)
    reviewed = replace(accepted, source=replace(accepted.source, classification="Vendor service",
                                                selected_pages=(1,), vendor="Synthetic Vendor"))
    path = sources._path(scoped, reviewed.source.sha256, reviewed.source.suffix)
    path.unlink()
    restored, messages = sources.ingest_batch(scoped, (("renamed.txt", raw),), (reviewed,))
    assert len(restored) == 1 and restored[0] == reviewed
    assert any("Saved source restored" in message for message in messages)
    assert sources.source_bytes(scoped, reviewed.source) == raw


def test_unknown_email_charset_cannot_fail_other_valid_file(scoped, monkeypatch):
    original = sources._email
    monkeypatch.setattr(sources, "_email", lambda raw: (_ for _ in ()).throw(LookupError("/private/server/path")))
    parsed, messages = sources.ingest_batch(scoped,
        (("invalid.eml", b"From: a@example.invalid\n\nbody"),
         ("valid.txt", b"Inspected test chiller.")))
    assert len(parsed) == 1 and parsed[0].source.filename == "valid.txt"
    assert any("unknown text encoding" in m for m in messages)
    assert not any("/private/" in m for m in messages)
    monkeypatch.setattr(sources, "_email", original)


def test_parser_oserror_is_sanitized_and_does_not_discard_success(scoped, monkeypatch):
    original = sources.ingest
    def wrapped(profile, name, raw):
        if name == "failed.txt":
            raise OSError("/private/server/raw/sensitive")
        return original(profile, name, raw)
    monkeypatch.setattr(sources, "ingest", wrapped)
    accepted, messages = sources.ingest_batch(scoped,
        (("failed.txt", b"fail"), ("good.txt", b"Completed test maintenance.")))
    assert len(accepted) == 1 and accepted[0].source.filename == "good.txt"
    assert any("Storage or file reader was unavailable" in m for m in messages)
    assert not any("/private" in m for m in messages)
