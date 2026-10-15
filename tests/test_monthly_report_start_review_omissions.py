"""An explicit changed source review is distinct from report-only deletion."""
from dataclasses import asdict, replace

import pytest

from app.monthly_report_import import inspect_docx
from app.monthly_report_start_import import build_starting_import
from app.monthly_report_start_replay import merge_starting_drafts
from tests.test_monthly_report_start_replay import activity, draft
from tests.test_monthly_report_start_import import build, report_file


def test_verified_source_review_removal_blanks_content_not_report_structure():
    previous = draft(activity("Original source wording."))
    incoming = draft()
    result = merge_starting_drafts(previous, incoming, previous)
    assert not result.blocks
    assert result.sections == previous.sections
    assert result.profile == previous.profile
    assert result.period == previous.period


@pytest.mark.parametrize("current", [draft(), draft(activity("Human correction.")), draft(activity(""))])
def test_removed_source_review_never_discards_current_human_edit(current):
    previous = draft(activity("Original source wording."))
    before = asdict(current)
    if current.blocks:
        with pytest.raises(ValueError, match="Activity summary differs"):
            merge_starting_drafts(current, draft(), previous)
    else:
        assert merge_starting_drafts(current, draft(), previous) == current
    assert asdict(current) == before


def test_removal_of_legacy_merged_block_requires_explicit_report_editor_recovery():
    previous = draft(activity("Earlier human wording.\n\nOriginal source wording."))
    with pytest.raises(ValueError, match="Activity summary differs"):
        merge_starting_drafts(previous, draft(), previous, verified=False)


def test_omission_then_saved_replay_and_explicit_reselection_are_idempotent():
    previous = draft(activity("Original source wording."))
    omitted = draft()
    removed = merge_starting_drafts(previous, omitted, previous)
    assert not removed.blocks
    assert merge_starting_drafts(removed, omitted, omitted) == removed
    restored = merge_starting_drafts(removed, previous, omitted)
    assert restored == previous
    assert merge_starting_drafts(restored, previous, previous) == restored


def test_source_removal_retains_unrelated_report_block_and_provenance():
    previous = draft(activity("Original source wording."))
    other = replace(previous.blocks[0], key="training_summary", text="Independent monthly note.",
                    references=("synthetic:independent",))
    current = draft(previous.blocks[0], other)
    result = merge_starting_drafts(current, draft(), previous)
    assert result.blocks == (other,)


def test_actual_docx_section_omission_survives_source_build_and_replay(tmp_path):
    path = report_file(tmp_path, activity=("September 2026 source work.",))
    original = path.read_bytes()
    _analysis, previous, plans = build(path)
    assert any(b.key == "activity_summary" and b.text for b in previous.blocks)
    plans["activity"].update(omit=True, selected=[], texts={}, tables={}, new_assets=[])
    mapped, _ = build_starting_import(path, inspect_docx(path), plans.values())
    from app.monthly_report_import import imported_draft
    incoming = imported_draft(previous.profile, previous.period, previous.prepared_by, mapped)
    assert not any(b.key == "activity_summary" for b in incoming.blocks)
    result = merge_starting_drafts(previous, incoming, previous)
    assert not any(b.key == "activity_summary" for b in result.blocks)
    assert path.read_bytes() == original
    assert next(b for b in result.blocks if b.key == "contact_matrix") == next(
        b for b in previous.blocks if b.key == "contact_matrix")


@pytest.mark.parametrize("interrupt", [False, True])
def test_source_review_omission_receipt_and_draft_publish_together(monkeypatch, tmp_path, interrupt):
    import hashlib
    from app import monthly_report_library as library
    from tests.test_monthly_report_start_import import PERIOD, start_app, save_start

    path = report_file(tmp_path, activity=("September 2026 source work.",))
    raw = path.read_bytes()
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    args = (initial.profile.contract, initial.profile.key)
    digest = hashlib.sha256(raw).hexdigest()
    prior, verified = library.starting_contribution(*args, PERIOD, digest)
    assert verified
    incoming = replace(prior, blocks=tuple(b for b in prior.blocks if b.key != "activity_summary"))
    result = merge_starting_drafts(initial, incoming, prior)
    assert not any(b.key == "activity_summary" for b in result.blocks)
    standing = library.load_profile(*args)
    library.save_snapshot(initial, expected_revision=0, entered_editor="Synthetic Editor")
    folder = library._profile_path(*args)
    before = (folder / "manifest.json").read_bytes()
    write = library._atomic_write
    if interrupt:
        def fail_head(target, data):
            if target == folder / "manifest.json":
                raise OSError("Synthetic interrupted omission publication")
            return write(target, data)
        monkeypatch.setattr(library, "_atomic_write", fail_head)

    def publish():
        library.save_report_setup(initial.profile, result, path,
            {"sha256": digest, "period": PERIOD.key}, assets=(),
            expected_revision=standing.revision, actor="Synthetic Editor", confirmed=True,
            snapshot_revision=1, source_draft=incoming)

    if interrupt:
        with pytest.raises(OSError, match="interrupted omission"):
            publish()
        assert (folder / "manifest.json").read_bytes() == before
        assert library.load_imported_draft(*args) == initial
        assert library.starting_contribution(*args, PERIOD, digest) == (prior, True)
    else:
        publish()
        reopened = library.load_imported_draft(*args)
        contribution, verified = library.starting_contribution(*args, PERIOD, digest)
        assert reopened == result and verified and contribution == incoming
        assert merge_starting_drafts(reopened, incoming, contribution) == result
    after = library.load_profile(*args)
    assert after.current == standing.current and after.versions == standing.versions
    assert library.load_snapshot(*args, PERIOD).draft == initial
    assert library.imported_original(*args).read_bytes() == raw == path.read_bytes()
