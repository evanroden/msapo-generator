"""Preservation UI is scoped source-art inspection, not logo selection."""
from streamlit.testing.v1 import AppTest

from app.monthly_report_editor import _signature
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_start_import import analyze_starting_report
from test_monthly_report_native_art_review import sample
from test_monthly_report_start_import import start_app, report_file, PERIOD


def test_preservation_panel_enumerates_every_occurrence_and_requires_every_group(sample):
    path, view, profile, period, inventory, receipt = sample
    app = AppTest.from_string(f'''
from pathlib import Path
import streamlit as st
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import _native_art_preservation_review
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
st.session_state['receipt'] = _native_art_preservation_review(path, view, profile, period,
    'Synthetic Operator', 'synthetic', _field)
''', default_timeout=30).run()
    assert not app.exception
    assert app.session_state['receipt'] is None
    assert len(app.checkbox) == 2, 'two same-byte images share display only; footer is another group'
    assert not app.radio and not app.selectbox
    assert len(app.get('popover')) == 2, 'technical source targets stay behind optional details'
    assert all(panel.proto.popover.label == 'Source details' for panel in app.get('popover'))
    captions = ' '.join(x.value for x in app.caption)
    assert all(item.original_id in captions for item in inventory.occurrences)
    app.checkbox[0].check().run()
    assert app.session_state['receipt'] is None
    for checkbox in app.checkbox:
        checkbox.check()
    app.run()
    assert not app.exception
    assert app.session_state['receipt'] == receipt


def test_ordinary_pending_plan_signature_and_draft_state_stay_legacy(monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=('September 2026 ordinary source',))
    app = start_app(monkeypatch, tmp_path, path)
    state = app.session_state.filtered_state
    signature_key = next(key for key in state if key.endswith('_analysis_signature'))
    plans_key = next(key for key in state if key.endswith('_section_plans'))
    profile = synthetic_profiles()[0]
    analysis = analyze_starting_report(inspect_docx(path), profile, PERIOD, profile.facilities)
    assert state[signature_key] == _signature((analysis, (), False))
    # A staged non-widget marker proves ordinary no-view reruns do not reseed.
    state[plans_key]['activity']['local_pending_marker'] = 'preserve ordinary edit'
    app.session_state[plans_key] = state[plans_key]
    app.run()
    assert not app.exception
    assert app.session_state[plans_key]['activity']['local_pending_marker'] == 'preserve ordinary edit'


def test_optional_source_view_ui_saves_real_review_without_logo_choice(sample, monkeypatch):
    from io import BytesIO
    from app import monthly_report_section_ui as ui, monthly_report_library as library
    path, view, profile, period, inventory, receipt = sample
    upload = BytesIO(path.read_bytes()); upload.name = 'synthetic-source.docx'; upload.size = len(upload.getvalue())
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label,*args,**kwargs:
        upload if label == 'Starting report' else real(label,*args,**kwargs))
    app = AppTest.from_string(f'''
from pathlib import Path
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
from dataclasses import replace
render_section_setup(profile.contract, period, 'Synthetic Operator', _field,
                     identity=replace(profile, imported_from=''), source_view=view)
''', default_timeout=60).run()
    assert not app.exception
    button = next(b for b in app.button if b.label == 'Continue to this month’s updates')
    assert button.disabled
    assert not any('Your sites and sections are ready' in x.value for x in app.success)
    app.checkbox[0].check().run()
    assert next(b for b in app.button if b.label == 'Continue to this month’s updates').disabled
    for checkbox in app.checkbox:
        if checkbox.label.startswith('I reviewed this artwork and want to keep it unchanged'):
            checkbox.check()
    app.run()
    assert not app.exception
    assert not any('logo' in widget.label.lower() or 'branch' in widget.label.lower() for widget in app.radio)
    button = next(b for b in app.button if b.label == 'Continue to this month’s updates')
    assert not button.disabled, [x.value for x in app.info]
    button.click().run()
    assert not app.exception and not app.error
    loaded = library.load_imported_draft(profile.contract, profile.key, source_view=view)
    assert loaded.profile.imported_from == view.original_inspection.sha256
    assert library.imported_original(profile.contract, profile.key).read_bytes() == path.read_bytes()
    saved = library.imported_native_art_review(profile.contract, profile.key, period, source_view=view)
    assert saved['dispositions'] == receipt['dispositions']


