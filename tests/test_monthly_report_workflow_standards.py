"""Only saved, reviewed outage diagrams become reusable ENFRA standards."""

from dataclasses import replace
from io import BytesIO

from PIL import Image
import pytest

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as standards
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles


@pytest.fixture(autouse=True)
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def profile(contract="Original contract", key="site"):
    return replace(synthetic_profiles()[0], contract=contract, key=key)


def picture(color="navy"):
    raw = BytesIO()
    Image.new("RGB", (40, 40), color).save(raw, "PNG")
    data = raw.getvalue()
    return library.asset_reference(data, "png"), data


def save_workflows(profile, *, color="navy", reviewed=True, keys=standards.WORKFLOW_KEYS):
    state = library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    reference, data = picture(color)
    blocks = tuple(ResolvedBlock(key, "Library", asset_hashes=(reference,),
                                 asset_captions=("Saved procedure",), references=("accepted-original",))
                   for key in keys)
    if reviewed:
        blocks = tuple(approve_all_assets(block) for block in blocks)
    library.save_import(profile.contract, profile.key, blocks, assets=((reference, data),),
                        expected_revision=state.revision, actor="Synthetic Editor", confirmed=True)
    return blocks, reference, data


def draft(target=None, blocks=(), *, synthetic=False):
    return ReportDraft(target or profile("Another contract"), ReportPeriod(2026, 10),
                       "Synthetic Editor", (), blocks, synthetic=synthetic)


def test_existing_saved_diagrams_seed_once_and_fill_a_different_contract():
    original, reference, data = save_workflows(profile())
    incoming = draft(blocks=(ResolvedBlock("activity_summary", "This month", text="Unrelated work"),))
    assets = {}
    applied = standards.apply_defaults(incoming, assets)
    state = standards.load_standards()
    assert state.revision == 1
    assert {item.key for item in state.workflows} == set(standards.WORKFLOW_KEYS)
    assert all(item.origin_contract == "Original contract" for item in state.workflows)
    assert assets == {reference: data}
    assert applied.blocks[0] == incoming.blocks[0]
    for block in applied.blocks[1:]:
        assert block.asset_hashes == (reference,)
        assert block.asset_captions == ()
        assert block.references[0].startswith("enfra-workflow-standard:")
        assert pending_asset_indexes(block, sources=()) == ()
    assert standards.apply_defaults(applied, assets) == applied
    assert standards.load_standards() == state


def test_different_site_cannot_overwrite_an_established_global_procedure():
    save_workflows(profile())
    first = standards.seed_from_saved_profile("Original contract", "site")
    other, reference, _ = save_workflows(profile("Different contract"), color="red")
    assert standards.seed_from_saved_profile("Different contract", "site") == first
    incoming = draft(profile("Different contract"), other)
    assert standards.apply_defaults(incoming, {}) == incoming
    assert standards.load_standards() == first
    assert all(item.block.asset_hashes != (reference,) for item in first.workflows)


def test_separate_saved_profiles_can_fill_missing_standard_slots_without_replacing():
    save_workflows(profile(), keys=standards.WORKFLOW_KEYS[:1])
    initial = standards.seed_from_saved_profile("Original contract", "site")
    save_workflows(profile("Other contract"), color="red", keys=standards.WORKFLOW_KEYS[1:])
    complete = standards.seed_from_saved_profile("Other contract", "site")
    assert initial.revision == 1 and complete.revision == 2
    assert complete.workflows[0] == initial.workflows[0]
    assert len(complete.workflows) == 2
    assert (standards._path() / "history" / "00000001.json").exists()


def test_unreviewed_or_unsaved_draft_diagrams_do_not_seed_defaults():
    blocks, _, _ = save_workflows(profile(), reviewed=False)
    assert standards.seed_from_saved_profile("Original contract", "site").revision == 0
    incoming = draft(blocks=tuple(approve_all_assets(block) for block in blocks))
    assert standards.apply_defaults(incoming, {}) == incoming
    assert standards.load_standards().revision == 0


def test_text_only_placeholder_does_not_become_a_shared_diagram():
    p = profile()
    library.save_profile(p, expected_revision=0, actor="Editor", confirmed=True)
    library.save_import(p.contract, p.key, (ResolvedBlock(standards.WORKFLOW_KEYS[0], "Library", text="Pending diagram"),),
                        expected_revision=1, actor="Editor", confirmed=True)
    assert standards.seed_from_saved_profile(p.contract, p.key).revision == 0


def test_empty_legacy_omissions_fill_but_existing_custom_procedures_are_pinned():
    save_workflows(profile())
    custom = ResolvedBlock(standards.WORKFLOW_KEYS[0], "This month", text="Existing site instruction")
    incoming = draft(blocks=(custom, ResolvedBlock(standards.WORKFLOW_KEYS[1], "Omit")))
    applied = standards.apply_defaults(incoming, {})
    assert applied.blocks[0] == custom
    assert applied.blocks[1].asset_hashes
    assert applied.blocks[1].source == "Library"


def test_missing_source_asset_never_publishes_half_a_standard():
    _, reference, _ = save_workflows(profile())
    (library._profile_path("Original contract", "site") / "assets" / reference).unlink()
    with pytest.raises(library.LibraryError):
        standards.seed_from_saved_profile("Original contract", "site")
    assert standards.load_standards().revision == 0


