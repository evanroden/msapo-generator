"""Changed source-review omissions cannot claim ownership of equal report text."""
from dataclasses import asdict, replace
import hashlib

import pytest

from app import monthly_report_library as library
from app.monthly_report_import import inspect_docx, imported_draft
from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_start_import import build_starting_import
from app.monthly_report_start_replay import _content, merge_starting_drafts
from tests.test_monthly_report_start_replay import activity, draft
from tests.test_monthly_report_start_import import PERIOD, build, report_file, start_app, save_start


@pytest.mark.parametrize("text", ["Original source wording.", "Human correction."])
def test_populated_source_deselection_needs_report_scoped_recovery(text):
    previous = draft(activity("Original source wording."))
    current = draft(activity(text))
    before = asdict(current)
    with pytest.raises(ValueError, match="Activity summary is still in this report"):
        merge_starting_drafts(current, draft(), previous)
    assert asdict(current) == before


@pytest.mark.parametrize("current", [draft(), draft(activity("")),
    draft(activity("Original source wording.", references=("synthetic:retained",)))])
def test_absent_blank_or_explicit_omit_can_acknowledge_source_deselection(current):
    # Omit is a report-level decision, not permission to destroy retained text.
    if current.blocks and current.blocks[0].text:
        current = replace(current, blocks=(replace(current.blocks[0], source="Omit"),))
    previous = draft(activity("Original source wording."))
    assert merge_starting_drafts(current, draft(), previous) == current
    assert merge_starting_drafts(current, draft(), draft()) == current


def test_legacy_merged_block_is_not_deleted_by_source_deselection():
    previous = draft(activity("Earlier human wording.\n\nOriginal source wording."))
    with pytest.raises(ValueError, match="Clear or omit this content in the report editor"):
        merge_starting_drafts(previous, draft(), previous, verified=False)


@pytest.mark.parametrize("kind", ["text", "rows"])
def test_deduplicated_human_content_survives_reselection_then_deselection(kind):
    source = activity("Grounded wording.", references=("synthetic:source",)) if kind == "text" else (
        ResolvedBlock("activity_summary", "This month", rows=(("Known item", "Pending"),),
                      references=("synthetic:source",)))
    human = replace(source, references=())
    original_report = draft(human)
    before = asdict(original_report)
    previous = draft()
    incoming = draft(source)
    merged = merge_starting_drafts(original_report, incoming, previous)
    # Equality with the receipt is real, but does not establish sole ownership.
    assert tuple(map(_content, merged.blocks)) == tuple(map(_content, incoming.blocks))
    with pytest.raises(ValueError, match="is still in this report"):
        merge_starting_drafts(merged, draft(), incoming)
    assert asdict(original_report) == before
    assert _content(merged.blocks[0]) == _content(source)


@pytest.mark.parametrize("with_block", [True, False])
@pytest.mark.parametrize("address", ["Source office address", "Human corrected office address"])
def test_footer_deselection_cannot_leave_hidden_native_address_value(with_block, address):
    footer = ResolvedBlock("footer_text", "This month", text="Source office address")
    previous = replace(draft(footer), address_line=footer.text)
    current = replace(previous, blocks=(footer,) if with_block else (), address_line=address)
    with pytest.raises(ValueError, match="Footer text is still in this report"):
        merge_starting_drafts(current, draft(), previous)
    assert current.address_line == address


def test_explicitly_cleared_footer_and_address_remain_blank():
    footer = ResolvedBlock("footer_text", "This month", text="Source office address")
    previous = replace(draft(footer), address_line=footer.text)
    current = replace(previous, blocks=(replace(footer, text=""),), address_line="")
    result = merge_starting_drafts(current, draft(), previous)
    assert result == current and not result.address_line


def test_actual_docx_source_omission_does_not_publish_false_blank(tmp_path):
    path = report_file(tmp_path, activity=("September 2026 source work.",))
    original = path.read_bytes()
    _analysis, previous, plans = build(path)
    plans["activity"].update(omit=True, selected=[], texts={}, tables={}, new_assets=[])
    mapped, _ = build_starting_import(path, inspect_docx(path), plans.values())
    incoming = imported_draft(previous.profile, previous.period, previous.prepared_by, mapped)
    assert not any(b.key == "activity_summary" for b in incoming.blocks)
    with pytest.raises(ValueError, match="Activity summary is still in this report"):
        merge_starting_drafts(previous, incoming, previous)
    cleared = replace(previous, blocks=tuple(replace(b, text="") if b.key == "activity_summary"
                                             else b for b in previous.blocks))
    result = merge_starting_drafts(cleared, incoming, previous)
    assert result == cleared
    assert result.sections == previous.sections and path.read_bytes() == original


