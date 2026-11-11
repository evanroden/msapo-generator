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
