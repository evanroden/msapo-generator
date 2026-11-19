"""A86: real malformed batch formats cannot erase valid originals or retries.

Fixtures are wholly synthetic and bounded. This integration regression combines
the five actual damaged-byte formats in one batch, then repairs them singly.
It exercises disk originals, extraction caches and explicitly saved history;
it is not a served-browser or authentic-report acceptance test.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from docx import Document
from PIL import Image

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import restore_sources
from test_monthly_report_parser_failure_integrity import (
    FIRST, LAST, corrupted_package, missing_workbook_part, oversized_png_header,
    workbook_bytes,
)
from test_mpo_decoder_failure_integrity import mpo


def _valid_docx():
    document = Document()
    document.add_paragraph("Synthetic inspection of chilled-water pump P-86.")
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _valid_pdf():
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((60, 90), "Synthetic monthly pump inspection completed.")
        return document.tobytes()
    finally:
        document.close()


def _valid_png():
    stream = BytesIO()
    Image.new("RGB", (32, 24), "green").save(stream, format="PNG")
    return stream.getvalue()


def _inventory(profile, contents):
    """Both bytes and disk cache fingerprints must stay unchanged on sibling retry."""
    result = {}
    for content in contents:
        source = content.source
        original = sources.source_bytes(profile, source)
        path = sources._path(profile, source.sha256, source.suffix)
        cache = sources._path(profile, source.sha256, ".json")
        result[source.id] = (
            source, sha256(original).hexdigest(), sha256(cache.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns, cache.stat().st_mtime_ns,
        )
    return result


def test_five_malformed_files_between_good_siblings_recover_independently(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    other_profile = replace(profile, key="a86-independent-site")
    other, _ = sources.ingest(other_profile, "different-site.txt", b"Other-site approved data.")
    original_other = sources.source_bytes(other_profile, other.source)

    broken = (
        ("broken.docx", corrupted_package(".docx"), "Compressed file data is damaged"),
        ("missing.xlsx", missing_workbook_part(), "missing required document data"),
        ("invalid.pdf", b"%PDF-1.7\\nnot a valid PDF document", "PDF"),
        ("bomb.png", oversized_png_header(), "too large to decode safely"),
        ("truncated.mpo", mpo()[:-100], "damaged or truncated"),
    )
    # No fixture allocates the expanded pixel or document budget it represents.
    assert all(0 < len(raw) < 128 * 1024 for _, raw, _ in broken)

    accepted, messages = sources.ingest_batch(
        profile, (("first.txt", FIRST), *((name, raw) for name, raw, _ in broken),
                  ("last.txt", LAST)))
    assert [item.source.filename for item in accepted] == ["first.txt", "last.txt"]
    assert len(messages) == len(broken)
    for name, raw, expected in broken:
        matching = [message for message in messages if message.startswith(f"Not read: {name}.")]
        assert len(matching) == 1 and expected in matching[0]
        assert "Storage or file reader was unavailable" not in matching[0]
        assert not sources._path(profile, sha256(raw).hexdigest(), name[name.rfind("."):]).exists()
        assert not sources._path(profile, sha256(raw).hexdigest(), ".json").exists()

    originals = _inventory(profile, accepted)
    assert set(originals) == {sha256(FIRST).hexdigest(), sha256(LAST).hexdigest()}
    assert tuple(sources.source_bytes(profile, x.source) for x in accepted) == (FIRST, LAST)

    period = ReportPeriod(2026, 10)
    initial_draft = replace(synthetic_draft(profile, period),
                            sources=tuple(content.source for content in accepted))
    first_save = library.save_snapshot(initial_draft, expected_revision=0,
                                       entered_editor="Synthetic A86 reviewer")
    assert library.load_snapshot(profile.contract, profile.key, period) == first_save

    repaired = (
        ("broken.docx", _valid_docx()),
        ("missing.xlsx", workbook_bytes()),
        ("invalid.pdf", _valid_pdf()),
        ("bomb.png", _valid_png()),
        ("truncated.mpo", mpo()),
    )
    for filename, raw in repaired:
        before = tuple(accepted)
        before_inventory = _inventory(profile, before)
        accepted, retry_messages = sources.ingest_batch(profile, ((filename, raw),), before)
        assert not retry_messages
        assert len(accepted) == len(before) + 1
        assert accepted[:len(before)] == before
        assert accepted[-1].source.filename == filename
        assert accepted[-1].source.sha256 == sha256(raw).hexdigest()
        assert sources.source_bytes(profile, accepted[-1].source) == raw
        assert {id_: _inventory(profile, accepted)[id_] for id_ in before_inventory} == before_inventory
        # A retry must not implicitly save or replace accepted historical reports.
        assert library.load_snapshot(profile.contract, profile.key, period) == first_save

    assert _inventory(profile, accepted).items() >= originals.items()
    assert sources.source_bytes(other_profile, other.source) == original_other
    saved_draft = replace(initial_draft, sources=tuple(content.source for content in accepted))
    second_save = library.save_snapshot(saved_draft, expected_revision=first_save.revision,
                                        entered_editor="Synthetic A86 reviewer")
    reloaded = library.load_snapshot(profile.contract, profile.key, period)
    assert reloaded == second_save
    assert reloaded.draft.sources[:2] == initial_draft.sources
    assert {source.sha256 for source in reloaded.draft.sources} == {
        sha256(raw).hexdigest() for raw in (FIRST, LAST, *(raw for _, raw in repaired))
    }
    restored, unavailable = restore_sources(profile, reloaded.draft.sources)
    assert not unavailable
    assert {item.source.sha256 for item in restored} == {
        item.source.sha256 for item in accepted
    }
    assert tuple(sources.source_bytes(profile, item.source) for item in restored) == (
        FIRST, LAST, *(raw for _, raw in repaired)
    )