@pytest.mark.parametrize("interrupt", [False, True])
def test_explicit_clear_then_source_deselection_publishes_atomically(monkeypatch, tmp_path, interrupt):
    path = report_file(tmp_path, activity=("September 2026 source work.",))
    raw = path.read_bytes()
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    args = (initial.profile.contract, initial.profile.key)
    digest = hashlib.sha256(raw).hexdigest()
    prior, verified = library.starting_contribution(*args, PERIOD, digest)
    assert verified
    incoming = replace(prior, blocks=tuple(b for b in prior.blocks if b.key != "activity_summary"))
    folder = library._profile_path(*args)
    before = (folder / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="Activity summary is still in this report"):
        merge_starting_drafts(initial, incoming, prior)
    assert (folder / "manifest.json").read_bytes() == before
    assert library.starting_contribution(*args, PERIOD, digest) == (prior, True)
    cleared = replace(initial, blocks=tuple(b for b in initial.blocks if b.key != "activity_summary"))
    result = merge_starting_drafts(cleared, incoming, prior)
    assert result == cleared
    standing = library.load_profile(*args)
    library.save_snapshot(initial, expected_revision=0, entered_editor="Synthetic Editor")
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


@pytest.mark.parametrize("source, correction", [
    (activity("Original wording."), activity("Human corrected wording.")),
    (ResolvedBlock("work_orders", "This month", rows=(("Pump", "Pending"),)),
     ResolvedBlock("work_orders", "This month", rows=(("Pump", "NR"),))),
    (ResolvedBlock("water_reports", "This month", asset_hashes=("a" * 64 + ".png",),
                   asset_captions=("Original caption",)),
     ResolvedBlock("water_reports", "This month", asset_hashes=("b" * 64 + ".png",),
                   asset_captions=("Human corrected caption",))),
    (ResolvedBlock("work_orders", "This month", extra_tables=(
        ReportTable(("Item", "Status"), (("Pump", "Pending"),), "synthetic:table"),)),
     ResolvedBlock("work_orders", "This month", extra_tables=(
        ReportTable(("Item", "Status"), (("Pump", "NR"),), "synthetic:table"),))),
    (ResolvedBlock("footer_text", "This month", text="Original office address"),
     ResolvedBlock("footer_text", "This month", text="Human corrected office address")),
    (activity("Original wording."), activity("")),
], ids=["text", "rows", "image-caption", "extra-table", "footer", "empty-omission"])
@pytest.mark.parametrize("verified", [True, False])
def test_acknowledged_deselection_then_reselection_preserves_report_omission(source, correction, verified):
    previous = draft(source)
    # The footer's independently rendered address was deliberately cleared;
    # the omitted block still retains its recoverable corrected wording.
    current = replace(previous, blocks=(replace(correction, source="Omit"),), address_line="")
    deselected = replace(previous, blocks=(), address_line="")
    kept = merge_starting_drafts(current, deselected, previous, verified=verified)
    assert kept == current
    before = asdict(kept)
    reselected = merge_starting_drafts(kept, previous, deselected, verified=verified)
    assert reselected == kept
    assert asdict(kept) == before
    assert merge_starting_drafts(reselected, previous, previous, verified=verified) == kept
    assert merge_starting_drafts(kept, deselected, deselected, verified=verified) == kept


def test_omission_guard_does_not_change_genuinely_new_source_merging():
    incoming = draft(activity("New source wording."))
    current = replace(incoming, blocks=(replace(incoming.blocks[0], source="Omit",
                                               text="Retained earlier wording."),))
    assert merge_starting_drafts(current, incoming) == incoming


def test_reselection_keeps_report_omission_while_adding_another_source_block():
    incoming = draft(activity("Original source wording."),
                     ResolvedBlock("training_summary", "This month", text="Synthetic client staff training."))
    omitted = replace(draft(incoming.blocks[0]), blocks=(replace(incoming.blocks[0],
                      source="Omit", text="Retained human correction."),))
    result = merge_starting_drafts(omitted, incoming, draft())
    blocks = {block.key: block for block in result.blocks}
    assert blocks["activity_summary"] == omitted.blocks[0]
    assert blocks["training_summary"] == incoming.blocks[1]
    assert merge_starting_drafts(result, incoming, incoming) == result


