"""Automatic recovery must never relax decoder or atomic replacement guards."""
from io import BytesIO
import pytest
from PIL import Image
from app import monthly_report_cover_images as cover


def encoded(fmt):
    stream = BytesIO()
    Image.new('RGB', (100, 50), 'navy').save(stream, fmt)
    return stream.getvalue()


@pytest.mark.parametrize('fmt,expected', [('JPEG','.jpg'), ('PNG','.png'), ('WEBP','.webp')])
def test_sniff_supported_photos_without_decode(fmt, expected):
    assert cover.cover_photo_suffix(encoded(fmt), '.wrong') == expected


def test_heif_brand_recognized_but_generic_iso_media_not_guessed():
    heif = (24).to_bytes(4, 'big') + b'ftypheic' + b'\0'*4 + b'mif1heic'
    assert cover.cover_photo_suffix(heif, '.jpg') == '.heic'
    avif = (24).to_bytes(4, 'big') + b'ftypavif' + b'\0'*4 + b'mif1avif'
    assert cover.cover_photo_suffix(avif, '.avif') == '.avif'
    assert cover.cover_photo_suffix(heif[:15], '.png') == '.png'


@pytest.mark.parametrize('fmt', ['PNG', 'JPEG', 'WEBP'])
def test_known_photo_with_wrong_extension_recovers(fmt, monkeypatch):
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 400*1024*1024)
    raw = encoded(fmt)
    result = cover.normalize_cover_photo(raw, '.wrong')
    assert (result.width, result.height) == (100, 50)
    assert raw == encoded(fmt)


def test_signature_recovery_does_not_swallow_corruption_or_replace_last_good():
    from app.monthly_report_cover_ui import replace_cover_picture
    from app.monthly_report_model import ResolvedBlock
    old = ResolvedBlock('cover_photo', 'Library', asset_hashes=('old',))
    assets = {'old': b'last good artwork'}
    with pytest.raises((ValueError, OSError)):
        replace_cover_picture(old, b'\x89PNG\r\n\x1a\ntruncated', '.jpg', assets)
    assert assets == {'old': b'last good artwork'}
    assert old.asset_hashes == ('old',)


def test_signature_recovery_still_obeys_memory_budget(monkeypatch):
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1)
    with pytest.raises(ValueError, match='memory'):
        cover.normalize_cover_photo(encoded('PNG'), '.wrong')


def test_real_mislabeled_heif_in_fresh_interpreter(tmp_path):
    """Opener must be selected from bytes, not a prior test's registration."""
    import os
    import subprocess
    import sys
    import pillow_heif
    source = tmp_path / 'phone-photo.jpg'
    pillow_heif.from_pillow(Image.new('RGB', (80, 40), 'navy')).save(source)
    code = '''
from pathlib import Path
from app.monthly_report_cover_images import normalize_cover_photo
from app import monthly_report_render_jobs as jobs
jobs.memory_headroom = lambda: 400 * 1024 * 1024
raw = Path(__import__('sys').argv[1]).read_bytes()
result = normalize_cover_photo(raw, '.jpg')
assert (result.width, result.height) == (80, 40)
assert result.extension == 'jpg'
'''
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    result = subprocess.run([sys.executable, '-c', code, str(source)],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
