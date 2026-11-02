"""Contract-specific outage defaults never adopt legacy artwork implicitly."""
from dataclasses import asdict, replace
from io import BytesIO

import pytest
from PIL import Image

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as workflows
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def report(contract="Contract A", blocks=(), key="site"):
    profile = replace(synthetic_profiles()[0], contract=contract, key=key)
    return ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Editor", (), blocks)


def image_block(key="business_hours_workflow", color="navy"):
    data = BytesIO()
    Image.new("RGB", (40, 30), color).save(data, "PNG")
    raw = data.getvalue()
    ref = library.asset_reference(raw, "png")
    block = approve_all_assets(ResolvedBlock(key, "This month", asset_hashes=(ref,)))
    return block, {ref: raw}


def legacy(contract="Contract A"):
    block, assets = image_block()
    path = library._root() / "workflow_standards"
    for ref, raw in assets.items():
        library._atomic_write(path / "assets" / ref, raw)
    item = workflows.WorkflowStandard(block.key, block, contract, "old-site", block.fingerprint, "2026-01-01")
    data = library._json({"schema": 1, "revision": 1, "workflows": [asdict(item)]})
    library._atomic_write(path / "manifest.json", data)
    library._atomic_write(path / "history" / "00000001.json", data)
    return item


def file_bytes():
    return {str(p.relative_to(library._root())): p.read_bytes()
            for p in library._root().rglob("*") if p.is_file() and p.suffix != ".lock"}


def test_foreign_legacy_default_is_not_applied():
    legacy()
    incoming, assets = report("Contract B"), {}
    before = file_bytes()
    assert workflows.apply_defaults(incoming, assets) == incoming
    assert assets == {} and file_bytes() == before


def test_own_legacy_default_requires_explicit_adoption():
    legacy()
    incoming, assets = report(), {}
    before = file_bytes()
    assert workflows.apply_defaults(incoming, assets) == incoming
    assert assets == {} and file_bytes() == before


def test_opening_a_report_never_discovers_or_seeds_saved_profiles():
    block, assets = image_block()
    saved = report(blocks=(block,))
    library.save_snapshot(saved, expected_revision=0, assets=tuple(assets.items()))
    before = file_bytes()
    incoming = report()
    assert workflows.apply_defaults(incoming, {}) == incoming
    assert file_bytes() == before


def test_explicit_empty_omission_is_never_refilled():
    legacy()
    incoming = report(blocks=(ResolvedBlock("business_hours_workflow", "Omit"),))
    assert workflows.apply_defaults(incoming, {}) == incoming
