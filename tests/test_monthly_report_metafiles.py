from io import BytesIO
import struct
from zipfile import ZipFile, ZIP_DEFLATED

import fitz
from PIL import Image
import pytest

from app import monthly_report_metafiles as vectors
from app import monthly_report_import as importer


def metafile(extra=b''):
    header = bytearray(88)
    struct.pack_into('<II', header, 0, 1, 88)
    struct.pack_into('<4i', header, 8, 0, 0, 200, 300)
    struct.pack_into('<4i', header, 24, 0, 0, 2000, 3000)
    header[40:44] = b' EMF'
    eof = struct.pack('<IIIII', 14, 20, 0, 0, 20)
    struct.pack_into('<II', header, 48, 108 + len(extra), 2 + bool(extra))
    return bytes(header) + extra + eof


def report(tmp_path, raw=None):
    package, _ = vectors._image_package(metafile(), '.emf')
    with ZipFile(BytesIO(package)) as z:
        parts = {name: z.read(name) for name in z.namelist()}
    parts['word/document.xml'] = parts['word/document.xml'].replace(
        b'<w:body>', b'<w:body><w:p><w:r><w:t>Equipment Performance Issues</w:t></w:r></w:p>')
    if raw is not None:
        parts['word/media/drawing.emf'] = raw
    path = tmp_path / 'report.docx'
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def test_static_image_import_keeps_id_and_suggests_equipment_evidence(tmp_path):
    path = report(tmp_path)
    accepted = importer.inspect_docx(path)
    image = next(i for i in accepted.items if i.image_part)
    assert image.kind == 'image'
    assert image.suggested_slot == 'equipment_issues_evidence'
    assert (image.image_width, image.image_height) == (200, 300)
    rejected = importer.inspect_docx(report(tmp_path, metafile(struct.pack('<II', 105, 8))))
    unsupported = next(i for i in rejected.items if i.image_part)
    assert unsupported.id == image.id
    assert unsupported.kind == 'unsupported'


def test_closed_review_package_retains_only_validated_image():
    raw = metafile()
    package, size = vectors._image_package(raw, '.emf')
    with ZipFile(BytesIO(package)) as archive:
        assert set(archive.namelist()) == {
            '[Content_Types].xml', '_rels/.rels', 'word/document.xml',
            'word/_rels/document.xml.rels', 'word/media/drawing.emf',
        }
        assert archive.read('word/media/drawing.emf') == raw
        assert b'TargetMode' not in archive.read('word/_rels/document.xml.rels')
    assert size == (432, 648)


@pytest.mark.parametrize('raw', [b'not a metafile', metafile()[:-1], metafile(struct.pack('<II', 105, 8))])
def test_unknown_or_active_metafile_never_reaches_converter(raw):
    assert not vectors.supported_metafile(raw, '.emf')
    with pytest.raises(ValueError):
        vectors._image_package(raw, '.emf')


def test_degenerate_frame_rejected_before_metadata_or_converter():
    raw = bytearray(metafile())
    struct.pack_into('<4i', raw, 24, 0, 0, 0, 0)
    assert not vectors.supported_metafile(bytes(raw), '.emf')


def test_review_raster_is_cached_and_existing_normalization_sees_pixels(tmp_path, monkeypatch):
    from app import monthly_report_library as library, monthly_report_word_pages as pages
    monkeypatch.setattr(library, '_root', lambda: tmp_path)
    monkeypatch.setattr(vectors, '_renderer_fingerprint', lambda *args: b'test-renderer-fonts')
    calls = []
    def render(path, directory):
        calls.append(path.read_bytes())
        pdf = fitz.open()
        page = pdf.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(0, 0, 432, 648), color=(0, 0, 0), fill=(0, 0, 0))
        target = directory / 'review.pdf'
        pdf.save(target)
        pdf.close()
        return target
    monkeypatch.setattr(pages, '_render', render)
    path = report(tmp_path)
    item = next(i for i in importer.inspect_docx(path).items if i.image_part)
    first = importer.read_import_image(path, item)
    second = importer.read_import_image(path, item)
    assert first.data == second.data and len(calls) == 1
    assert first.width / first.height == pytest.approx(2 / 3, abs=.001)
    with Image.open(BytesIO(first.data)) as image:
        assert image.getpixel((image.width // 2, image.height // 2)) == (0, 0, 0)
        assert image.getpixel((1, 1)) == (0, 0, 0)
    # A changed font/renderer profile must generate new review evidence.
    monkeypatch.setattr(vectors, '_renderer_fingerprint', lambda *args: b'changed-fonts')
    importer.read_import_image(path, item)
    assert len(calls) == 2
