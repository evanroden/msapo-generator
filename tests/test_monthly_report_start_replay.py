"""Source replay is three-way and isolated from generic/new-source merging."""
from dataclasses import asdict, replace
import hashlib

import pytest

from app import monthly_report_library as library
from app.monthly_report_import import MappedImport, imported_draft
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_start_replay import merge_starting_drafts
from tests.test_monthly_report_start_import import report_file, start_app, save_start

PERIOD = ReportPeriod(2026, 9)


def draft(*blocks):
    return imported_draft(synthetic_profiles()[0], PERIOD, "Synthetic Editor",
                          MappedImport(blocks, (), (), ()))


def activity(text, **kwargs):
    return ResolvedBlock("activity_summary", "This month", text=text, **kwargs)


@pytest.mark.parametrize("edited", [draft(), draft(activity("")), draft(activity("Manual correction."))])
def test_unchanged_source_never_restores_cleared_missing_or_corrected_block(edited):
    previous = draft(activity("Original wording."))
    assert merge_starting_drafts(edited, previous, previous) == edited


def test_changed_selection_replaces_only_unchanged_contribution_then_replays_identically():
    previous = draft(activity("Original wording."))
    incoming = draft(activity("Explicitly corrected source review."))
    updated = merge_starting_drafts(previous, incoming, previous)
    assert updated == incoming
    assert merge_starting_drafts(updated, incoming, incoming) == updated


@pytest.mark.parametrize("verified", [True, False])
def test_changes_on_both_sides_are_named_conflicts_not_overwrites(verified):
    previous = draft(activity("Original wording."))
    current = draft(activity("Manual correction."))
    incoming = draft(activity("Different source-review correction."))
    before = asdict(current)
    with pytest.raises(ValueError, match="Activity summary differs"):
        merge_starting_drafts(current, incoming, previous, verified=verified)
    assert asdict(current) == before


def test_legacy_merged_bootstrap_cannot_authorize_changed_review_replacement():
    previous = draft(activity("Legacy merged wording."))
    incoming = draft(activity("New source review."))
    with pytest.raises(ValueError, match="Activity summary differs"):
        merge_starting_drafts(previous, incoming, previous, verified=False)


def test_new_source_keeps_normal_append_and_conflict_behavior():
    existing = draft(activity("Current work."))
    incoming = draft(activity("Additional new source."))
    result = merge_starting_drafts(existing, incoming)
    assert result.blocks[0].text == "Current work.\n\nAdditional new source."


def test_newly_selected_block_does_not_restore_unchanged_cleared_block():
    previous = draft(activity("Old activity."))
    current = draft(activity(""))
    training = ResolvedBlock("training_summary", "This month", text="Client staff training pending.")
    incoming = draft(previous.blocks[0], training)
    result = merge_starting_drafts(current, incoming, previous)
    assert result.blocks[0] == current.blocks[0]
    assert result.blocks[1] == incoming.blocks[1]


@pytest.mark.parametrize("which", ["existing", "previous"])
def test_replay_never_crosses_profile_or_month(which):
    previous = draft(activity("Original."))
    wrong = replace(previous, period=ReportPeriod(2026, 10))
    with pytest.raises(ValueError, match="different sites or a different month"):
        merge_starting_drafts(wrong if which == "existing" else previous,
                              previous, wrong if which == "previous" else previous)


def test_acknowledged_receipt_is_month_scoped_and_corruption_fails_closed(monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("September 2026 work.",))
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    args = (initial.profile.contract, initial.profile.key)
    previous, verified = library.starting_contribution(*args, PERIOD, digest)
    assert verified and previous is not None
    assert library.starting_contribution(*args, ReportPeriod(2026, 10), digest) == (None, False)
    folder = library._profile_path(*args)
    value = library._read(folder / "manifest.json")
    reference = value["starting_contributions"][PERIOD.key + ":" + digest]
    receipt = folder / "imports" / (reference + ".contribution.json")
    payload = library._read(receipt)
    payload["draft"]["prepared_by"] = "Tampered synthetic receipt"
    receipt.write_bytes(library._json(payload))
    with pytest.raises(library.LibraryError, match="record changed"):
        library.starting_contribution(*args, PERIOD, digest)
    assert library.load_imported_draft(*args) == initial


def test_legacy_latest_source_uses_only_conservative_bootstrap(monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("September 2026 work.",))
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    args = (initial.profile.contract, initial.profile.key)
    folder = library._profile_path(*args)
    manifest = library._read(folder / "manifest.json")
    manifest.pop("starting_contributions")
    (folder / "manifest.json").write_bytes(library._json(manifest))
    previous, verified = library.starting_contribution(*args, PERIOD, hashlib.sha256(path.read_bytes()).hexdigest())
    assert previous == initial and not verified


def test_failed_manifest_write_does_not_acknowledge_new_source(monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("September 2026 old work.",))
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    args = (initial.profile.contract, initial.profile.key)
    folder = library._profile_path(*args)
    manifest_before = (folder / "manifest.json").read_bytes()
    path = report_file(tmp_path, activity=("September 2026 new bytes.",))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    state = library.load_profile(*args)
    real_write = library._atomic_write
    def fail_head(target, raw):
        if target == folder / "manifest.json":
            raise OSError("Synthetic interrupted manifest save")
        return real_write(target, raw)
    monkeypatch.setattr(library, "_atomic_write", fail_head)
    with pytest.raises(OSError, match="interrupted manifest"):
        library.save_report_setup(initial.profile, initial, path,
            {"sha256": digest, "period": PERIOD.key}, assets=(),
            expected_revision=state.revision, actor="Synthetic Editor", confirmed=True,
            source_draft=initial)
    assert (folder / "manifest.json").read_bytes() == manifest_before
    assert library.starting_contribution(*args, PERIOD, digest) == (None, False)
    assert library.load_imported_draft(*args) == initial


def test_omitted_report_block_cannot_be_treated_as_an_unchanged_included_block():
    previous = draft(activity("Original wording."))
    current = replace(previous, blocks=(replace(previous.blocks[0], source="Omit"),))
    incoming = draft(activity("Changed source review."))
    with pytest.raises(ValueError, match="Activity summary differs"):
        merge_starting_drafts(current, incoming, previous)
    assert current.blocks[0].source == "Omit"


@pytest.mark.parametrize("bad", ["", "../outside", None, 12])
def test_invalid_acknowledged_pointer_never_falls_back_to_a_new_import(monkeypatch, tmp_path, bad):
    path = report_file(tmp_path, activity=("September 2026 work.",))
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    args = (initial.profile.contract, initial.profile.key)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    folder = library._profile_path(*args)
    value = library._read(folder / "manifest.json")
    value["starting_contributions"][PERIOD.key + ":" + digest] = bad
    (folder / "manifest.json").write_bytes(library._json(value))
    with pytest.raises(library.LibraryError, match="invalid identity"):
        library.starting_contribution(*args, PERIOD, digest)
    assert library.load_imported_draft(*args) == initial
