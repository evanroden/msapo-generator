"""A85: interrupted browser drafts may restore only their own referenced pictures.

All cases use synthetic content and a disposable EPC_DATA_DIR. No real report,
user browser cookie, or production standing data is accessed.
"""
from dataclasses import replace
from io import BytesIO
import random

import pytest
from PIL import Image

from app import monthly_report_active_work as active
from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ResolvedBlock
from test_monthly_report_active_work import make_draft

TOKEN = "8" * 32
OTHER = "9" * 32


def picture(large=False):
    output = BytesIO()
    if large:
        # Deterministic, nontrivial PNG: prevents a tiny solid-image fixture
        # from accidentally skipping the large-picture recovery path.
        image = Image.frombytes("RGB", (768, 768),
                                random.Random(85).randbytes(768 * 768 * 3))
    else:
        image = Image.new("RGB", (128, 96), "#32748a")
    image.save(output, format="PNG")
    return output.getvalue()


def with_picture(draft, reference, text="Local text survives reconnect"):
    # The synthetic report uses demo_* block keys rather than regular monthly
    # keys. Pick a genuinely included section for the runtime ownership check.
    block_key = next(s.blocks[0].key for s in draft.sections if s.included)
    return replace(draft, prepared_by="Synthetic browser editor", blocks=(
        ResolvedBlock(block_key, "This month", text=text,
                      asset_hashes=(reference,), asset_captions=("Synthetic photo",)),))


def location(draft):
    return active._directory(TOKEN, draft.profile.contract,
                             draft.profile.key, draft.period) / "working.json"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return make_draft()


@pytest.mark.parametrize("large", (False, True))
def test_refresh_and_disconnect_reattach_preserve_text_and_picture(isolated, large):
    draft = isolated
    raw = picture(large)
    ref = library.asset_reference(raw, "png")
    working = with_picture(draft, ref)
    saved = active.save(TOKEN, working, expected_revision=0,
                        base_snapshot_revision=0, assets={ref: raw})
    journal_before = location(draft).read_bytes()
    # Refresh and reconnect are new clients loading the durable journal; a
    # repeated no-change event must not create a second version.
    for _ in range(2):
        restored = active.load(TOKEN, draft.profile.contract,
                               draft.profile.key, draft.period)
        assert restored.draft == working
        assert dict(restored.assets)[ref] == raw
        assert restored.revision == saved.revision
        again = active.save(TOKEN, restored.draft,
            expected_revision=restored.revision,
            expected_generation=restored.generation,
            base_snapshot_revision=restored.base_snapshot_revision,
            assets=dict(restored.assets))
        assert again.revision == saved.revision
        assert location(draft).read_bytes() == journal_before
    assert active.load(OTHER, draft.profile.contract, draft.profile.key,
                       draft.period) is None
    assert library.load_snapshot(draft.profile.contract, draft.profile.key,
                                 draft.period) is None


def test_two_tab_stale_picture_save_cannot_replace_newer_text(isolated):
    draft = isolated
    raw = picture()
    ref = library.asset_reference(raw, "png")
    initial = with_picture(draft, ref, "Tab one text")
    first = active.save(TOKEN, initial, expected_revision=0,
                        base_snapshot_revision=0, assets={ref: raw})
    latest = with_picture(draft, ref, "Tab two newer text")
    second = active.save(TOKEN, latest, expected_revision=first.revision,
                         expected_generation=first.generation,
                         base_snapshot_revision=0, assets={ref: raw})
    before = location(draft).read_bytes()
    with pytest.raises(active.ActiveWorkConflict):
        active.save(TOKEN, initial, expected_revision=first.revision,
                    expected_generation=first.generation,
                    base_snapshot_revision=0, assets={ref: raw})
    restored = active.load(TOKEN, draft.profile.contract,
                           draft.profile.key, draft.period)
    assert restored.draft == latest and restored.revision == second.revision
    assert dict(restored.assets)[ref] == raw
    assert location(draft).read_bytes() == before


