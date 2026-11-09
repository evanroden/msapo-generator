"""A reused master must not distribute its attached schema identifiers or locations."""
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from lxml import etree
import pytest

from app import monthly_report_designs as designs, monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_native_layout import _build_native_docx
from app.monthly_report_native_package import W, passive_docx
from app.monthly_report_preview import section_preview_docx
from test_monthly_report_designs import master_reference


SL = 'http://schemas.openxmlformats.org/schemaLibrary/2006/main'
MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
W14 = 'http://schemas.microsoft.com/office/word/2010/wordml'
OTHER = 'urn:synthetic:unrelated-extension'
PRIVATE_URI = 'urn:synthetic:prior-contract:schema-identifier'
PRIVATE_PATH = 'file:///synthetic/prior-contract/schema-location.xsd'
CURRENT_TEXT = 'Current Activity reviewed for the receiving contract.'


def _master(tmp_path, mode):
    path = master_reference(tmp_path)
    doc = Document(path)
    settings = doc.settings.element
    attached = etree.Element(f'{{{W}}}attachedSchema')
    attached.set(f'{{{W}}}val', PRIVATE_URI)
    schema_library = etree.Element(f'{{{SL}}}schemaLibrary', nsmap={'sl': SL})
    schema = etree.SubElement(schema_library, f'{{{SL}}}schema')
    schema.set(f'{{{SL}}}uri', PRIVATE_URI)
    schema.set(f'{{{SL}}}schemaLocation', PRIVATE_PATH)
    if mode == 'direct':
        settings.insert_element_before(attached, 'w:themeFontLang')
        settings.insert_element_before(schema_library, 'w:shapeDefaults')
    elif mode == 'compatibility':
        wrapper = etree.Element(f'{{{MC}}}AlternateContent', nsmap={'mc': MC, 'w14': W14})
        choice = etree.SubElement(wrapper, f'{{{MC}}}Choice', Requires='w14')
        choice.append(attached)
        fallback = etree.SubElement(wrapper, f'{{{MC}}}Fallback')
        fallback.append(schema_library)
        settings.insert_element_before(wrapper, 'w:themeFontLang')
    elif mode == 'lookalikes':
        wrapper = etree.Element(f'{{{MC}}}AlternateContent', nsmap={'mc': MC, 'other': OTHER})
        choice = etree.SubElement(wrapper, f'{{{MC}}}Choice', Requires='other')
        for local in ('attachedSchema', 'schemaLibrary'):
            etree.SubElement(choice, f'{{{OTHER}}}{local}').set('value', 'Preserved')
        etree.SubElement(wrapper, f'{{{MC}}}Fallback')
        settings.insert_element_before(wrapper, 'w:themeFontLang')
    doc.save(path)
    return path


def _draft(profile):
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    activity = next(s for s in draft.sections if s.key == 'activity').blocks[0].key
    return replace(draft, blocks=tuple(replace(b, text=CURRENT_TEXT) if b.key == activity else b for b in draft.blocks))


def _verify_word(raw):
    doc = Document(BytesIO(raw))
    assert CURRENT_TEXT in [p.text for p in doc.paragraphs]
    with ZipFile(BytesIO(raw)) as archive:
        settings = etree.fromstring(archive.read('word/settings.xml'))
        assert settings.find(f'{{{W}}}zoom') is not None
        assert settings.find(f'{{{W}}}defaultTabStop') is not None
        for name in archive.namelist():
            part = archive.read(name)
            assert PRIVATE_URI.encode() not in part, name
            assert PRIVATE_PATH.encode() not in part, name
        assert not list(settings.iter(f'{{{W}}}attachedSchema', f'{{{SL}}}schemaLibrary'))


@pytest.mark.parametrize('mode', ['direct', 'compatibility'])
@pytest.mark.parametrize('section', [None, 'activity'])
def test_full_and_section_word_remove_prior_master_schema_declarations(tmp_path, mode, section):
    master = _master(tmp_path, mode)
    original = master.read_bytes()
    profile = replace(synthetic_profiles()[0], contract='Synthetic Receiving Contract')
    raw = _build_native_docx(_draft(profile), master, master=True, section_key=section)
    _verify_word(raw)
    assert master.read_bytes() == original


@pytest.mark.parametrize('mode', ['clean', 'lookalikes'])
def test_clean_settings_and_foreign_names_remain_byte_identical(tmp_path, mode):
    path = _master(tmp_path, mode)
    with ZipFile(path) as source, ZipFile(BytesIO(passive_docx(path))) as clone:
        assert source.read('word/settings.xml') == clone.read('word/settings.xml')


def test_public_storage_installed_master_keeps_original_and_report_versions(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    path = _master(tmp_path, 'direct')
    original = path.read_bytes()
    designs.install_master(path, actor='Synthetic Editor', expected_revision=0)
    profile = designs.pin(replace(synthetic_profiles()[0], contract='Synthetic Receiving Contract'))
    saved = library.save_snapshot(_draft(profile), expected_revision=0)
    updated = library.save_snapshot(replace(saved.draft, prepared_by='Synthetic Reviewer'), expected_revision=1)
    reopened = library.load_snapshot(profile.contract, profile.key, updated.draft.period)
    assert reopened == updated
    _verify_word(assemble_docx(reopened.draft, acknowledged_fingerprint=reopened.draft.fingerprint))
    _verify_word(section_preview_docx(reopened.draft, 'activity'))
    assert designs.source_for(profile).read_bytes() == path.read_bytes() == original
    assert library.load_snapshot_version(profile.contract, profile.key, saved.draft.period, 1) == saved
