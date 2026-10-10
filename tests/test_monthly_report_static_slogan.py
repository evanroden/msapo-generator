"""Verified company artwork is not an alternate client-logo replacement slot."""
from dataclasses import replace
from io import BytesIO
import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw

from app import monthly_report_static_branding as slogan
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, default_sections
from app.monthly_report_native_layout import build_native_docx


def picture(size, text, color):
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    draw.text((4, 4), text, fill='black')
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def source_and_draft(tmp_path):
    source = tmp_path / 'synthetic-old.docx'
    document = Document()
    document.add_paragraph('Synthetic old account')
    brand = picture((600, 90), 'ENFRA STATIC SYNTHETIC', 'lightgreen')
    old_client = picture((300, 100), 'OLD CLIENT - REMOVE', 'lightblue')
    old_slogan = picture((409, 37), 'SYNTHETIC SHARED CORPORATE ART', 'yellow')
    current_client = picture((700, 230), 'CURRENT CLIENT', 'white')
    document.add_paragraph().add_run().add_picture(BytesIO(brand), width=Inches(2))
    document.add_paragraph().add_run().add_picture(BytesIO(old_client), width=Inches(2))
    document.add_paragraph('CONTENTS')
    document.add_paragraph().add_run().add_picture(BytesIO(old_slogan), width=Inches(1.9), height=Inches(.172))
    document.add_heading('MONTHLY ACTIVITY SUMMARY', level=1)
    document.add_paragraph('Private old activity')
    document.save(source)
    profile = ReportProfile('Synthetic new contract', 'north', 'Synthetic New Client', (Facility('north', 'Synthetic New Client'),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', default_sections(),
                        (ResolvedBlock('client_logo', 'Library', asset_hashes=('current-client.png',)),))
    return source, draft, brand, old_client, old_slogan, current_client


def media(raw):
    with ZipFile(BytesIO(raw)) as archive:
        return tuple(archive.read(name) for name in archive.namelist() if name.startswith('word/media/'))


def test_static_company_slogan_requires_verified_pixels_and_proper_source_part(tmp_path, monkeypatch):
    source, _, _, _, art, _ = source_and_draft(tmp_path)
    inspection = inspect_docx(source)
    item = next(i for i in inspection.items if i.kind == 'image' and i.image_width == 409 and i.image_height == 37)
    digest = hashlib.sha256(Image.open(BytesIO(art)).convert('RGBA').tobytes()).hexdigest()
    assert not slogan.is_approved_company_slogan(source, inspection.sha256, item)
    monkeypatch.setattr(slogan, '_APPROVED_WORDMARK_PIXELS', frozenset((digest,)))
    assert slogan.is_approved_company_slogan(source, inspection.sha256, item)
    assert not slogan.is_approved_company_slogan(source, inspection.sha256, replace(item, image_width=410))
    assert slogan._fingerprint(str(source), inspection.sha256, '../private.xml') == ''


def test_fresh_master_preserves_only_verified_company_slogan_not_old_client(tmp_path, monkeypatch):
    source, draft, brand, old_client, art, current_client = source_and_draft(tmp_path)
    original_bytes = source.read_bytes()
    digest = hashlib.sha256(Image.open(BytesIO(art)).convert('RGBA').tobytes()).hexdigest()
    monkeypatch.setattr(slogan, '_APPROVED_WORDMARK_PIXELS', frozenset((digest,)))
    output = build_native_docx(draft, source, master=True, asset_loader=lambda _: current_client)
    images = media(output)
    assert art in images, 'Corporate wordmark should remain in its real source frame.'
    assert current_client in images, 'New client mark should replace old client mark.'
    assert old_client not in images, 'Old client mark must be removed.'
    assert source.read_bytes() == original_bytes
    actual = Document(BytesIO(output))
    assert 'Private old activity' not in '\n'.join(p.text for p in actual.paragraphs)


def test_unverified_same_dimensions_cannot_be_promoted_from_appearance(tmp_path):
    source, draft, _, old_client, art, current_client = source_and_draft(tmp_path)
    output = build_native_docx(draft, source, master=True, asset_loader=lambda _: current_client)
    assert art not in media(output), 'Unknown artwork must not survive a master under the exception.'


def test_corrupt_or_large_vector_like_parts_are_never_approved(tmp_path, monkeypatch):
    source, _, _, _, art, _ = source_and_draft(tmp_path)
    inspection = inspect_docx(source)
    item = next(i for i in inspection.items if i.kind == 'image' and i.image_width == 409)
    assert slogan._fingerprint(str(source), inspection.sha256, 'word/media/not-present.png') == ''
    assert slogan._fingerprint(str(source), inspection.sha256, 'word/media/../item.xml') == ''