def test_foreign_report_picture_cannot_be_claimed_by_an_owning_browser(isolated):
    draft = isolated
    raw = picture()
    ref = library.asset_reference(raw, "png")
    # Digest authenticity alone does not grant access to another report's
    # private asset. The same digest exists only under the foreign profile.
    foreign = library._profile_path(draft.profile.contract, "different-site") / "assets" / ref
    library._atomic_write(foreign, raw)
    working = with_picture(draft, ref)
    with pytest.raises(library.LibraryError, match="picture|asset|reference"):
        active.save(TOKEN, working, expected_revision=0,
                    base_snapshot_revision=0)
    assert not location(draft).exists()
    assert foreign.read_bytes() == raw


def test_same_report_library_picture_is_a_valid_reference_without_reupload(isolated):
    draft = isolated
    raw = picture()
    ref = library.asset_reference(raw, "png")
    own = library._profile_path(draft.profile.contract, draft.profile.key) / "assets" / ref
    library._atomic_write(own, raw)
    working = with_picture(draft, ref)
    saved = active.save(TOKEN, working, expected_revision=0,
                        base_snapshot_revision=0)
    recovered = active.load(TOKEN, draft.profile.contract,
                            draft.profile.key, draft.period)
    assert recovered.draft == working and recovered.revision == saved.revision
    assert recovered.assets == () and own.read_bytes() == raw


@pytest.mark.parametrize("damage", ("orphan", "dictionary", "duplicate", "null"))
def test_malformed_or_orphan_picture_manifest_rejected_without_touching_shared_report(isolated, damage):
    draft = isolated
    report = library.save_snapshot(draft, expected_revision=0,
                                   entered_editor="Synthetic reporter")
    raw = picture()
    ref = library.asset_reference(raw, "png")
    working = with_picture(draft, ref)
    active.save(TOKEN, working, expected_revision=0,
                base_snapshot_revision=report.revision, assets={ref: raw})
    path = location(draft)
    manifest = library._read(path)
    if damage == "orphan":
        manifest["assets"] = []
    elif damage == "dictionary":
        manifest["assets"] = {ref: "not a journal list"}
    elif damage == "duplicate":
        manifest["assets"] = [ref, ref]
    else:
        manifest["assets"] = None
    library._atomic_write(path, library._json(manifest))
    corrupted = path.read_bytes()
    with pytest.raises(library.LibraryError):
        active.load(TOKEN, draft.profile.contract, draft.profile.key, draft.period)
    # An apparently valid next edit may not silently replace the bad journal
    # either: keep its previous bytes for an explicit, reviewed recovery.
    with pytest.raises(library.LibraryError):
        active.save(TOKEN, replace(working, prepared_by="Synthetic later editor"),
                    expected_revision=1, base_snapshot_revision=report.revision,
                    assets={ref: raw})
    assert path.read_bytes() == corrupted
    assert library.load_snapshot(draft.profile.contract, draft.profile.key,
                                 draft.period) == report


@pytest.mark.parametrize("damage", ("absent", "broken_json", "foreign_reference"))
def test_missing_or_broken_browser_journal_does_not_delete_saved_report(isolated, damage):
    draft = isolated
    report = library.save_snapshot(draft, expected_revision=0,
                                   entered_editor="Synthetic reporter")
    path = location(draft)
    if damage == "absent":
        assert active.load(TOKEN, draft.profile.contract,
                           draft.profile.key, draft.period) is None
    else:
        active.save(TOKEN, draft, expected_revision=0,
                    base_snapshot_revision=report.revision)
        if damage == "broken_json":
            path.write_text("{not json")
        else:
            raw = picture()
            ref = library.asset_reference(raw, "png")
            foreign = library._profile_path(draft.profile.contract, "different-site") / "assets" / ref
            library._atomic_write(foreign, raw)
            staged = with_picture(draft, ref)
            manifest = library._read(path)
            from dataclasses import asdict
            manifest["draft"] = asdict(staged)
            manifest["fingerprint"] = staged.fingerprint
            library._atomic_write(path, library._json(manifest))
        with pytest.raises(library.LibraryError):
            active.load(TOKEN, draft.profile.contract, draft.profile.key, draft.period)
    assert library.load_snapshot(draft.profile.contract, draft.profile.key,
                                 draft.period) == report
    assert library.snapshot_history(draft.profile.contract, draft.profile.key,
                                    draft.period)[0][0].revision == report.revision
