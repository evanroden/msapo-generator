"""Synthetic boundary checks for owner-scoped native DOCX preview reuse."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import monthly_report_designs as designs
from app import monthly_report_native_layout as native
from app import monthly_report_preview as preview
from app import monthly_report_render_jobs as jobs
from app import monthly_report_section_assembly_cache as cache
from app import monthly_report_source_view_runtime as source_runtime
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    cache.clear()
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 512 * 1024 * 1024)
    monkeypatch.setattr(source_runtime, "cache_identity", lambda draft: "source-view-one")
    monkeypatch.setattr(preview, "preflight", lambda scope: [])
    monkeypatch.setattr(designs, "source_for", lambda profile: Path("verified-synthetic-native.docx"))
    monkeypatch.setattr(designs, "is_master", lambda profile: False)
    yield
    cache.clear()


@pytest.fixture
def report():
    return synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))


@pytest.fixture
def writer(monkeypatch):
    calls = []

    def write(draft, source, *, asset_loader, section_key, master, source_view):
        calls.append((draft.fingerprint, section_key, source))
        return b"synthetic-fixed-native-docx"

    monkeypatch.setattr(native, "build_native_docx", write)
    return calls


def assemble(report):
    return preview._section_preview_docx(report, "activity")


def test_same_owner_revision_reuses_identical_native_bytes(report, writer):
    with cache.owner_scope("visitor-a"):
        first = assemble(report)
        second = assemble(report)
    assert first == second == b"synthetic-fixed-native-docx"
    assert len(writer) == 1


def test_without_owner_always_assembles_fresh(report, writer):
    assemble(report)
    assemble(report)
    assert len(writer) == 2


def test_one_visitors_bytes_never_cross_another_owner(report, writer):
    with cache.owner_scope("visitor-a"):
        assemble(report)
    with cache.owner_scope("visitor-b"):
        assemble(report)
    assert len(writer) == 2


def test_unsaved_asset_bytes_change_invalidates_same_revision(report, writer):
    with cache.owner_scope("visitor-a", (("picture.png", b"first-digest"),)):
        assemble(report)
        assemble(report)
    with cache.owner_scope("visitor-a", (("picture.png", b"new-digest"),)):
        assemble(report)
    assert len(writer) == 2


def test_full_draft_revision_change_invalidates(report, writer):
    with cache.owner_scope("visitor-a"):
        assemble(report)
        assemble(replace(report, prepared_by="Changed synthetic editor"))
    assert len(writer) == 2


def test_source_view_revision_change_invalidates(report, writer, monkeypatch):
    with cache.owner_scope("visitor-a"):
        assemble(report)
        monkeypatch.setattr(source_runtime, "cache_identity", lambda draft: "source-view-two")
        assemble(report)
    assert len(writer) == 2


def test_preflight_and_pinned_source_validation_still_run_on_hit(report, writer, monkeypatch):
    with cache.owner_scope("visitor-a"):
        assemble(report)
        monkeypatch.setattr(
            preview, "preflight",
            lambda scope: [SimpleNamespace(blocking=True, code="invalid-source", message="Invalid synthetic source.")],
        )
        with pytest.raises(ValueError, match="Invalid synthetic source"):
            assemble(report)
        monkeypatch.setattr(preview, "preflight", lambda scope: [])
        monkeypatch.setattr(designs, "source_for",
                            lambda profile: (_ for _ in ()).throw(ValueError("Source changed")))
        with pytest.raises(ValueError, match="Source changed"):
            assemble(report)
    assert len(writer) == 1


def test_failed_assembly_is_not_cached(report, writer, monkeypatch):
    original = native.build_native_docx
    calls = [0]

    def fail_once(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            raise ValueError("Synthetic renderer failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(native, "build_native_docx", fail_once)
    with cache.owner_scope("visitor-a"):
        with pytest.raises(ValueError, match="renderer failure"):
            assemble(report)
        assert assemble(report) == b"synthetic-fixed-native-docx"
    assert calls[0] == 2 and len(writer) == 1


def test_expiry_and_single_entry_budget(report, writer, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache, "monotonic", lambda: now[0])
    with cache.owner_scope("visitor-a"):
        assemble(report)
        now[0] += cache.TTL_SECONDS + 1
        assemble(report)
    assert len(writer) == 2
    cache.clear()
    with cache.owner_scope("visitor-a"):
        assert cache.read(("revision",)) is None
        cache.remember(("revision",), b"x" * (cache.MAX_ENTRY_BYTES + 1))
        assert cache.read(("revision",)) is None


def test_memory_pressure_disables_reuse_without_changing_output(report, writer, monkeypatch):
    monkeypatch.setattr(jobs, "memory_headroom", lambda: jobs.PREVIEW_HEADROOM_BYTES)
    with cache.owner_scope("visitor-a"):
        first = assemble(report)
        second = assemble(report)
    assert first == second
    assert len(writer) == 2


def test_owner_context_does_not_leak_after_failure(report, writer):
    with pytest.raises(RuntimeError, match="synthetic"):
        with cache.owner_scope("visitor-a"):
            assemble(report)
            raise RuntimeError("synthetic")
    assert not cache.active()
    assemble(report)
    assert len(writer) == 2
