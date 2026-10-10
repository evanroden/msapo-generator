"""A bad saved original must not discard other monthly evidence."""
from dataclasses import replace

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ResolvedBlock, ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import restore_sources, retain_unavailable, used_missing_sources, safe_source_name


def test_one_damaged_source_keeps_unaffected_content_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    good, _ = sources.ingest(profile, "synthetic-good.txt", b"Inspected pump; check result pending.")
    bad, _ = sources.ingest(profile, "synthetic-bad.txt", b"Checked fan vibration.")
    path = sources._path(profile, bad.source.sha256, bad.source.suffix)
    path.write_bytes(b"synthetic different bytes")
    available, missing = restore_sources(profile, (good.source, bad.source))
    assert tuple(c.source for c in available) == (good.source,)
    assert missing == (bad.source,)
    assert retain_unavailable(tuple(c.source for c in available), missing) == (good.source, bad.source)
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    snapshot = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == snapshot


def test_only_output_linked_to_missing_file_must_block():
    profile = synthetic_profiles()[0]
    report = synthetic_draft(profile, ReportPeriod(2026, 9))
    missing = (sources.ReportSource("a" * 64, "missing.txt", "a" * 64, ".txt"),)
    assert used_missing_sources(report, missing) == ()
    block = ResolvedBlock("activity_summary", "This month", text="Approved pump observation",
                          references=("a" * 64 + ":1:source-fingerprint",))
    from app.monthly_report_model import default_sections
    report = replace(report, sections=default_sections(), blocks=(block,))
    assert used_missing_sources(report, missing) == missing
    report = replace(report, blocks=(replace(block, source="Omit"),))
    assert used_missing_sources(report, missing) == ()


def test_replacing_missing_source_identity_does_not_duplicate_metadata():
    missing = sources.ReportSource("b" * 64, "gone.txt", "b" * 64, ".txt")
    assert retain_unavailable((missing,), (missing,)) == (missing,)
    assert retain_unavailable((), (missing,)) == (missing,)
    assert safe_source_name(replace(missing, filename="/private/source.txt")) == "source.txt"
