"""A31: immutable per-section fingerprint reuse; synthetic inputs only.

Run with pytest -q -s tests/test_monthly_report_section_fingerprint_cache.py.
The first test fails on main because unchanged sections are JSON-serialized on
every rerun. The oracle pins the prior hash format, not a new output format.
"""
from dataclasses import asdict, replace
import hashlib
import json
import resource
from time import perf_counter, process_time

import pytest

from app import monthly_report_preview as preview
from app import monthly_report_source_view_runtime as source_runtime
from app.monthly_report_asset_layout import document_page_indexes
from app.monthly_report_designs import fingerprint as design_fingerprint
from app.monthly_report_followups import report_text
from app.monthly_report_model import (
    ReportPeriod, ResolvedBlock, default_sections, included_sections,
    synthetic_draft, synthetic_profiles,
)


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setattr(source_runtime, "cache_identity", lambda draft: "")
    base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    return replace(base, sections=default_sections(), blocks=(
        ResolvedBlock("activity_summary", "This month", text="Synthetic activity"),
        ResolvedBlock("training_summary", "This month", text="Synthetic training"),
        ResolvedBlock("brand_logo", "This month", asset_hashes=("shared-logo-v1.png",)),
    ))


def _legacy_fingerprint(draft, section_key, source_identity=""):
    """Exact main-branch v6 representation: retained as a hash-identity oracle."""
    scope, section = preview._section_scope(draft, section_key)
    blocks = []
    for block in scope.blocks:
        if block.source == "Omit":
            blocks.append({"key": block.key, "source": "Omit"})
            continue
        blocks.append({name: getattr(block, name) for name in (
            "key", "text", "rows", "asset_hashes", "asset_captions",
            "photos_per_page", "references",
        )} | {"org_nodes": [asdict(node) for node in block.org_nodes],
             "extra_tables": [asdict(table) for table in block.extra_tables],
             "document_pages": sorted(document_page_indexes(block, scope.sources))})
    value = {
        "version": 6,
        "period": draft.period.key,
        "title": draft.profile.title,
        "contract": draft.profile.contract,
        "profile": draft.profile.key,
        "section": asdict(section) if section else "cover",
        "blocks": blocks,
        "address": draft.address_line if section else "",
        "follow_ups": [report_text(item) for item in scope.follow_ups if item.included],
        "native_layout": design_fingerprint(draft.profile),
    }
    if source_identity:
        value["source_view"] = source_identity
    if section is None:
        value["cover"] = {
            "title": draft.profile.title, "period": draft.period.key,
            "prepared_by": draft.prepared_by, "synthetic": draft.synthetic,
            "facilities": [facility.title for facility in draft.profile.facilities],
        }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_eleven_sections_warm_rerun_does_not_reserialize_unchanged_values(report, monkeypatch):
    keys = [section.key for section in included_sections(report.sections)][:11]
    assert len(keys) == 11
    preview._cached_section_fingerprint.cache_clear()
    original = json.dumps
    serializations = []

    def counting(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("version") == 6:
            serializations.append(value["section"])
        return original(value, *args, **kwargs)

    baseline_wall, baseline_cpu = perf_counter(), process_time()
    baseline = {key: _legacy_fingerprint(report, key) for key in keys}
    baseline_wall, baseline_cpu = perf_counter() - baseline_wall, process_time() - baseline_cpu
    monkeypatch.setattr(json, "dumps", counting)
    cold_wall, cold_cpu = perf_counter(), process_time()
    first = {key: preview.section_preview_fingerprint(report, key) for key in keys}
    cold_wall, cold_cpu = perf_counter() - cold_wall, process_time() - cold_cpu
    warm_wall, warm_cpu = perf_counter(), process_time()
    assert {key: preview.section_preview_fingerprint(report, key) for key in keys} == first
    warm_wall, warm_cpu = perf_counter() - warm_wall, process_time() - warm_cpu
    print(f"A31 eleven-section fingerprint control: baseline_wall={baseline_wall:.6f}s "
          f"baseline_cpu={baseline_cpu:.6f}s cold_wall={cold_wall:.6f}s "
          f"cold_cpu={cold_cpu:.6f}s warm_wall={warm_wall:.6f}s "
          f"warm_cpu={warm_cpu:.6f}s serialized={len(serializations)} "
          f"maxrss_kib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}")
    assert len(serializations) == len(keys), "Warm unchanged sections must reuse their immutable hash"


def test_activity_edit_keeps_training_hash_and_cache_hit(report, monkeypatch):
    from app.monthly_report_preview import _cached_section_fingerprint
    _cached_section_fingerprint.cache_clear()
    old = preview.section_preview_fingerprint(report, "training")
    misses = _cached_section_fingerprint.cache_info().misses
    changed = replace(report, blocks=tuple(
        replace(block, text="Synthetic activity revised")
        if block.key == "activity_summary" else block for block in report.blocks
    ))
    assert preview.section_preview_fingerprint(changed, "activity") != preview.section_preview_fingerprint(report, "activity")
    assert preview.section_preview_fingerprint(changed, "training") == old
    assert _cached_section_fingerprint.cache_info().misses == misses + 2
    assert _cached_section_fingerprint.cache_info().hits >= 1
    assert old == _legacy_fingerprint(changed, "training")


def test_shared_logo_changes_both_and_source_refresh_invalidates(report, monkeypatch):
    old_cover = preview.section_preview_fingerprint(report, "cover")
    old_training = preview.section_preview_fingerprint(report, "training")
    new = replace(report, blocks=tuple(
        replace(block, asset_hashes=("shared-logo-v2.png",))
        if block.key == "brand_logo" else block for block in report.blocks
    ))
    assert preview.section_preview_fingerprint(new, "cover") != old_cover
    assert preview.section_preview_fingerprint(new, "training") != old_training
    assert preview.section_preview_fingerprint(new, "cover") == _legacy_fingerprint(new, "cover")
    assert preview.section_preview_fingerprint(new, "training") == _legacy_fingerprint(new, "training")
    state = {"value": "source-manifest-first"}
    monkeypatch.setattr(source_runtime, "cache_identity", lambda draft: state["value"])
    before = preview.section_preview_fingerprint(report, "training")
    assert before == _legacy_fingerprint(report, "training", state["value"])
    state["value"] = "source-manifest-replaced"
    after = preview.section_preview_fingerprint(report, "training")
    assert after != before
    assert after == _legacy_fingerprint(report, "training", state["value"])


def test_hash_identity_invalid_section_and_disposable_cache_boundary(report):
    for section in ("cover", "activity", "training"):
        assert preview.section_preview_fingerprint(report, section) == _legacy_fingerprint(report, section)
    with pytest.raises(ValueError, match="existing report section"):
        preview.section_preview_fingerprint(report, "unknown")
    # Private preview fingerprinting must never mutate saved report content.
    before = report.fingerprint
    preview.section_preview_fingerprint(report, "training")
    assert report.fingerprint == before

def test_native_assembly_reuses_training_after_activity_edit(report, monkeypatch):
    """Real cache path, synthetic renderer bytes; no final-export cache."""
    from pathlib import Path
    from app import monthly_report_section_assembly_cache as assembly
    from app import monthly_report_native_layout as native
    from app import monthly_report_designs as designs
    from app import monthly_report_render_jobs as jobs

    assembly.clear()
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 512 * 1024 * 1024)
    monkeypatch.setattr(preview, "preflight", lambda draft: [])
    monkeypatch.setattr(designs, "source_for", lambda profile: Path("synthetic-source.docx"))
    monkeypatch.setattr(designs, "is_master", lambda profile: False)
    calls = []

    def render(*args, **kwargs):
        calls.append(kwargs["section_key"])
        return b"synthetic-identical-assembly"

    monkeypatch.setattr(native, "build_native_docx", render)
    changed = replace(report, blocks=tuple(
        replace(block, text="Synthetic activity changed")
        if block.key == "activity_summary" else block for block in report.blocks
    ))
    try:
        with assembly.owner_scope("synthetic-session"):
            first = preview._section_preview_docx(report, "training")
            second = preview._section_preview_docx(changed, "training")
        assert first == second == b"synthetic-identical-assembly"
        assert calls == ["training"], "Unrelated Activity must not rebuild native Training"
    finally:
        assembly.clear()

def test_unhashable_legacy_metadata_falls_back_without_poisoning_cache(report):
    """The old v6 hash ignores this unrelated imported metadata field."""
    altered = replace(report, blocks=tuple(
        replace(block, asset_provenance=(("legacy", {"unhashable": "record"}),))
        if block.key == "training_summary" else block for block in report.blocks
    ))
    expected = _legacy_fingerprint(altered, "training")
    assert preview.section_preview_fingerprint(altered, "training") == expected
    assert preview.section_preview_fingerprint(altered, "training") == expected


def test_unavailable_source_identity_cannot_be_hidden_by_warm_cache(report, monkeypatch):
    preview.section_preview_fingerprint(report, "training")

    def vanished(draft):
        raise ValueError("Synthetic source receipt missing")

    monkeypatch.setattr(source_runtime, "cache_identity", vanished)
    with pytest.raises(ValueError, match="receipt missing"):
        preview.section_preview_fingerprint(report, "training")
