"""Routine APIs discover scoped views without a logo/branch choice interface."""
from contextvars import copy_context
from dataclasses import replace
import json

import pytest

from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_preview import section_preview_docx, section_preview_fingerprint
from app.monthly_report_source_view_runtime import render_operation, cache_identity
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


def test_routine_reload_replay_native_and_section_use_saved_view(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    assert library.load_imported_draft(profile.contract, profile.key) == draft
    assert library.starting_contribution(profile.contract, profile.key, period,
        view.original_inspection.sha256) == (draft, True)
    assert build_native_docx(draft, path, asset_loader=loader)
    assert section_preview_docx(draft, 'cover', loader)
    assert cache_identity(draft)


@pytest.mark.parametrize('damage', ['source', 'receipt', 'art', 'month', 'template'])
def test_routine_native_and_preview_fail_closed_without_expected_keyword(sample, damage):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    before = section_preview_fingerprint(draft, 'cover')
    folder = library._profile_path(profile.contract, profile.key)
    if damage == 'source':
        original = library.imported_original(profile.contract, profile.key)
        original.unlink()  # Replace the synthetic path, never mutate a shared immutable object.
        original.write_bytes(b'changed source')
    elif damage == 'receipt':
        next((folder/'imports').glob('*.source-view.json')).write_bytes(b'{}')
    elif damage == 'art':
        value = json.loads((folder/'manifest.json').read_bytes())
        value.pop('source_view_art_reviews')
        (folder/'manifest.json').write_text(json.dumps(value))
    elif damage == 'month':
        draft = replace(draft, period=replace(period, month=period.month % 12 + 1))
    else:
        draft = replace(draft, profile=replace(profile, template='other-template'))
    with pytest.raises(ValueError): build_native_docx(draft, path, asset_loader=loader)
    with pytest.raises(ValueError): section_preview_docx(draft, 'cover', loader)
    try:
        after = section_preview_fingerprint(draft, 'cover')
    except ValueError:
        pass
    else:
        assert after != before


def test_nested_operations_verify_once_and_copied_closed_context_rederives(sample, monkeypatch):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    calls = []
    real = library.verified_render_source_view
    def verify(*args, **kwargs):
        calls.append(True)
        return real(*args, **kwargs)
    monkeypatch.setattr(library, 'verified_render_source_view', verify)
    with render_operation(draft, source_path=path):
        copied = copy_context()
        build_native_docx(draft, path, asset_loader=loader)
        assert len(calls) == 1
    copied.run(build_native_docx, draft, path, asset_loader=loader)
    assert len(calls) == 2


def test_mid_operation_manifest_change_prevents_output(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    manifest = library._profile_path(profile.contract, profile.key)/'manifest.json'
    with pytest.raises(ValueError, match='changed during'):
        with render_operation(draft, source_path=path):
            manifest.write_bytes(manifest.read_bytes()+b'\n')


def test_automatic_generate_and_retry_bind_art_review_and_word_bytes(sample, monkeypatch, tmp_path):
    from app import monthly_report_docx as word, monthly_report_render_jobs as jobs, pdf_converter
    import fitz
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    with pytest.raises(ValueError, match='picture'):
        word.generate_report(draft, asset_loader=loader, acknowledged_fingerprint=draft.fingerprint)
    draft = replace(draft, blocks=tuple(approve_all_assets(block) for block in draft.blocks))
    converted = []
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    def convert(source, **kwargs):
        converted.append(source.read_bytes())
        output = tmp_path/f'adapter-{len(converted)}.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72,72),'Synthetic adapter; not renderer evidence')
            pdf.save(output)
        return output
    monkeypatch.setattr(jobs,'convert_to_pdf',convert)
    package = word.generate_report(draft,asset_loader=loader,acknowledged_fingerprint=draft.fingerprint)
    assert package.source_view_digest == view.receipt_sha256
    assert package.source_view_art_digest
    assert word.retry_report_pdf(draft, package) == package
    for damaged in (replace(package, source_view_art_digest=''),
                    replace(package, docx=package.docx+b'payload'),
                    replace(package, source_view_digest='')):
        with pytest.raises(ValueError): word.retry_report_pdf(draft,damaged)
    assert len(converted) == 1


def test_routine_import_ui_derives_without_caller_keyword_or_logo_choice(sample, monkeypatch):
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_section_ui as ui
    path, view, profile, period, inventory, receipt = sample
    upload = BytesIO(path.read_bytes()); upload.name='synthetic.docx'; upload.size=len(upload.getvalue())
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st,'file_uploader',lambda label,*a,**k: upload if label=='Starting report' else real(label,*a,**k))
    app=AppTest.from_string(f'''
from pathlib import Path
from dataclasses import replace
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
render_section_setup(profile.contract,period,'Synthetic Operator',_field,
                     identity=replace(profile,imported_from=''))
''',default_timeout=60).run()
    assert not app.exception
    for checkbox in app.checkbox:
        if checkbox.label.startswith(('Preserve this native','I checked this artwork')): checkbox.check()
    app.run()
    assert not app.exception
    assert not any('logo' in w.label.lower() or 'branch' in w.label.lower() for w in app.radio)
    button=next(b for b in app.button if b.label=='Continue to this month’s updates')
    assert not button.disabled
    button.click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    loaded=library.load_imported_draft(profile.contract,profile.key)
    assert loaded.profile.imported_from == view.original_inspection.sha256
    assert library.imported_original(profile.contract,profile.key).read_bytes()==path.read_bytes()


def test_record_discovery_never_downgrades_malformed_same_source_month(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    assert library.source_view_replay_recorded(profile.contract, profile.key, period, profile.imported_from)
    other = replace(period, month=period.month % 12 + 1)
    assert not library.source_view_replay_recorded(profile.contract, profile.key, other, profile.imported_from)
    manifest = library._profile_path(profile.contract, profile.key)/'manifest.json'
    value = json.loads(manifest.read_bytes())
    value['source_views'][value['import_source_view']] = {'malformed':True}
    manifest.write_text(json.dumps(value))
    assert library.source_view_replay_recorded(profile.contract, profile.key, period, profile.imported_from)
    with pytest.raises(ValueError):
        library.starting_contribution(profile.contract, profile.key, period, profile.imported_from)


def test_incoming_view_b_never_becomes_expected_authority_for_prior_view_a(sample, tmp_path):
    from docx import Document
    from app.monthly_report_compatibility_view import derive_compatibility_view
    path, view_a, profile, period, inventory, receipt = sample
    draft_a, _ = save_sample(sample)
    different = tmp_path/'different-source.docx'
    document = Document(path)
    document.add_paragraph('Additional synthetic source content.')
    document.save(different)
    view_b = derive_compatibility_view(different.read_bytes())
    assert view_b.original_inspection.sha256 != view_a.original_inspection.sha256
    manifest = library._profile_path(profile.contract, profile.key)/'manifest.json'
    before = manifest.read_bytes()
    assert not library.source_view_replay_recorded(profile.contract,profile.key,period,view_b.original_inspection.sha256)
    assert library.load_imported_draft(profile.contract,profile.key) == draft_a
    with pytest.raises(ValueError):
        library.load_imported_draft(profile.contract,profile.key,source_view=view_b)
    assert manifest.read_bytes() == before


def test_finite_auto_attempt_refuses_unknown_content_without_changing_original(sample):
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_source_view_runtime import derive_import_view, import_candidate
    from test_monthly_report_native_art_review import rewrite, change_xml
    path, view, profile, period, inventory, receipt = sample
    def corrupt(parts):
        def mutate(root):
            wrapper = next(n for n in root.iter() if n.tag.endswith('}AlternateContent'))
            wrapper.set('unrecognized', 'unknown payload')
        change_xml(parts,'word/document.xml',mutate)
    path.write_bytes(rewrite(path.read_bytes(),corrupt))
    before = path.read_bytes(); inspection = inspect_docx(path)
    assert import_candidate(inspection)
    with pytest.raises(ValueError): derive_import_view(path,inspection)
    assert path.read_bytes() == before


@pytest.mark.parametrize('prior', ['legacy', 'other-month-view'])
def test_existing_profile_import_uses_prior_own_identity_and_new_scoped_review(sample, monkeypatch, prior):
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_section_ui as ui
    from app.monthly_report_import import imported_draft
    from app.monthly_report_start_import import build_starting_import
    from test_monthly_report_native_art_lifecycle import plans_for
    path, view, profile, period, inventory, receipt = sample
    if prior == 'legacy':
        plans = plans_for(sample)
        mapped, _ = build_starting_import(path, view.original_inspection, tuple(plans.values()),
            source_view=view, profile=profile, period=period)
        draft = imported_draft(profile, period, 'Synthetic Operator', mapped)
        library.save_profile(profile,expected_revision=0,actor='Synthetic Operator',confirmed=True)
        library.save_report_setup(profile,draft,path,{'sha256':profile.imported_from,'period':period.key},
            assets=mapped.assets,expected_revision=1,actor='Synthetic Operator',confirmed=True,source_draft=draft)
        assert not library.source_view_replay_recorded(profile.contract,profile.key,period,profile.imported_from)
    else:
        save_sample(sample)
        period = replace(period, month=period.month % 12 + 1)
        assert not library.source_view_replay_recorded(profile.contract,profile.key,period,profile.imported_from)
    upload=BytesIO(path.read_bytes());upload.name='synthetic.docx';upload.size=len(upload.getvalue())
    real=ui.st.file_uploader
    monkeypatch.setattr(ui.st,'file_uploader',lambda label,*a,**k:upload if label=='Starting report' else real(label,*a,**k))
    app=AppTest.from_string(f'''
from pathlib import Path
from dataclasses import replace
from test_monthly_report_native_art_review import setup
from app import monthly_report_library as library
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
period=replace(period,month={period.month})
state=library.load_profile(profile.contract,profile.key)
render_section_setup(profile.contract,period,'Synthetic Operator',_field,state=state,identity=profile)
''',default_timeout=60).run()
    assert not app.exception
    assert all('no confirmed photograph or logo role' in e.value for e in app.error)
    checks=[c for c in app.checkbox if c.label.startswith(('Preserve this native','I checked this artwork'))]
    assert len(checks)==4, 'no prior month/legacy review may pre-approve source art'
    for checkbox in checks: checkbox.check()
    app.run()
    button=next(b for b in app.button if b.label=='Continue to this month’s updates')
    assert not button.disabled, [i.value for i in app.info]
    button.click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    loaded=library.load_imported_draft(profile.contract,profile.key)
    assert loaded.period == period
    assert library.source_view_replay_recorded(profile.contract,profile.key,period,profile.imported_from)
    assert all(not b.client_asset_reviews for b in loaded.blocks if b.key != 'client_logo')


@pytest.mark.parametrize('damage', ['source', 'receipt', 'receipt-missing', 'manifest'])
def test_operation_rechecks_all_exact_evidence_before_publication(sample, damage):
    path, view, profile, period, inventory, receipt = sample
    draft, _ = save_sample(sample)
    folder = library._profile_path(profile.contract, profile.key)
    with pytest.raises(ValueError, match='during this operation'):
        with render_operation(draft, source_path=path):
            if damage == 'source':
                path.write_bytes(path.read_bytes() + b'changed')
            elif damage.startswith('receipt'):
                sidecar = next((folder/'imports').glob('*.source-view.json'))
                sidecar.unlink() if damage == 'receipt-missing' else sidecar.write_bytes(b'{}')
            else:
                manifest = folder/'manifest.json'
                manifest.write_bytes(manifest.read_bytes() + b'\n')


@pytest.mark.parametrize('mode', ['full', 'section', 'generate', 'retry'])
@pytest.mark.parametrize('damage', ['source', 'receipt', 'art'])
def test_conversion_cannot_publish_or_relabel_old_output_after_evidence_mutation(
        sample, monkeypatch, tmp_path, mode, damage):
    import fitz
    from app import monthly_report_docx as word, monthly_report_preview as preview
    from app import monthly_report_render_jobs as jobs, pdf_converter
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    draft = replace(draft, blocks=tuple(approve_all_assets(b) for b in draft.blocks))
    folder = library._profile_path(profile.contract, profile.key)
    manifest = folder/'manifest.json'
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    mutate = mode != 'retry'
    calls = []
    def convert(source, **kwargs):
        calls.append(source.read_bytes())
        if mutate:
            if damage == 'source':
                original = library.imported_original(profile.contract, profile.key)
                original.unlink()  # Synthetic path replacement, not a shared object mutation.
                original.write_bytes(b'changed source')
            elif damage == 'receipt':
                next((folder/'imports').glob('*.source-view.json')).write_bytes(b'{}')
            else:
                value = json.loads(manifest.read_bytes())
                value.pop('source_view_art_reviews')
                manifest.write_text(json.dumps(value))
        output = tmp_path/f'synthetic-{len(calls)}.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72,72),'Synthetic adapter only; not renderer evidence')
            pdf.save(output)
        return output
    monkeypatch.setattr(jobs, 'convert_to_pdf', convert)
    if mode == 'retry':
        package = word.generate_report(draft, asset_loader=loader, acknowledged_fingerprint=draft.fingerprint)
        package = replace(package, pdf=None)
        mutate = True
        action = lambda: word.retry_report_pdf(draft, package)
    elif mode == 'generate':
        action = lambda: word.generate_report(draft, asset_loader=loader, acknowledged_fingerprint=draft.fingerprint)
    elif mode == 'full':
        action = lambda: preview.preview_report(draft, loader)
    else:
        action = lambda: preview.preview_section(draft, 'cover', loader)
    with pytest.raises(ValueError):
        action()
    assert len(calls) == (2 if mode == 'retry' else 1)
    assert not list(tmp_path.glob('synthetic-*.pdf'))


@pytest.mark.parametrize('damage', ['replace', 'remove', 'symlink'])
def test_external_original_cannot_hide_stored_original_mutation(sample, damage, tmp_path):
    path, view, profile, period, inventory, receipt = sample
    draft, _ = save_sample(sample)
    stored = library.imported_original(profile.contract, profile.key)
    assert stored.resolve() != path.resolve()
    before = path.read_bytes()
    with pytest.raises(ValueError):
        with render_operation(draft, source_path=path):
            stored.unlink()  # Replace only the synthetic stored path, never its shared immutable object.
            if damage == 'replace': stored.write_bytes(b'changed stored original')
            elif damage == 'symlink': stored.symlink_to(path)
    assert path.read_bytes() == before
