"""Publishing a standing diagram must not strip a rejected page's provenance."""
from dataclasses import replace

import pymupdf
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_workflow_standards as workflows
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes, refresh_asset_source_context
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_contract_workflows import isolated, report, image_block, file_bytes


def imported_workflow():
    draft = report()
    with pymupdf.open() as document:
        for text in ("TEST ONLY invented equipment outage response diagram", "TEST ONLY independent sibling technical inspection"):
            document.new_page().insert_text((40, 60), text)
        original = document.tobytes()
    content, _ = sources.ingest(draft.profile, "synthetic-outage-procedure.pdf", original)
    source = replace(content.source, selected_pages=(1, 2))
    source = replace(source, client_page_reviews=tuple((n, page_fingerprint(source, n)) for n in (1, 2)))
    raster = sources.page_image(draft.profile, sources.SourceContent(source), 1).data
    asset = library.asset_reference(raster, "png")
    reference = sources.source_reference(source, 1)
    block = ResolvedBlock("business_hours_workflow", "This month", asset_hashes=(asset,),
                          references=(reference,), asset_provenance=((asset, (reference,)),))
    block = approve_all_assets(refresh_asset_source_context(block, (source,)))
    return replace(draft, sources=(source,), blocks=(block,)), block, {asset: raster}, original


@pytest.mark.parametrize("change", ["deselected", "unreviewed", "sibling_only"])
def test_current_source_page_cannot_be_laundered_into_contract_default(change):
    draft, block, assets, original = imported_workflow()
    source = draft.sources[0]
    if change == "deselected":
        source = replace(source, selected_pages=())
    elif change == "unreviewed":
        source = replace(source, client_page_reviews=())
    else:
        source = replace(source, selected_pages=(2,), client_page_reviews=((2, page_fingerprint(source, 2)),))
    candidate = replace(draft, sources=(source,))
    # Exact same original/raster and block review survive; the independent
    # source-page selection/review gate must nevertheless reject publication.
    assert sources.source_bytes(draft.profile, source) == original
    assert not pending_asset_indexes(block, candidate.sources)
    assert 1 not in source.selected_pages or not page_allowed(source, 1)
    before = file_bytes()
    with pytest.raises(library.LibraryError, match="source page"):
        workflows.save_standard(candidate, block, assets, expected_revision=0,
                                expected_fingerprint=block.fingerprint, confirmed=True)
    assert file_bytes() == before
    assert workflows.load_standards(draft.profile.contract).revision == 0
    assert workflows.apply_defaults(report(), {}) == report()


def test_approved_imported_page_publishes_without_changing_original_or_report():
    draft, block, assets, original = imported_workflow()
    before = file_bytes()
    saved = workflows.save_standard(draft, block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    assert saved.revision == 1
    assert saved.workflows[0].block.references[0].startswith("contract-workflow-standard:v1:")
    assert draft.blocks == (block,) and sources.source_bytes(draft.profile, draft.sources[0]) == original
    assert all(file_bytes()[path] == raw for path, raw in before.items())


def test_unrelated_sibling_review_does_not_block_selected_approved_picture():
    draft, block, assets, original = imported_workflow()
    source = draft.sources[0]
    source = replace(source, selected_pages=(1,), client_page_reviews=((1, page_fingerprint(source, 1)),))
    draft = replace(draft, sources=(source,))
    assert workflows.save_standard(draft, block, assets, expected_revision=0,
        expected_fingerprint=block.fingerprint, confirmed=True).revision == 1
    assert sources.source_bytes(draft.profile, source) == original


def test_manual_reviewed_diagram_without_original_page_link_still_publishes():
    block, assets = image_block()
    draft = report(blocks=(block,))
    assert workflows.save_standard(draft, block, assets, expected_revision=0,
        expected_fingerprint=block.fingerprint, confirmed=True).revision == 1