def test_source_reselection_receipt_keeps_saved_omitted_work(monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("September 2026 source work.",))
    initial = save_start(start_app(monkeypatch, tmp_path, path))
    args = (initial.profile.contract, initial.profile.key)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    prior, verified = library.starting_contribution(*args, PERIOD, digest)
    assert verified
    current = replace(initial, blocks=tuple(
        replace(block, source="Omit", text="Retained human correction.")
        if block.key == "activity_summary" else block for block in initial.blocks))
    deselected = replace(prior, blocks=tuple(block for block in prior.blocks
                                            if block.key != "activity_summary"))
    kept = merge_starting_drafts(current, deselected, prior)
    state = library.load_profile(*args)
    library.save_snapshot(kept, expected_revision=0, entered_editor="Synthetic Editor")
    library.save_report_setup(initial.profile, kept, path,
        {"sha256": digest, "period": PERIOD.key}, assets=(), expected_revision=state.revision,
        actor="Synthetic Editor", confirmed=True, snapshot_revision=1, source_draft=deselected)
    acknowledged, verified = library.starting_contribution(*args, PERIOD, digest)
    assert verified and acknowledged == deselected
    reselected = merge_starting_drafts(library.load_imported_draft(*args), prior, acknowledged)
    assert reselected == kept
    state = library.load_profile(*args)
    library.save_report_setup(initial.profile, reselected, path,
        {"sha256": digest, "period": PERIOD.key}, assets=(), expected_revision=state.revision,
        actor="Synthetic Editor", confirmed=True, snapshot_revision=1, source_draft=prior)
    assert library.starting_contribution(*args, PERIOD, digest) == (prior, True)
    assert library.load_imported_draft(*args) == kept
    assert library.load_snapshot(*args, PERIOD).draft == kept
    assert library.imported_original(*args).read_bytes() == path.read_bytes()
    assert library.load_profile(*args).current == state.current
    assert library.load_profile(*args).versions == state.versions
    assert merge_starting_drafts(kept, prior, prior) == kept


def test_manual_editor_reinclusion_after_consumed_reselection_keeps_human_wording():
    from app.monthly_report_guided import _edited_rich_text
    source = draft(activity("Original source wording."))
    omitted = replace(source, blocks=(replace(source.blocks[0], source="Omit",
                                              text="Retained human correction."),))
    reselected = merge_starting_drafts(omitted, source, draft())
    assert reselected == omitted
    edited = _edited_rich_text(reselected.blocks[0], "Human correction explicitly included.")
    assert edited.source != "Omit"
    included = replace(reselected, blocks=(edited,))
    assert merge_starting_drafts(included, source, source) == included


@pytest.mark.parametrize("address", ["Human corrected address", ""])
@pytest.mark.parametrize("matching_reviewed_block", [True, False])
def test_changed_source_footer_cannot_overwrite_independent_address_correction(address, matching_reviewed_block):
    previous = replace(draft(ResolvedBlock("footer_text", "This month", text="Source address A")),
                       address_line="Source address A")
    incoming = replace(previous, blocks=(replace(previous.blocks[0], text="Reviewed address B"),),
                       address_line="Reviewed address B")
    current = replace(incoming if matching_reviewed_block else previous, address_line=address)
    before = asdict(current)
    with pytest.raises(ValueError, match="Footer text differs"):
        merge_starting_drafts(current, incoming, previous)
    assert asdict(current) == before


def test_footer_correction_matching_reviewed_address_is_not_a_concurrent_change():
    previous = replace(draft(ResolvedBlock("footer_text", "This month", text="Source address A")),
                       address_line="Source address A")
    incoming = replace(previous, blocks=(replace(previous.blocks[0], text="Reviewed address B"),),
                       address_line="Reviewed address B")
    # The manager already made that exact correction in the report's address.
    current = replace(previous, address_line="Reviewed address B")
    result = merge_starting_drafts(current, incoming, previous)
    assert result.blocks[0].text == result.address_line == "Reviewed address B"
