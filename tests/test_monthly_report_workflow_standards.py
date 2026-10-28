"""Explicit contract procedures retain review, integrity, revision and history gates."""
from dataclasses import asdict, replace

import pytest

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as standards
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
from app.monthly_report_model import OrgChartNode, ReportPeriod, ReportTable, ResolvedBlock
from test_monthly_report_contract_workflows import isolated, report, image_block, legacy, file_bytes


def publish(contract="Contract A", color="navy", key="business_hours_workflow", revision=0):
    block, assets = image_block(key, color)
    draft = report(contract, (block,))
    state = standards.save_standard(draft, block, assets, expected_revision=revision,
                                   expected_fingerprint=block.fingerprint, confirmed=True)
    return draft, block, assets, state


def test_two_contracts_have_independent_defaults_and_versions():
    a, a_block, a_assets, first = publish()
    b, b_block, b_assets, other = publish("Contract B", "red")
    assert first.revision == other.revision == 1
    for contract, expected, expected_assets in (("Contract A", a_block, a_assets), ("Contract B", b_block, b_assets)):
        assets = {}
        target = report(contract, (ResolvedBlock("activity_summary", "This month", text="Keep monthly work"),), key="another-site")
        before = file_bytes()
        result = standards.apply_defaults(target, assets)
        assert result.blocks[0] == target.blocks[0]
        assert result.blocks[1].asset_hashes == expected.asset_hashes
        assert result.blocks[1].references[0].startswith("contract-workflow-standard:v1:")
        assert not pending_asset_indexes(result.blocks[1], sources=())
        assert assets == expected_assets and file_bytes() == before
        assert standards.apply_defaults(result, assets) == result
    assert standards.load_standards().revision == 0
    assert standards.apply_defaults(report("Contract C"), {}) == report("Contract C")


def test_replacement_changes_only_future_defaults_not_saved_reports_or_other_contract():
    a, block, assets, first = publish()
    b, _, _, other = publish("Contract B", "red")
    saved = library.save_snapshot(a, expected_revision=0, assets=tuple(assets.items()))
    _, new, _, updated = publish(color="green", revision=1)
    assert updated.revision == 2 and updated.workflows[0].block.asset_hashes == new.asset_hashes
    assert standards.load_standards("Contract B") == other
    assert library.load_snapshot(a.profile.contract, a.profile.key, a.period) == saved
    assert standards.apply_defaults(a, {}) == a
    history = standards._path("Contract A") / "history"
    assert library._read(history / "00000001.json")["workflows"][0]["block"]["asset_hashes"] == list(block.asset_hashes)
    assert sorted(p.name for p in history.iterdir()) == ["00000001.json", "00000002.json"]


