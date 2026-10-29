"""Saved originals keep their real parser suffix when display labels are shortened."""
from dataclasses import replace

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import restore_sources, safe_source_name


CSV = b"Equipment,Observation\nP-001,Inspected pump\nF-002,Checked fan\n"
TXT = b"Synthetic service report\nActions: Completed pump inspection.\n"
LONG_NAME = "synthetic-" + "n" * 122 + ".txt"
UNICODE_NAME = "檢查-équipement-" * 10 + ".TxT"


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def _paths(profile, source):
    return (sources._path(profile, source.sha256, source.suffix),
            sources._path(profile, source.sha256, ".json"))


@pytest.mark.parametrize("stored_name,warm", [
    pytest.param("a" * 116 + ".txt", True, id="120-character-boundary"),
    pytest.param("a" * 117 + ".txt", True, id="121-character-boundary"),
    pytest.param(UNICODE_NAME, True, id="unicode-mixed-case-warm"),
    pytest.param(UNICODE_NAME, False, id="unicode-mixed-case-uncached"),
    pytest.param("/private/synthetic/" + LONG_NAME, True, id="posix-warm"),
    pytest.param("/private/synthetic/" + LONG_NAME, False, id="posix-uncached"),
    pytest.param("C:\\Synthetic\\Uploads\\" + LONG_NAME, True, id="windows-warm"),
    pytest.param("C:\\Synthetic\\Uploads\\" + LONG_NAME, False, id="windows-uncached"),
])
def test_full_saved_filename_restores_with_or_without_cache(profile, monkeypatch, stored_name, warm):
    basename = stored_name.replace("\\", "/").rsplit("/", 1)[-1]
    original, _ = sources.ingest(profile, basename, TXT)
    reviewed = replace(original.source, filename=stored_name)
    path, cache = _paths(profile, reviewed)
    original_stat, cache_bytes = path.stat(), cache.read_bytes()
    if warm:
        monkeypatch.setattr(sources, "suggest_facts", lambda *args: pytest.fail("healthy extraction cache was reparsed"))
    else:
        cache.unlink()

    restored, missing = restore_sources(profile, (reviewed,))

    assert missing == ()
    assert restored == (replace(original, source=reviewed),)
    assert sources.source_bytes(profile, reviewed) == TXT
    assert library._read(cache)["source"]["suffix"] == ".txt"
    if warm:
        assert cache.read_bytes() == cache_bytes
        assert (path.stat().st_ino, path.stat().st_mtime_ns) == (original_stat.st_ino, original_stat.st_mtime_ns)
    assert safe_source_name(reviewed) == basename[:120]


@pytest.mark.parametrize("actual_suffix,inner_suffix", [(".csv", ".txt"), (".txt", ".csv")])
def test_inner_extension_cannot_change_extracted_content(profile, actual_suffix, inner_suffix):
    filename = "a" * 116 + inner_suffix + "-service" + actual_suffix
    original, _ = sources.ingest(profile, filename, CSV)
    path, cache = _paths(profile, original.source)
    cache_bytes = cache.read_bytes()
    original_files = set(path.parent.iterdir())
    assert safe_source_name(original.source).endswith(inner_suffix)
    assert bool(original.tables) == (actual_suffix == ".csv")

    restored, missing = restore_sources(profile, (original.source,))

    assert missing == ()
    assert restored == (original,)
    assert library._read(cache)["source"]["suffix"] == actual_suffix
    assert cache.read_bytes() == cache_bytes
    assert set(path.parent.iterdir()) == original_files
    assert sources.source_bytes(profile, original.source) == CSV


