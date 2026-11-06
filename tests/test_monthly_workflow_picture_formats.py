"""Malformed content-hash-named pictures must never become shared contract defaults.

Refs #785, #474: all documents, profiles and images in this module are synthetic.
"""

from dataclasses import asdict
from io import BytesIO

import pytest
from PIL import Image

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as standards
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_contract_workflows import isolated, image_block, report, file_bytes


def picture(fmt="PNG", color="navy"):
    stream = BytesIO()
    Image.new("RGB", (40, 30), color).save(stream, fmt)
    return stream.getvalue()


def candidate(raw, suffix="png"):
    reference = library.asset_reference(raw, suffix)
    block = approve_all_assets(ResolvedBlock(
        "business_hours_workflow", "This month", asset_hashes=(reference,)))
    return block, {reference: raw}


def publish(block, assets, *, revision=0, contract="Contract A"):
    draft = report(contract, (block,))
    return standards.save_standard(
        draft, block, assets, expected_revision=revision,
        expected_fingerprint=block.fingerprint, confirmed=True)


@pytest.mark.parametrize("suffix,raw", [
    ("png", b"not a PNG despite its matching content hash"),
    ("jpg", b"not a JPEG despite its matching content hash"),
    ("png", b"\\x89PNG\\r\\n\\x1a\\nnot-a-decodable-image"),
    ("jpg", b"\\xff\\xd8\\xff\\xe0not-a-decodable-image"),
])
def test_invalid_but_correctly_hashed_picture_does_not_publish(suffix, raw):
    block, assets = candidate(raw, suffix)
    before = file_bytes()
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        publish(block, assets)
    assert file_bytes() == before
    assert standards.load_standards("Contract A").revision == 0


@pytest.mark.parametrize("actual,declared", [("PNG", "jpg"), ("JPEG", "png")])
def test_valid_picture_with_wrong_declared_extension_cannot_be_saved(actual, declared):
    block, assets = candidate(picture(actual), declared)
    before = file_bytes()
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        publish(block, assets)
    assert file_bytes() == before
    assert standards.load_standards("Contract A").revision == 0


@pytest.mark.parametrize("trim", [2, 12])
def test_truncated_jpeg_with_matching_hash_does_not_publish(trim):
    # Pillow's Image.verify() alone accepts these truncated JPEGs; decoding
    # must also establish that the complete scan data is present.
    block, assets = candidate(picture("JPEG")[:-trim], "jpg")
    before = file_bytes()
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        publish(block, assets)
    assert file_bytes() == before


@pytest.mark.parametrize("fmt,suffix,contract", [
    ("PNG", "png", "Contract A"),
    ("JPEG", "jpg", "Contract B"),
])
def test_valid_diagrams_still_publish_read_and_reuse(fmt, suffix, contract):
    raw = picture(fmt)
    block, assets = candidate(raw, suffix)
    saved = publish(block, assets, contract=contract)
    assert saved.revision == 1
    assert standards.read_asset(block.asset_hashes[0], contract=contract) == raw
    incoming = {}
    result = standards.apply_defaults(report(contract), incoming)
    assert incoming == assets
    assert result.blocks[0].asset_hashes == block.asset_hashes
    assert standards.load_standards(contract) == saved


def test_rejected_replacement_preserves_prior_manifest_history_and_assets():
    first, original_assets = image_block()
    original = publish(first, original_assets)
    before = file_bytes()
    damaged, bad_assets = candidate(b"correctly hashed, but not an image")
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        publish(damaged, bad_assets, revision=1)
    assert file_bytes() == before
    assert standards.load_standards("Contract A") == original
    assert standards.apply_defaults(report(), {}).blocks[0].asset_hashes == first.asset_hashes
    replacement, assets = candidate(picture("PNG", "green"))
    latest = publish(replacement, assets, revision=1)
    assert latest.revision == 2
    assert latest.workflows[0].block.asset_hashes == replacement.asset_hashes
    assert standards.load_standards("Contract A") == latest
    assert original.workflows[0].block.asset_hashes == first.asset_hashes


def test_existing_hash_matched_but_corrupt_contract_picture_is_not_reused():
    # A synthetic legacy manifest may already refer to bytes whose hash is
    # correct but whose content is not a PNG. No migration or data deletion.
    raw = b"legacy bytes are not PNG pixels"
    block, assets = candidate(raw)
    pinned = standards._pinned(block, "Contract A")
    item = standards.WorkflowStandard(
        block.key, pinned, "contract a", "site", block.fingerprint, "2026-11-06")
    path = standards._path("Contract A")
    encoded = library._json({
        "schema": 1, "workflow_scope": "contract",
        "contract": standards._contract("Contract A"), "actor": "Synthetic Editor",
        "revision": 1, "workflows": [asdict(item)],
    })
    library._atomic_write(path / "assets" / block.asset_hashes[0], raw)
    library._atomic_write(path / "manifest.json", encoded)
    before = file_bytes()
    incoming = {"keep": b"previous work"}
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        standards.apply_defaults(report(), incoming)
    assert incoming == {"keep": b"previous work"}
    assert file_bytes() == before
    assert standards.load_standards("Contract A").revision == 1