def test_explicit_save_is_idempotent_and_never_replaces_another_slot():
    draft, block, assets, first = publish()
    again = standards.save_standard(draft, block, assets, expected_revision=1,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert again == first
    _, _, _, second = publish(key="after_hours_workflow", color="red", revision=1)
    assert second.revision == 2 and second.workflows[0] == first.workflows[0]


@pytest.mark.parametrize("kind", ["unreviewed", "omitted", "text_only", "synthetic", "unconfirmed", "unnamed", "stale_block", "wrong_block", "bad_revision"])
def test_invalid_publication_retains_every_original(kind):
    block, assets = image_block()
    draft = report(blocks=(block,))
    kwargs = dict(expected_revision=0, expected_fingerprint=block.fingerprint, confirmed=True)
    if kind == "unreviewed":
        block = replace(block, client_reviewed_fingerprint="", client_asset_reviews=())
    elif kind == "omitted":
        block = replace(block, source="Omit")
    elif kind == "text_only":
        block = ResolvedBlock(block.key, "This month", text="Awaiting a diagram")
    elif kind == "synthetic":
        draft = replace(draft, synthetic=True)
    elif kind == "unconfirmed":
        kwargs["confirmed"] = False
    elif kind == "unnamed":
        draft = replace(draft, prepared_by="")
    elif kind == "stale_block":
        kwargs["expected_fingerprint"] = "outdated"
    elif kind == "bad_revision":
        kwargs["expected_revision"] = True
    if kind not in {"stale_block", "wrong_block"}:
        draft = replace(draft, blocks=(block,))
        kwargs["expected_fingerprint"] = block.fingerprint
    if kind == "wrong_block":
        draft = replace(draft, blocks=())
    before = file_bytes()
    with pytest.raises(ValueError):
        standards.save_standard(draft, block, assets, **kwargs)
    assert file_bytes() == before
    assert standards.load_standards("Contract A").revision == 0


def test_stale_revision_does_not_overwrite_current_standard():
    first = publish()[-1]
    block, assets = image_block(color="red")
    before = file_bytes()
    with pytest.raises(library.RevisionConflict, match="changed"):
        standards.save_standard(report(blocks=(block,)), block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert standards.load_standards("Contract A") == first and file_bytes() == before


@pytest.mark.parametrize("bad", ["missing", "tampered"])
def test_source_integrity_failure_never_publishes_a_partial_default(bad):
    block, assets = image_block()
    if bad == "missing":
        assets = {}
    else:
        assets = {ref: b"changed" for ref in assets}
    before = file_bytes()
    with pytest.raises(ValueError):
        standards.save_standard(report(blocks=(block,)), block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before and standards.load_standards("Contract A").revision == 0


def test_default_reads_are_atomic_on_later_corrupt_asset():
    publish()
    _, block, _, _ = publish(key="after_hours_workflow", color="red", revision=1)
    ref = block.asset_hashes[0]
    path = standards._path("Contract A") / "assets" / ref
    path.unlink()
    path.write_bytes(b"changed")
    incoming, assets = report(), {"previous": b"unchanged"}
    with pytest.raises(library.LibraryError, match="integrity"):
        standards.apply_defaults(incoming, assets)
    assert incoming.blocks == () and assets == {"previous": b"unchanged"}


def test_populated_and_empty_omitted_slots_remain_pinned():
    publish()
    omitted = ResolvedBlock("business_hours_workflow", "Omit")
    custom = ResolvedBlock("business_hours_workflow", "This month", text="Report-only procedure")
    for block in (omitted, custom):
        before = report(blocks=(block,))
        assert standards.apply_defaults(before, {}) == before


def test_default_does_not_copy_site_notes_contacts_nodes_or_captions():
    block, assets = image_block()
    mixed = approve_all_assets(replace(block, text="Site-only note", rows=(("Site-only", "Contact"),),
        extra_tables=(ReportTable(("Site",), (("Site-only",),)),),
        org_nodes=(OrgChartNode("manager", "Site-only person", "Supervisor"),),
        asset_captions=("Site-only caption",), references=("site-only-source",)))
    draft = report(blocks=(mixed,))
    saved = standards.save_standard(draft, mixed, assets, expected_revision=0,
                                    expected_fingerprint=mixed.fingerprint, confirmed=True)
    pinned = saved.workflows[0].block
    assert pinned.asset_hashes == mixed.asset_hashes
    assert pinned.text == "" and pinned.rows == pinned.extra_tables == pinned.org_nodes == pinned.asset_captions == ()
    assert "Site-only" not in repr(pinned) and not pending_asset_indexes(pinned)
    assert standards.apply_defaults(draft, {}) == draft


def test_explicit_use_preserves_adjacent_content_and_rejects_stale_actions():
    _, expected, raw, state = publish()
    existing = ResolvedBlock("business_hours_workflow", "Omit", text="Keep note",
        extra_tables=(ReportTable(("Operator",), (("Synthetic contact",),)),), references=("note-source",))
    draft, assets = report(blocks=(existing,)), {}
    result = standards.use_standard(draft, existing, assets, expected_revision=1,
                                    expected_fingerprint=existing.fingerprint)
    assert result.source == "This month" and result.asset_hashes == expected.asset_hashes
    assert result.text == existing.text and result.extra_tables == existing.extra_tables
    assert "note-source" in result.references and assets == raw
    with pytest.raises(library.RevisionConflict):
        standards.use_standard(draft, existing, {}, expected_revision=0, expected_fingerprint=existing.fingerprint)
    with pytest.raises(library.RevisionConflict):
        standards.use_standard(draft, existing, {}, expected_revision=1, expected_fingerprint="old")
    assert standards.load_standards("Contract A") == state


def test_legacy_adoption_is_explicit_origin_scoped_and_nondestructive():
    item = legacy()
    before = file_bytes()
    assert standards.legacy_candidate("Contract B", item.key) is None
    with pytest.raises(library.RevisionConflict):
        standards.adopt_legacy(report("Contract B"), item.key, expected_revision=0,
                               expected_legacy_fingerprint=item.block.fingerprint, confirmed=True)
    with pytest.raises(library.RevisionConflict):
        standards.adopt_legacy(report(), item.key, expected_revision=0,
                               expected_legacy_fingerprint="old", confirmed=True)
    assert file_bytes() == before
    state = standards.adopt_legacy(report(), item.key, expected_revision=0,
                                  expected_legacy_fingerprint=item.block.fingerprint, confirmed=True)
    assert state.revision == 1 and state.workflows[0].block.asset_hashes == item.block.asset_hashes
    assert all(file_bytes()[path] == raw for path, raw in before.items())
    assert standards.load_standards().revision == 1
    assert standards.apply_defaults(report("Contract B"), {}) == report("Contract B")
    assert standards.apply_defaults(report(), {}).blocks[0].asset_hashes == item.block.asset_hashes


def test_contract_spelling_normalization_is_not_a_fuzzy_alias():
    state = publish()[-1]
    assert standards.load_standards("  CONTRACT   A ") == state
    assert standards.load_standards("Contract-A").revision == 0


def test_foreign_contract_manifest_fails_closed():
    publish()
    path = standards._path("Contract A") / "manifest.json"
    value = library._read(path)
    value["contract"] = "contract b"
    library._atomic_write(path, library._json(value))
    with pytest.raises(library.LibraryError, match="could not be read"):
        standards.apply_defaults(report(), {})


def test_snapshot_reopen_and_rollover_retain_approved_versions_and_exclusions():
    from app.monthly_report_setup import new_month_draft
    publish()
    assets = {}
    chosen = standards.apply_defaults(report(), assets)
    saved = library.save_snapshot(chosen, expected_revision=0, assets=tuple(assets.items()))
    publish(color="red", revision=1)
    reloaded = library.load_snapshot(chosen.profile.contract, chosen.profile.key, chosen.period)
    assert reloaded == saved
    future = new_month_draft(reloaded.draft, ReportPeriod(2026, 11))
    assert future.blocks[0].asset_hashes == chosen.blocks[0].asset_hashes
    omitted = replace(chosen, blocks=(replace(chosen.blocks[0], source="Omit"),))
    future_omitted = new_month_draft(omitted, ReportPeriod(2026, 11))
    assert standards.apply_defaults(future_omitted, {}) == future_omitted
    assert future_omitted.blocks[0].source == "Omit"


@pytest.mark.parametrize("scope", ["profile", "section"])
def test_excluded_organization_cannot_receive_missing_default_pages(scope):
    from app.monthly_report_model import profile_sections
    publish()
    current = report()
    current = replace(current, sections=profile_sections(current.profile))
    if scope == "profile":
        current = replace(current, profile=replace(current.profile, excluded_sections=("organization",)))
    else:
        current = replace(current, sections=tuple(replace(s, included=False) if s.key == "organization" else s
                                                  for s in current.sections))
    assets, before = {}, file_bytes()
    assert standards.apply_defaults(current, assets) == current
    assert assets == {} and file_bytes() == before


def test_fresh_guided_omission_requires_explicit_use_and_then_survives_rollover():
    from types import SimpleNamespace
    from app.monthly_report_guided import _initial_draft, complete_guided_sections
    from app.monthly_report_setup import new_month_draft
    publish()
    profile = report().profile
    state = SimpleNamespace(profile=profile, block=lambda key: None)
    current = complete_guided_sections(_initial_draft(state, ReportPeriod(2026, 10), "Synthetic Editor"))
    block = next(b for b in current.blocks if b.key == "business_hours_workflow")
    assert block.source == "Omit"
    assets, before = {}, file_bytes()
    # The initializer's Omit is deliberately indistinguishable from a saved
    # choice. Reuse stays explicit instead of silently overriding it.
    assert standards.apply_defaults(current, assets) == current
    assert assets == {} and file_bytes() == before
    used = standards.use_standard(current, block, assets, expected_revision=1,
                                   expected_fingerprint=block.fingerprint)
    current = replace(current, blocks=tuple(used if b.key == block.key else b for b in current.blocks))
    saved = library.save_snapshot(current, expected_revision=0, assets=tuple(assets.items()))
    restored = library.load_snapshot(profile.contract, profile.key, current.period)
    assert restored == saved
    next_month = new_month_draft(restored.draft, ReportPeriod(2026, 11))
    assert next(b for b in next_month.blocks if b.key == block.key).asset_hashes == used.asset_hashes
    assert standards.apply_defaults(next_month, {}) == next_month


def test_disappeared_source_review_cannot_be_promoted_to_contract_default():
    block, assets = image_block()
    reference = "a" * 64 + ":1:" + "b" * 64
    block = approve_all_assets(replace(block, references=(reference,),
                                      asset_provenance=((block.asset_hashes[0], (reference,)),)))
    draft = report(blocks=(block,))
    assert not pending_asset_indexes(block)
    before = file_bytes()
    with pytest.raises(ValueError, match="review every"):
        standards.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before
