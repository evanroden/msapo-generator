"""Malformed saved page references cannot strand contract-procedure controls."""
from dataclasses import replace

import pytest

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as standards
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_contract_workflow_ui import APP, button, start
from test_monthly_report_contract_workflows import isolated, file_bytes
from test_monthly_report_workflow_source_guards import imported_procedure
from test_monthly_report_workflow_standards import publish


BROKEN_PAGES = [pytest.param("²", id="superscript"),
                pytest.param("9" * 4301, id="over-integer-limit")]


def procedure(page, *, missing=False, key="business_hours_workflow", digest=None):
    draft, block, assets = imported_procedure()
    source = draft.sources[0]
    source_id = "c" * 64 if missing else source.id
    reference = f"{source_id}:{page}:{source.fingerprint if digest is None else digest}"
    block = approve_all_assets(replace(
        block, key=key, text="Keep the report's synthetic procedure note.",
        asset_captions=("Keep the synthetic picture caption",), references=(reference,),
        asset_provenance=((block.asset_hashes[0], (reference,)),)))
    neighbor = ResolvedBlock("contact_matrix", "This month", text="Keep synthetic contacts.")
    return replace(draft, sources=() if missing else draft.sources,
                   blocks=(block, neighbor)), block, assets


def reopen(draft, assets):
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened == saved
    restored = {ref: library.read_asset(draft.profile.contract, draft.profile.key, ref)
                for ref in assets}
    assert restored == assets
    return reopened, restored


@pytest.mark.parametrize("page", BROKEN_PAGES)
@pytest.mark.parametrize("key", standards.WORKFLOW_KEYS)
def test_reopened_malformed_missing_source_keeps_procedure_controls_available(page, key):
    draft, _, assets = procedure(page, missing=True, key=key)
    saved, assets = reopen(draft, assets)
    draft = saved.draft
    # This is the reachable legacy path: a missing source with a malformed
    # token retains its picture receipt, so the page-admission gate must deny it.
    assert standards._eligible(refresh_asset_source_context(draft.blocks[0], draft.sources))
    before, original_assets = file_bytes(), dict(assets)
    app = start(draft, assets, script=APP.replace("business_hours_workflow", key))
    assert not app.exception
    assert button(app, "Save as contract default").disabled
    assert app.session_state["draft"] == draft
    assert app.session_state["assets"] == original_assets
    app.run()
    assert not app.exception and app.session_state["draft"] == draft
    assert app.session_state["assets"] == original_assets and file_bytes() == before
    assert standards.load_standards(draft.profile.contract).revision == 0
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved


@pytest.mark.parametrize("page", BROKEN_PAGES)
def test_publication_reports_admission_error_without_modifying_saved_work(page):
    draft, _, assets = procedure(page, missing=True)
    saved, assets = reopen(draft, assets)
    draft, block = saved.draft, saved.draft.blocks[0]
    before, original_assets = file_bytes(), dict(assets)
    with pytest.raises(library.LibraryError, match="source page"):
        standards.save_standard(draft, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before and assets == original_assets
    assert standards.load_standards(draft.profile.contract).revision == 0
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved


@pytest.mark.parametrize("page", [
    *BROKEN_PAGES,
    pytest.param("١", id="arabic-digit"),
    pytest.param("１", id="fullwidth-digit"),
    pytest.param("0000001", id="overlong-padding"),
    "0", "-1", "+1", "1 ", "1.0", "", "1:extra", "999999",
])
def test_page_admission_rejects_invalid_or_unavailable_page_identity(page):
    draft, block, assets = procedure(page)
    before, original_assets = file_bytes(), dict(assets)
    assert standards.source_pages_allowed(block, draft.sources, draft.profile) is False
    assert file_bytes() == before and assets == original_assets


@pytest.mark.parametrize("digest", ["", "a" * 63, "g" * 64, "A" * 64])
def test_page_identity_does_not_replace_digest_validation(digest):
    draft, block, _ = procedure("1", digest=digest)
    assert standards.source_pages_allowed(block, draft.sources, draft.profile) is False


@pytest.mark.parametrize("page", ["1", "01", "000001"])
def test_current_approved_pages_and_bounded_legacy_padding_can_still_publish(page):
    draft, block, assets = procedure(page)
    assert standards.source_pages_allowed(block, draft.sources, draft.profile) is True
    state = standards.save_standard(draft, block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert state.revision == 1
    assert state.workflows[0].block.asset_hashes == block.asset_hashes


def test_well_formed_missing_source_still_disables_publication():
    draft, _, assets = procedure("1", missing=True)
    before = file_bytes()
    app = start(draft, assets)
    assert not app.exception and button(app, "Save as contract default").disabled
    assert app.session_state["draft"] == draft and file_bytes() == before


@pytest.mark.parametrize("page", BROKEN_PAGES)
def test_reopened_procedure_can_use_approved_default_without_losing_notes(page):
    _, default, default_assets, state = publish()
    draft, _, assets = procedure(page, missing=True)
    saved, assets = reopen(draft, assets)
    draft, original = saved.draft, saved.draft.blocks[0]
    before, original_assets = file_bytes(), dict(assets)
    app = start(draft, assets)
    assert not app.exception and button(app, "Replace contract default").disabled
    button(app, "Use contract default in this report").click().run()
    assert not app.exception and app.session_state["explicit"]
    recovered = app.session_state["draft"]
    assert recovered.blocks[0].asset_hashes == default.asset_hashes
    assert recovered.blocks[0].text == original.text
    assert set(original.references) <= set(recovered.blocks[0].references)
    assert recovered.blocks[1:] == draft.blocks[1:]
    assert app.session_state["assets"] == original_assets | default_assets
    assert not button(app, "Replace contract default").disabled
    app.run()
    assert not app.exception and app.session_state["draft"] == recovered
    assert file_bytes() == before and standards.load_standards(draft.profile.contract) == state
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved
