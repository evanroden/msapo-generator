"""ENFRA's verified header furniture is page design, not unknown cover art."""
from dataclasses import replace
from io import BytesIO
import hashlib

from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw

from app import monthly_report_static_branding as branding
from app.monthly_report_content_policy import table_price_columns
from app.monthly_report_import import ImportItem
from app.monthly_report_native_layout import _remove_unapproved_header_images
from app.monthly_report_start_import import unresolved_cover_artwork


def picture(size, text, color, fmt='PNG', **save):
    image = Image.new('RGB', size, color)
    ImageDraw.Draw(image).text((4, 4), text, fill='black')
    buffer = BytesIO()
    image.save(buffer, fmt, **save)
    return buffer.getvalue()


def approve(monkeypatch, raw):
    with Image.open(BytesIO(raw)) as image:
        pixels = hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()
        size = image.size
    monkeypatch.setattr(branding, '_COMPANY_ARTWORK_BYTES', frozenset({hashlib.sha256(raw).hexdigest()}))
    monkeypatch.setattr(branding, '_COMPANY_ARTWORK_PIXELS', {size: pixels})


def test_company_artwork_matches_exact_bytes_or_lossless_resave(monkeypatch):
    logo = picture((180, 29), 'SYNTHETIC COMPANY', 'white')
    approve(monkeypatch, logo)
    assert branding.is_company_artwork_blob(logo)
    resaved = picture((180, 29), 'SYNTHETIC COMPANY', 'white', optimize=True)
    assert branding.is_company_artwork_blob(resaved)
    assert not branding.is_company_artwork_blob(picture((180, 29), 'OLD CLIENT', 'white'))
    assert not branding.is_company_artwork_blob(picture((181, 29), 'SYNTHETIC COMPANY', 'white'))
    assert not branding.is_company_artwork_blob(b'')
    assert branding.is_company_artwork_digest(hashlib.sha256(logo).hexdigest())
    assert not branding.is_company_artwork_digest('')


def test_verified_header_furniture_no_longer_blocks_cover_import(monkeypatch):
    logo = picture((180, 29), 'SYNTHETIC COMPANY', 'white')
    approve(monkeypatch, logo)
    company = ImportItem('item-1', 'image', 'word/header1.xml', 1, 2, 'cover', image_part='word/media/a.png',
                         image_width=180, image_height=29, image_digest=hashlib.sha256(logo).hexdigest(),
                         image_role='header_artwork')
    unknown = replace(company, id='item-2', image_part='word/media/b.png', image_digest='0' * 64)
    # The same bytes in the document body are not header furniture.
    body = replace(company, id='item-3', part='word/document.xml', word_section=1)
    assert unresolved_cover_artwork((company,)) == ()
    assert unresolved_cover_artwork((company, unknown)) == (unknown,)
    assert body in unresolved_cover_artwork((body,))


def test_fresh_master_keeps_company_header_logo_and_drops_old_client_art(monkeypatch):
    logo = picture((180, 29), 'SYNTHETIC COMPANY', 'white')
    old_client = picture((120, 40), 'OLD CLIENT - REMOVE', 'lightblue')
    approve(monkeypatch, logo)
    document = Document()
    header = document.sections[0].header
    run = header.paragraphs[0].add_run()
    run.add_picture(BytesIO(logo), width=Inches(1.5))
    run.add_picture(BytesIO(old_client), width=Inches(1))
    part = header.part
    _remove_unapproved_header_images(part, set())
    kept = [part.related_parts[node.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')].blob
            for node in part.element.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}blip')]
    assert kept == [logo]


def test_status_column_beside_sentence_notes_is_not_a_price_column():
    columns = ('Site / Area', 'Scope', 'Provider', 'Status', 'Notes')
    rows = (
        ('North Site', 'Covered electrical assets', 'Synthetic Electric', 'Quote in preparation',
         'Thermal scan intended to support electrical condition evaluation.'),
        ('South Site', 'No scope documented', '—', 'No update', 'No scope was supplied for this reporting cycle.'),
    )
    assert table_price_columns(columns, rows) == ()
    # A real price heading is still removed, whatever the notes say.
    assert table_price_columns(columns + ('Cost',), tuple(row + ('',) for row in rows)) == (5,)