def test_tampered_shared_asset_is_rejected_without_changing_the_report():
    save_workflows(profile())
    state = standards.seed_from_saved_profile("Original contract", "site")
    reference = state.workflows[0].block.asset_hashes[0]
    path = standards._path() / "assets" / reference
    path.unlink()
    path.write_bytes(b"changed")
    incoming = draft()
    with pytest.raises(library.LibraryError, match="integrity"):
        standards.apply_defaults(incoming, {})
    assert incoming.blocks == ()


def test_synthetic_report_opening_never_seeds_shared_state():
    save_workflows(profile())
    incoming = draft(synthetic=True)
    assert standards.apply_defaults(incoming, {}) == incoming
    assert standards.load_standards().revision == 0


def test_review_then_save_progress_seeds_a_fresh_contract_without_any_import():
    reference, data = picture("green")
    blocks = tuple(approve_all_assets(ResolvedBlock(key, "This month", asset_hashes=(reference,)))
                   for key in standards.WORKFLOW_KEYS)
    first_report = draft(profile("Saved report contract"), blocks)
    library.save_snapshot(first_report, expected_revision=0, assets=((reference, data),),
                          entered_editor="Synthetic Editor")
    assert not (library._profile_path(first_report.profile.contract, "site") / "manifest.json").exists()
    assets = {}
    applied = standards.apply_defaults(draft(), assets)
    assert {block.key for block in applied.blocks} == set(standards.WORKFLOW_KEYS)
    assert all(block.asset_hashes == (reference,) for block in applied.blocks)
    assert all(pending_asset_indexes(block, sources=()) == () for block in applied.blocks)
    assert assets == {reference: data}
    assert {item.origin_contract for item in standards.load_standards().workflows} == {"Saved report contract"}


def test_latest_reviewed_snapshot_is_preferred_over_older_standing_library():
    source = profile()
    _, old_reference, _ = save_workflows(source)
    new_reference, data = picture("green")
    updated = tuple(approve_all_assets(ResolvedBlock(key, "This month", asset_hashes=(new_reference,)))
                    for key in standards.WORKFLOW_KEYS)
    library.save_snapshot(draft(source, updated), expected_revision=0, assets=((new_reference, data),))
    applied = standards.apply_defaults(draft(source), {})
    assert old_reference != new_reference
    assert all(block.asset_hashes == (new_reference,) for block in applied.blocks)


@pytest.mark.parametrize("synthetic,reviewed", [(True, True), (False, False)])
def test_synthetic_or_unreviewed_saved_report_cannot_seed_global_defaults(synthetic, reviewed):
    reference, data = picture()
    blocks = tuple(ResolvedBlock(key, "This month", asset_hashes=(reference,)) for key in standards.WORKFLOW_KEYS)
    if reviewed:
        blocks = tuple(approve_all_assets(block) for block in blocks)
    library.save_snapshot(draft(profile("Saved only"), blocks, synthetic=synthetic), expected_revision=0,
                          assets=((reference, data),))
    incoming = draft()
    assert standards.apply_defaults(incoming, {}) == incoming
    assert standards.load_standards().revision == 0


def test_saved_import_bootstrap_is_a_source_even_without_standing_versions():
    source = profile()
    library.save_profile(source, expected_revision=0, actor="Editor", confirmed=True)
    reference, data = picture("green")
    blocks = tuple(approve_all_assets(ResolvedBlock(key, "This month", asset_hashes=(reference,)))
                   for key in standards.WORKFLOW_KEYS)
    imported = draft(source, blocks)
    from dataclasses import asdict
    path = library._profile_path(source.contract, source.key)
    value = library._read(path / "manifest.json")
    value["bootstrap"] = asdict(imported)
    value["audit"].append({"action": "report_import", "at": library._now()})
    library._atomic_write(path / "assets" / reference, data)
    library._atomic_write(path / "manifest.json", library._json(value))
    applied = standards.apply_defaults(draft(), {})
    assert all(block.asset_hashes == (reference,) for block in applied.blocks)
    assert len(applied.blocks) == 2


def test_shared_diagrams_do_not_copy_source_site_notes_tables_nodes_or_captions():
    from app.monthly_report_model import OrgChartNode, ReportTable
    source = profile("North contract")
    reference, data = picture()
    mixed = approve_all_assets(ResolvedBlock(
        standards.WORKFLOW_KEYS[0], "This month", text="North-only shutdown instruction",
        rows=(("North-only control room", "555-0100"),),
        extra_tables=(ReportTable(("Site", "Contact"), (("North", "North-only operator"),)),),
        org_nodes=(OrgChartNode("north-manager", "North-only manager", "Supervisor"),),
        asset_hashes=(reference,), asset_captions=("North-only escalation contacts",),
        references=("north-original-source",),
    ))
    library.save_snapshot(draft(source, (mixed,)), expected_revision=0, assets=((reference, data),))
    applied = standards.apply_defaults(draft(profile("South contract")), {})
    shared = applied.blocks[0]
    assert shared.asset_hashes == mixed.asset_hashes
    assert shared.text == ""
    assert shared.rows == shared.extra_tables == shared.org_nodes == shared.asset_captions == ()
    assert shared.references != mixed.references
    assert pending_asset_indexes(shared, sources=()) == ()
    assert "North-only" not in repr(shared)
    assert standards.load_standards().workflows[0].origin_contract == source.contract
    # The original site's persisted report and current custom content stay intact.
    assert library.load_snapshot(source.contract, source.key, ReportPeriod(2026, 10)).draft.blocks == (mixed,)
    original = draft(source, (mixed,))
    assert standards.apply_defaults(original, {}) == original