def test_encoded_display_metadata_cannot_be_reviewed_as_plain_thumbnail(sample):
    from io import BytesIO
    from PIL import Image, PngImagePlugin
    from test_monthly_report_native_art_review import rewrite
    path, view, profile, period, inventory, receipt = sample
    target = inventory.occurrences[0].rendition_representations[0].media_part
    def add_metadata(parts):
        with Image.open(BytesIO(parts[target])) as image:
            out = BytesIO(); metadata = PngImagePlugin.PngInfo()
            metadata.add_text('Description', 'Synthetic metadata requiring rendered review')
            image.save(out, format='PNG', pnginfo=metadata)
        parts[target] = out.getvalue()
    path.write_bytes(rewrite(path.read_bytes(), add_metadata))
    app = AppTest.from_string(f'''
from pathlib import Path
import streamlit as st
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import _native_art_preservation_review
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
st.session_state['receipt'] = _native_art_preservation_review(path, view, profile, period,
    'Synthetic Operator', 'synthetic', _field)
''', default_timeout=30).run()
    assert not app.exception
    assert app.error and app.session_state['receipt'] is None


def test_optional_heavy_ui_uses_existing_admission_but_default_does_not(monkeypatch):
    from contextlib import contextmanager
    from app import monthly_report_section_ui as ui, monthly_report_render_jobs as jobs
    entered = []
    @contextmanager
    def slot(**kwargs):
        entered.append(kwargs)
        yield
    monkeypatch.setattr(jobs, 'work_slot', slot)
    @ui._source_view_admission
    def render(*, source_view=None): return 'rendered'
    assert render() == 'rendered' and entered == []
    assert render(source_view=object()) == 'rendered'
    assert entered == [{'preview':True}]


def test_empty_native_art_inventory_does_not_add_pending_gate(sample, monkeypatch):
    from io import BytesIO
    from lxml import etree as ET
    from app import monthly_report_section_ui as ui
    from test_monthly_report_native_art_review import rewrite, setup
    path, _, original_profile, period, _, _ = sample
    def remove_header_pictures(parts):
        for name in tuple(parts):
            if name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'):
                root = ET.fromstring(parts[name])
                for node in tuple(root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing')):
                    node.getparent().remove(node)
                parts[name] = ET.tostring(root)
    path.write_bytes(rewrite(path.read_bytes(), remove_header_pictures))
    from dataclasses import replace
    from app.monthly_report_compatibility_view import derive_compatibility_view
    from app.monthly_report_native_art_review import native_art_inventory
    import test_monthly_report_native_art_review as fixtures
    def empty_setup(source):
        view = derive_compatibility_view(source.read_bytes())
        profile = replace(original_profile, imported_from=view.original_inspection.sha256)
        inventory = native_art_inventory(source, view, profile, period)
        return source, view, profile, period, inventory, None
    monkeypatch.setattr(fixtures, 'setup', empty_setup)
    _, view, profile, period, inventory, _ = empty_setup(path)
    assert not inventory.occurrences
    upload = BytesIO(path.read_bytes()); upload.name = 'synthetic-no-native-art.docx'; upload.size = len(upload.getvalue())
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label,*args,**kwargs:
        upload if label == 'Starting report' else real(label,*args,**kwargs))
    app = AppTest.from_string(f'''
from pathlib import Path
from dataclasses import replace
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
render_section_setup(profile.contract, period, 'Synthetic Operator', _field,
    identity=replace(profile, imported_from=''), source_view=view)
''', default_timeout=60).run()
    assert not app.exception
    assert not next(b for b in app.button if b.label == 'Continue to this month’s updates').disabled
    assert not any('Review the native page artwork' in x.value for x in app.info)


def test_unavailable_native_thumbnail_keeps_continue_disabled(sample, monkeypatch):
    from io import BytesIO
    from app import monthly_report_section_ui as ui, monthly_report_import as imports
    path, *_ = sample
    upload = BytesIO(path.read_bytes()); upload.name = 'synthetic-blocked-art.docx'; upload.size = len(upload.getvalue())
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label,*args,**kwargs:
        upload if label == 'Starting report' else real(label,*args,**kwargs))
    real_read = imports._read_import_image
    def blocked(path, item, *args, **kwargs):
        if item.part.startswith(('word/header', 'word/footer')):
            raise ValueError('Synthetic thumbnail failure')
        return real_read(path, item, *args, **kwargs)
    monkeypatch.setattr(imports, '_read_import_image', blocked)
    app = AppTest.from_string(f'''
from pathlib import Path
from dataclasses import replace
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
path, view, profile, period, inventory, _ = setup(Path({str(path)!r}))
render_section_setup(profile.contract, period, 'Synthetic Operator', _field,
    identity=replace(profile, imported_from=''), source_view=view)
''', default_timeout=60).run()
    assert not app.exception
    assert app.error
    assert next(b for b in app.button if b.label == 'Continue to this month’s updates').disabled
    assert not any('Your sites and sections are ready' in x.value for x in app.success)
