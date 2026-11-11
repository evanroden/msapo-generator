from io import BytesIO
from dataclasses import replace
import base64
import pytest
from PIL import Image
from app import ocr, monthly_report_sources as sources, monthly_report_library as library
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_model import synthetic_profiles, synthetic_draft, ReportPeriod


def mpo(count=2):
    out = BytesIO()
    Image.new('RGB', (24, 18), 'red').save(out, format='MPO', save_all=True,
        append_images=[Image.new('RGB', (24, 18), 'blue') for _ in range(count-1)])
    return out.getvalue()


def color(raw):
    with Image.open(BytesIO(raw)) as image:
        return image.convert('RGB').getpixel((12, 9))


def test_mpo_vision_and_report_frames_preserve_order_without_default_truncation():
    raw = mpo()
    blocks = ocr.image_blocks_for_vision(raw, '.mpo')
    assert len(blocks) == 2
    for index, block in enumerate(blocks):
        expected = 0 if index == 0 else 2
        assert color(base64.b64decode(block['source']['data']))[expected] > 240
        assert color(normalize_report_image(raw, '.mpo', frame_index=index).data)[expected] > 240
    with pytest.raises(ValueError, match='single image'):
        normalize_report_image(raw, '.mpo')
    with pytest.raises(ValueError, match='does not exist'):
        normalize_report_image(raw, '.mpo', frame_index=2)


def test_mpo_intake_reopen_and_selected_page_derivatives(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = mpo()
    content, _ = sources.ingest(profile, 'Synthetic pictures.mpo', raw)
    assert sources.image_numbers(content) == (1, 2)
    assert content.source.needs_vision == (1, 2)
    assert sources.source_bytes(profile, content.source) == raw
    assert color(sources.page_image(profile, content, 1).data)[0] > 240
    assert color(sources.page_image(profile, content, 2).data)[2] > 240
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 10)), sources=(content.source,))
    library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic MPO Reviewer')
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reopened.draft.sources == draft.sources
    assert sources.source_bytes(profile, reopened.draft.sources[0]) == raw
    repeated, _ = sources.ingest(profile, 'Synthetic pictures.mpo', raw)
    assert repeated == content


def test_bad_mpo_keeps_good_batch_siblings(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    contents, notices = sources.ingest_batch(profile, (
        ('first.txt', b'First synthetic inspection'), ('bad.mpo', b'not an image'),
        ('last.txt', b'Last synthetic inspection')))
    assert len(contents) == 2
    assert any('bad.mpo' in n for n in notices)


def test_mpo_total_pixels_and_frame_count_reject_before_raster_copy(monkeypatch):
    from app.mpo_images import frame_count
    raw = mpo()
    monkeypatch.setattr(ocr, '_MAX_PIXELS_PER_FRAME', 24 * 18)
    monkeypatch.setattr(Image.Image, 'copy', lambda self: pytest.fail('must reject before raster copy'))
    with pytest.raises(ValueError, match='too large'):
        frame_count(raw)
    with pytest.raises(ValueError, match='too large'):
        ocr.image_blocks_for_vision(raw, '.mpo')
    monkeypatch.setattr(ocr, '_MAX_PIXELS_PER_FRAME', 40_000_000)
    monkeypatch.setattr(ocr, '_MAX_IMAGE_FRAMES', 1)
    with pytest.raises(ValueError, match='too many frames'):
        frame_count(raw)


def prepared_draft(monkeypatch, tmp_path):
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_model import default_sections
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, 'Synthetic pictures.mpo', mpo())
    source = replace(content.source, selected_pages=(1, 2), captions=((1, 'Synthetic red picture'), (2, 'Synthetic blue picture')))
    from app.monthly_report_source_scope import correct_scope
    source = correct_scope(source, profile, (profile.facilities[0].key,))
    source = replace(source, client_page_reviews=tuple((n, page_fingerprint(source, n)) for n in (1, 2)))
    content = replace(content, source=source)
    blocks = sources.prepare_pages(profile, (content,), ((source.id, 'vendor_reports'),))
    sections = tuple(replace(s, blocks=tuple(b for b in s.blocks if b.key == 'vendor_reports'))
                     for s in default_sections() if any(b.key == 'vendor_reports' for b in s.blocks))
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 10)), sections=sections, blocks=blocks, sources=(source,))
    loader = lambda ref: library.read_asset(profile.contract, profile.key, ref)
    return draft, loader


def test_selected_mpo_frames_reach_real_word_in_order(monkeypatch, tmp_path):
    from docx import Document
    from app.monthly_report_docx import assemble_docx
    draft, loader = prepared_draft(monkeypatch, tmp_path)
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
    document = Document(BytesIO(raw))
    captions = [p.text for p in document.paragraphs if p.text in ('Synthetic red picture', 'Synthetic blue picture')]
    assert captions == ['Synthetic red picture', 'Synthetic blue picture']
    images = [document.part.related_parts[s._inline.graphic.graphicData.pic.blipFill.blip.embed].blob
              for s in document.inline_shapes]
    colors = [color(raw) for raw in images if Image.open(BytesIO(raw)).size == (24, 18)]
    assert len(colors) == 2
    assert colors[0][0] > 240 and colors[1][2] > 240


from tests.conftest import requires_libreoffice

@requires_libreoffice
def test_selected_mpo_frames_reach_actual_pdf(monkeypatch, tmp_path):
    import pymupdf
    from app.monthly_report_docx import generate_report
    draft, loader = prepared_draft(monkeypatch, tmp_path)
    package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
    with pymupdf.open(stream=package.pdf, filetype='pdf') as pdf:
        texts = [page.get_text() for page in pdf]
        assert sum(t.count('Synthetic red picture') for t in texts) == 1
        assert sum(t.count('Synthetic blue picture') for t in texts) == 1
        assert next(i for i,t in enumerate(texts) if 'Synthetic red picture' in t) < next(i for i,t in enumerate(texts) if 'Synthetic blue picture' in t)


def test_decoder_dimension_rejection_stays_within_batch(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = mpo()
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 100)
    contents, notices = sources.ingest_batch(profile, (
        ('first.txt', b'First synthetic inspection'), ('oversized.mpo', raw),
        ('last.txt', b'Last synthetic inspection')))
    assert len(contents) == 2
    assert any('oversized.mpo' in notice and 'too large' in notice for notice in notices)
