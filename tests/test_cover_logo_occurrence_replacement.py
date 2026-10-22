"""A real logo replacement must keep an explicitly mapped native occurrence."""

from dataclasses import replace
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, asset_context, pending_asset_indexes
from app.monthly_report_cover_ui import replace_cover_picture
from app.monthly_report_import import ImportMapping, inspect_docx, map_items
from app.monthly_report_native_layout import build_native_docx
from test_cover_branding_contracts import mark
from test_cover_review_regressions import _draft, _header_images, _header_source


def _replace_in_editor(monkeypatch, block, assets, route):
    upload = BytesIO(mark())
    upload.name, upload.size = "synthetic-replacement.png", len(upload.getvalue())
    if route == "cover":
        return replace_cover_picture(block, upload.getvalue(), ".png", assets)
    from app import monthly_report_guided as guided
    real_upload = guided.st.file_uploader
    def uploader(label, *args, **kwargs):
        real_upload(label, *args, **kwargs)
        return upload
    monkeypatch.setattr(guided.st, "file_uploader", uploader)
    app = AppTest.from_string('''
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_model import layout_blocks, synthetic_profiles
from app.monthly_report_ui import _field
profile = synthetic_profiles()[0]
block, assets = st.session_state['block'], st.session_state['assets']
state = library.load_profile(profile.contract, profile.key)
spec = next(s for s in layout_blocks() if s.key == block.key)
if ROUTE == 'guided':
    from app.monthly_report_guided import _edit_content
    result = _edit_content(spec, block, state, 'mapped_logo', assets, _field, manage_saved_pictures=False)
elif ROUTE == 'detailed':
    from app.monthly_report_editor import _block_editor
    result = _block_editor(spec, state, {block.key: block}, 'Replace once', 'mapped_logo', assets, _field)
else:
    from app.monthly_report_branding_ui import offer_logo
    result = offer_logo(block, profile.contract, 'mapped_logo', assets)
st.session_state['block'] = result
'''.replace('ROUTE', repr(route)))
    app.session_state['block'], app.session_state['assets'] = block, assets
    app.run()
    assert not app.exception
    if route != 'detailed':
        label = "Use this replacement in this report" if route == "guided" else "Use this logo in this report"
        next(button for button in app.button if button.label == label).click().run()
        assert not app.exception
    assets.update(app.session_state['assets'])
    return app.session_state['block']


@pytest.mark.parametrize('route', ['cover', 'guided', 'detailed', 'shared'])
@pytest.mark.parametrize('master', [False, True])
def test_replacement_keeps_mapped_header_occurrence_after_save_reload(monkeypatch, tmp_path, route, master):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    source, old_company, unrelated = _header_source(tmp_path, 'none')
    original = source.read_bytes()
    inspection = inspect_docx(source)
    header = next(item for item in inspection.items if item.kind == 'image' and item.part.startswith('word/header'))
    assert header.image_role == 'header_artwork'
    mapped = map_items(source, inspection, (ImportMapping(header.id, 'brand_logo'),))
    block = approve_all_assets(mapped.blocks[0])
    assets = dict(mapped.assets)
    profile = _draft(block).profile
    library.save_profile(profile, expected_revision=0, actor='Synthetic Reviewer', confirmed=True)
    if route == 'shared':
        raw = mark()
        reference = library.asset_reference(raw, 'png')
        logo = branding.BrandLogo('enfra', 'Synthetic ENFRA', (), reference,
            'https://example.invalid/brand', 'https://example.invalid/logo.png', '2026-10-20')
        branding.save_branding((logo,), {reference: raw}, expected_revision=0,
                              actor='Synthetic Reviewer', confirmed=True)
    replaced = _replace_in_editor(monkeypatch, block, assets, route)
    assert replaced.asset_hashes != block.asset_hashes, 'Production replacement route must process the new bytes'
    assert replaced.references == block.references, 'Replacing artwork must retain its exact mapped source occurrence'
    assert replaced.asset_provenance != block.asset_provenance, 'Old image evidence is not evidence for replacement bytes'
    assert asset_context(replaced, 0) == (), 'Placement identity must not be misattributed as artwork provenance'
    if route != 'shared':
        assert not replaced.client_reviewed_fingerprint, 'New custom bytes still require review'
        assert pending_asset_indexes(replaced) == (0,)
    report = _draft(approve_all_assets(replaced))
    library.save_snapshot(report, expected_revision=0, assets=tuple(assets.items()), entered_editor='Synthetic Reviewer')
    loaded = library.load_snapshot(profile.contract, profile.key, report.period).draft
    loader = lambda ref: library.read_asset(profile.contract, profile.key, ref)
    result = _header_images(build_native_docx(loaded, source, asset_loader=loader, master=master))
    assert result[0] == loader(replaced.asset_hashes[0]) != old_company
    assert result[1:] == (() if master else unrelated)
    assert source.read_bytes() == original


@pytest.mark.parametrize('slot', ['brand_logo', 'client_logo', 'cover_photo'])
def test_replacement_preserves_only_logo_placement_not_source_evidence(slot):
    from app.monthly_report_model import ResolvedBlock
    reference = 'docx:' + 'a' * 64 + ':item-0004'
    old = approve_all_assets(ResolvedBlock(slot, 'Library', asset_hashes=('old.png',),
        references=(reference, 'old-evidence:1:source-hash', 'report-period:2026-10')))
    updated = replace_cover_picture(old, mark(), '.png', {})
    assert updated.references == ((reference,) if slot != 'cover_photo' else ())
    assert asset_context(updated, 0) == ()
    assert pending_asset_indexes(updated) == (0,)
