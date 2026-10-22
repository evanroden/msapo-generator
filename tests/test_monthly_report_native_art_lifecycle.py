"""Actual import/store/native APIs for synthetic exact native artwork review."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_import import imported_draft
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_native_art_review import verify_native_art_review, verify_native_art_output
from app.monthly_report_start_import import automatic_section_plans, build_starting_import, StartingReportAnalysis
from test_monthly_report_native_art_review import sample
from test_monthly_report_source_frame_logo_role import raster


def plans_for(sample, receipt=True):
    path, view, profile, period, inventory, review = sample
    return automatic_section_plans(view.original_inspection, StartingReportAnalysis((), 'same', (), (), ()),
        preferred_logos=('client_logo',), source_view=view, native_art_review=review if receipt else None,
        source_path=path, profile=profile, period=period)


def save_sample(sample):
    path, view, profile, period, inventory, receipt = sample
    plans = plans_for(sample)
    assert all(p['approved'] for p in plans.values()), plans
    mapped, _ = build_starting_import(path, view.original_inspection, tuple(plans.values()),
        source_view=view, profile=profile, period=period)
    replacement = raster('purple'); reference = library.asset_reference(replacement, 'png')
    client = approve_all_assets(ResolvedBlock('client_logo', 'Library', asset_hashes=(reference,)))
    mapped = replace(mapped, blocks=(*mapped.blocks, client), assets=(*mapped.assets, (reference, replacement)))
    draft = imported_draft(profile, period, 'Synthetic Operator', mapped)
    library.save_profile(profile, expected_revision=0, actor='Synthetic Operator', confirmed=True)
    review = {'sha256':view.original_inspection.sha256, 'period':period.key, 'native_art_review':receipt}
    library.save_report_setup(profile, draft, path, review, assets=mapped.assets, expected_revision=1,
        actor='Synthetic Operator', confirmed=True, source_draft=draft, source_view=view)
    return draft, lambda key: library.read_asset(profile.contract, profile.key, key)


def test_real_import_save_reload_full_and_cover_native_replay(sample):
    path, view, profile, period, inventory, receipt = sample
    before = path.read_bytes()
    assert not plans_for(sample, False)['cover']['approved']
    draft, loader = save_sample(sample)
    fingerprints = (draft.fingerprint, tuple(b.client_asset_reviews for b in draft.blocks))
    loaded = library.load_imported_draft(profile.contract, profile.key, source_view=view)
    assert loaded == draft
    assert library.imported_native_art_review(profile.contract, profile.key, period, source_view=view) == receipt
    context = verify_native_art_review(path, view, profile, period, receipt)
    output = build_native_docx(loaded, path, asset_loader=loader, source_view=view)
    verify_native_art_output(output, context)
    from app.monthly_report_preview import section_preview_docx
    verify_native_art_output(section_preview_docx(loaded, 'cover', loader, source_view=view), context)
    replay, verified = library.starting_contribution(profile.contract, profile.key, period,
        view.original_inspection.sha256, source_view=view)
    assert verified and replay == draft
    assert (draft.fingerprint, tuple(b.client_asset_reviews for b in draft.blocks)) == fingerprints
    assert path.read_bytes() == before
    assert not any(any(item.original_id in ref for item in inventory.occurrences)
                   for block in draft.blocks for ref in block.references)


@pytest.mark.parametrize('where', ['same-plan', 'other-plan', 'omit'])
def test_exact_preserved_art_cannot_be_mapped_or_omitted(sample, where):
    path, view, profile, period, inventory, receipt = sample
    plans = plans_for(sample)
    target = plans['cover'] if where != 'other-plan' else next(p for k,p in plans.items() if k != 'cover')
    if where == 'omit': target['omit'] = True
    else:
        target['selected'].append(inventory.occurrences[0].original_id)
        target['destinations'][inventory.occurrences[0].original_id] = 'client_logo'
    with pytest.raises(ValueError, match='preservation conflicts'):
        build_starting_import(path, view.original_inspection, tuple(plans.values()),
            source_view=view, profile=profile, period=period)


def test_public_builder_no_context_or_missing_review_does_not_waive_guard(sample):
    path, view, profile, period, inventory, receipt = sample
    plans = plans_for(sample)
    with pytest.raises(ValueError):
        build_starting_import(path, view.original_inspection, tuple(plans.values()), source_view=view)
    plans['cover'].pop('native_art_review')
    with pytest.raises(ValueError, match='no confirmed'):
        build_starting_import(path, view.original_inspection, tuple(plans.values()),
            source_view=view, profile=profile, period=period)


def test_manifest_receipt_tamper_rejected_by_reload_replay_native(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    manifest = library._profile_path(profile.contract, profile.key) / 'manifest.json'
    value = json.loads(manifest.read_bytes())
    next(iter(value['source_view_art_reviews'].values()))['dispositions'].pop()
    manifest.write_text(json.dumps(value))
    for operation in (
        lambda: library.load_imported_draft(profile.contract, profile.key, source_view=view),
        lambda: library.starting_contribution(profile.contract, profile.key, period, view.original_inspection.sha256, source_view=view),
        lambda: build_native_docx(draft, path, asset_loader=loader, source_view=view),
    ):
        with pytest.raises(ValueError): operation()


def test_preservation_does_not_approve_assets_or_waive_pricing_and_pdf_retry(sample, monkeypatch, tmp_path):
    from app import monthly_report_docx as word, monthly_report_render_jobs as jobs, pdf_converter
    import fitz
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    with pytest.raises(ValueError, match='picture'):
        word.generate_report(draft, asset_loader=loader, source_view=view,
                             acknowledged_fingerprint=draft.fingerprint)
    approved = replace(draft, blocks=tuple(approve_all_assets(block) for block in draft.blocks))
    priced = replace(approved, blocks=(*approved.blocks, ResolvedBlock('activity_summary', 'Manual', text='Cost: $500')))
    with pytest.raises(ValueError, match='(?i)pric|cost'):
        word.generate_report(priced, asset_loader=loader, source_view=view,
                             acknowledged_fingerprint=priced.fingerprint)
    converted = []
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    def convert(source, **kwargs):
        converted.append(source.read_bytes())
        out = tmp_path / f'adapter-{len(converted)}.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72,72), 'Synthetic PDF adapter, not layout evidence')
            pdf.save(out)
        return out
    monkeypatch.setattr(jobs, 'convert_to_pdf', convert)
    package = word.generate_report(approved, asset_loader=loader, source_view=view,
                                   acknowledged_fingerprint=approved.fingerprint)
    assert package.pdf and package.docx
    assert word.retry_report_pdf(approved, package, source_view=view).docx == package.docx
    manifest = library._profile_path(profile.contract, profile.key) / 'manifest.json'
    record = json.loads(manifest.read_bytes())
    record.pop('source_view_art_reviews')
    manifest.write_text(json.dumps(record))
    before = len(converted)
    with pytest.raises(ValueError): word.retry_report_pdf(approved, package, source_view=view)
    assert len(converted) == before


def test_save_refuses_actor_mismatch_and_mapped_art_before_publication(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    manifest = library._profile_path(profile.contract, profile.key) / 'manifest.json'
    before = manifest.read_bytes()
    reference = f'docx:{view.original_inspection.sha256}:{inventory.occurrences[0].original_id}'
    changed = replace(draft, blocks=(*draft.blocks, ResolvedBlock('brand_logo', 'Omit', references=(reference,))))
    review = {'sha256':view.original_inspection.sha256, 'period':period.key, 'native_art_review':receipt}
    with pytest.raises(ValueError, match='preservation conflicts'):
        library.save_report_setup(profile, changed, path, review, assets=(), expected_revision=2,
            actor='Synthetic Operator', confirmed=True, source_draft=changed, source_view=view)
    assert manifest.read_bytes() == before
    forged = deepcopy(receipt); forged['visual_review']['actor'] = 'Different Inspector'
    forged['visible_content_review']['actor'] = 'Different Inspector'
    with pytest.raises(ValueError, match='actor'):
        library.save_report_setup(profile, draft, path, dict(review,native_art_review=forged),
            assets=(), expected_revision=2, actor='Synthetic Operator', confirmed=True,
            source_draft=draft, source_view=view)
    assert manifest.read_bytes() == before


@pytest.mark.parametrize('field,value', [('title','Changed report title'), ('template','other-template')])
def test_current_profile_cannot_differ_from_persisted_art_scope(sample, field, value):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    altered = replace(draft, profile=replace(draft.profile, **{field:value}))
    with pytest.raises(ValueError, match='profile or template scope'):
        build_native_docx(altered, path, asset_loader=loader, source_view=view)


def test_legacy_no_view_storage_and_reviewed_fingerprint_are_unchanged(tmp_path, monkeypatch):
    from dataclasses import asdict
    from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
    from app.monthly_report_import import inspect_docx
    from test_monthly_report_start_import import report_file
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path/'legacy-store'))
    path = report_file(tmp_path, activity=('September 2026 completed work',))
    inspection = inspect_docx(path)
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026,9))
    draft = replace(draft, profile=replace(draft.profile, imported_from=inspection.sha256))
    profile = draft.profile
    before = asdict(draft); fingerprint = draft.fingerprint
    library.save_profile(profile, expected_revision=0, actor='Legacy Editor', confirmed=True)
    library.save_report_setup(profile, draft, path,
        {'sha256':inspection.sha256, 'period':draft.period.key}, assets=(), expected_revision=1,
        actor='Legacy Editor', confirmed=True, source_draft=draft)
    loaded = library.load_imported_draft(profile.contract, profile.key)
    assert asdict(loaded) == before and loaded.fingerprint == fingerprint
    raw = json.loads((library._profile_path(profile.contract, profile.key)/'manifest.json').read_bytes())
    assert not {'source_views','source_view_art_reviews','import_source_view'} & set(raw)
    assert 'native_art' not in json.dumps(asdict(loaded))
