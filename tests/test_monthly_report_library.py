from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
import json

from PIL import Image
import pytest

from app import monthly_report_library as library
from app.monthly_report_model import BlockSpec, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    return profile


def png(color):
    stream = BytesIO()
    Image.new("RGB", (50, 50), color).save(stream, "PNG")
    raw = stream.getvalue()
    return library.asset_reference(raw, "png"), raw


def replace_chart(profile, revision, color):
    reference, raw = png(color)
    block = ResolvedBlock("org_chart", "Library", asset_hashes=(reference,))
    return library.replace_block(profile.contract, profile.key, "org_chart", block,
                                 label="Synthetic org chart", expected_revision=revision,
                                 actor="Synthetic Editor", confirmed=True, assets=((reference, raw),))


def test_create_replace_restore_and_audit(profile):
    state = replace_chart(profile, 1, "red")
    first = state.versions[-1]
    state = replace_chart(profile, 2, "blue")
    assert state.block("org_chart") != first.block
    restored = library.restore_block(profile.contract, profile.key, first.id, expected_revision=3,
                                     actor="Synthetic Reviewer", confirmed=True)
    assert restored.revision == 4
    assert restored.block("org_chart") == first.block
    assert len(restored.versions) == 3
    assert restored.audit[-1]["new_hash"] == first.block.fingerprint
    assert restored.audit[-1]["actor"] == "Synthetic Reviewer"
    assert library.read_asset(profile.contract, profile.key, first.block.asset_hashes[0]) == png("red")[1]


def test_confirmation_and_editor_required_before_write(profile):
    for actor, confirmed in (("", True), ("Synthetic Editor", False)):
        with pytest.raises(library.LibraryError, match="Confirm"):
            library.save_profile(replace(profile, title="New"), expected_revision=1, actor=actor, confirmed=confirmed)
    assert library.load_profile(profile.contract, profile.key).revision == 1


def test_revision_guard_serializes_competing_writers(profile):
    def save(color):
        try:
            return replace_chart(profile, 1, color).revision
        except library.RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ("red", "blue")))
    assert sorted(results, key=str) == [2, "conflict"]
    assert library.load_profile(profile.contract, profile.key).revision == 2


def test_atomic_manifest_failure_keeps_old_head(profile, monkeypatch):
    original = library.os.replace

    def fail(source, target):
        if target.name == "manifest.json":
            raise OSError("Synthetic disk failure")
        return original(source, target)

    monkeypatch.setattr(library.os, "replace", fail)
    with pytest.raises(OSError):
        replace_chart(profile, 1, "red")
    assert library.load_profile(profile.contract, profile.key).revision == 1
    assert not list(library._root().rglob(".pending-*"))


def test_profile_membership_edits_are_restorable(profile):
    library.save_profile(replace(profile, title="Revised synthetic title"), expected_revision=1,
                         actor="Synthetic Editor", confirmed=True)
    restored = library.restore_profile(profile.contract, profile.key, 1, expected_revision=2,
                                       actor="Synthetic Editor", confirmed=True)
    assert restored.profile == profile
    assert restored.revision == 3


@pytest.mark.parametrize("key", ["../escape", "../", "/tmp", "a/b", "", "a\\b"])
def test_profile_paths_reject_traversal(profile, key):
    with pytest.raises(library.LibraryError):
        library.load_profile(profile.contract, key)


def test_asset_integrity_and_profile_isolation(profile):
    state = replace_chart(profile, 1, "red")
    reference = state.block("org_chart").asset_hashes[0]
    with pytest.raises(library.LibraryError):
        library.read_asset(profile.contract, "other", reference)
    with pytest.raises(library.LibraryError):
        library.read_asset(profile.contract, profile.key, "../manifest.json")
    damaged = library._profile_path(profile.contract, profile.key) / "assets" / reference
    damaged.unlink()  # Simulate out-of-band replacement of an immutable link.
    damaged.write_bytes(b"corrupt")
    with pytest.raises(library.LibraryError, match="integrity"):
        library.read_asset(profile.contract, profile.key, reference)


def test_snapshot_versions_pin_assets_and_preserve_open_items(profile):
    state = replace_chart(profile, 1, "red")
    original = state.block("org_chart")
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    draft = replace(draft, blocks=(*draft.blocks, original), sections=(
        replace(draft.sections[0], blocks=(BlockSpec("org_chart", "image_page"),)), *draft.sections[1:]))
    library.save_snapshot(draft, expected_revision=0, open_issues=("Synthetic pump needs review",), pending_proposals=("Synthetic quote pending",))
    replace_chart(profile, 2, "blue")
    saved = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert saved.draft == draft
    assert saved.open_issues == ("Synthetic pump needs review",)
    assert saved.pending_proposals == ("Synthetic quote pending",)
    assert saved.draft.blocks[-1] == original
    assert library.usage_count(profile.contract, profile.key, original.asset_hashes[0]) == 1
    with pytest.raises(library.RevisionConflict):
        library.save_snapshot(draft, expected_revision=0)
    library.save_snapshot(draft, expected_revision=1)
    assert library.usage_count(profile.contract, profile.key, original.asset_hashes[0]) == 1
    assert len(list((library._profile_path(profile.contract, profile.key, snapshots=True) / "history").glob("*.json"))) == 2


def test_omitted_images_are_not_counted_as_used(profile):
    state = replace_chart(profile, 1, "red")
    block = state.block("org_chart")
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    draft = replace(draft, blocks=(*draft.blocks, block))
    library.save_snapshot(draft, expected_revision=0)
    assert library.usage_count(profile.contract, profile.key, block.asset_hashes[0]) == 0


def test_invalid_section_defaults_fail_before_mutation(profile):
    with pytest.raises(library.LibraryError, match="omitted"):
        library.save_profile(replace(profile, excluded_sections=("unknown",)), expected_revision=1,
                             actor="Synthetic Editor", confirmed=True)
    assert library.load_profile(profile.contract, profile.key).revision == 1


def test_unknown_or_corrupt_schema_never_resets_saved_library(profile):
    path = library._profile_path(profile.contract, profile.key) / "manifest.json"
    data = json.loads(path.read_bytes())
    data["schema"] = 99
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(library.LibraryError, match="Unsupported"):
        library.save_profile(profile, expected_revision=1, actor="Synthetic Editor", confirmed=True)
    assert path.read_bytes() == before