@pytest.mark.parametrize("actual_suffix,inner_suffix", [(".csv", ".txt"), (".txt", ".csv")])
def test_prior_wrong_route_cache_is_repaired_without_deleting_extra_original(profile, monkeypatch, actual_suffix, inner_suffix):
    filename = "b" * 116 + inner_suffix + "-retained" + actual_suffix
    original, _ = sources.ingest(profile, filename, CSV)
    path, cache = _paths(profile, original.source)
    # Reproduce the previous restore call with the real reader and parser.
    wrong, _ = sources.ingest(profile, safe_source_name(original.source), sources.source_bytes(profile, original.source))
    wrong_path = sources._path(profile, original.source.sha256, inner_suffix)
    assert wrong.source.suffix == inner_suffix and wrong.tables != original.tables
    assert library._read(cache)["source"]["suffix"] == inner_suffix
    assert wrong_path.read_bytes() == CSV
    original_files = set(path.parent.iterdir())

    restored, missing = restore_sources(profile, (original.source,))

    assert missing == () and restored == (original,)
    assert library._read(cache)["source"]["suffix"] == actual_suffix
    assert set(path.parent.iterdir()) == original_files
    assert sources.source_bytes(profile, original.source) == CSV
    assert wrong_path.read_bytes() == CSV
    cache_bytes = cache.read_bytes()
    monkeypatch.setattr(sources, "suggest_facts", lambda *args: pytest.fail("corrected route reparsed its cache"))
    assert restore_sources(profile, (original.source,)) == ((original,), ())
    assert cache.read_bytes() == cache_bytes


def test_reviewed_fields_deliberate_blanks_and_two_saved_versions_stay_exact(profile):
    original, _ = sources.ingest(profile, "c" * 126 + ".csv", CSV)
    sibling, _ = sources.ingest(profile, "sibling.txt", TXT)
    reviewed = replace(original.source, vendor="Reviewed vendor", service_date="2026-09-17",
                       actions="", findings="Human observation", selected_pages=(),
                       captions=((1, "Reviewed caption"),), scope_review="saved-review-receipt")
    first = replace(synthetic_draft(profile, ReportPeriod(2026, 9)), sources=(reviewed, sibling.source))
    saved_first = library.save_snapshot(first, expected_revision=0, entered_editor="Synthetic Editor")
    latest_review = replace(reviewed, findings="", recommendations="Explicit second-version recommendation")
    second = replace(first, sources=(latest_review, sibling.source))
    saved_second = library.save_snapshot(second, expected_revision=1, entered_editor="Synthetic Editor")
    snapshots = library._profile_path(profile.contract, profile.key, snapshots=True)
    history_bytes = {path: path.read_bytes() for path in snapshots.rglob("*.json")}
    source_bytes = {path: path.read_bytes() for source in second.sources for path in _paths(profile, source)}

    restored, missing = restore_sources(profile, saved_second.draft.sources)

    assert missing == ()
    assert restored == (replace(original, source=latest_review), sibling)
    assert library.load_snapshot(profile.contract, profile.key, first.period) == saved_second
    assert library.load_snapshot_version(profile.contract, profile.key, first.period, 1) == saved_first
    assert library.load_snapshot_version(profile.contract, profile.key, first.period, 2) == saved_second
    assert {path: path.read_bytes() for path in snapshots.rglob("*.json")} == history_bytes
    assert {path: path.read_bytes() for path in source_bytes} == source_bytes


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_unavailable_original_still_fails_without_hiding_long_named_sibling(profile, damage):
    bad, _ = sources.ingest(profile, "unavailable.txt", TXT)
    good, _ = sources.ingest(profile, "d" * 126 + ".csv", CSV)
    bad_path, bad_cache = _paths(profile, bad.source)
    cache_bytes = bad_cache.read_bytes()
    if damage == "changed":
        bad_path.write_bytes(b"Different original bytes")
    else:
        bad_path.unlink()

    restored, missing = restore_sources(profile, (bad.source, good.source))

    assert restored == (good,) and missing == (bad.source,)
    assert sources.source_bytes(profile, good.source) == CSV
    assert bad_cache.read_bytes() == cache_bytes
    if damage == "changed":
        assert bad_path.read_bytes() == b"Different original bytes"
    else:
        assert not bad_path.exists()
