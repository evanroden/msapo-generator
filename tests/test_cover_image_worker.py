from io import BytesIO
from pathlib import Path
import subprocess
import sys
from PIL import Image
import pytest

WORKER = Path(__file__).parents[1] / 'scripts' / 'cover_image_worker.py'

def run_worker(tmp_path, raw, budget=256*1024*1024):
    source, target = tmp_path/'input', tmp_path/'output'
    source.write_bytes(raw)
    result = subprocess.run([sys.executable, '-I', str(WORKER), str(source), str(target), str(budget)],
                            capture_output=True, timeout=20)
    return result, target

@pytest.mark.parametrize('fmt,mode', [('JPEG','RGB'), ('PNG','RGBA'), ('WEBP','RGB')])
def test_worker_reduces_and_matches_approved_white_composite(tmp_path, fmt, mode):
    stream = BytesIO()
    Image.new(mode, (2400,1200), (10,20,30,100) if mode=='RGBA' else (10,20,30)).save(stream, fmt)
    result, target = run_worker(tmp_path, stream.getvalue())
    assert result.returncode == 0, result.stderr
    with Image.open(target) as image:
        assert image.size == (1400,700)
        if mode == 'RGBA':
            assert image.mode == 'RGB'
            expected=tuple(round(channel*100/255 + 255*155/255) for channel in (10,20,30))
            assert all(abs(actual-wanted)<=3 for actual,wanted in zip(image.getpixel((0,0)),expected))

@pytest.mark.parametrize('raw', [b'garbage', b'\x89PNG\r\n\x1a\ntruncated'])
def test_corrupt_is_not_recovered(tmp_path, raw):
    result, target = run_worker(tmp_path, raw)
    assert result.returncode != 0
    assert not target.exists()


def test_multiframe_and_unsupported_not_recovered(tmp_path):
    stream = BytesIO()
    Image.new('RGB',(20,10),'red').save(stream,'GIF',save_all=True,
        append_images=[Image.new('RGB',(20,10),'blue')])
    result, target = run_worker(tmp_path, stream.getvalue())
    assert result.returncode != 0
    assert not target.exists()


def test_too_small_memory_budget_fails_without_output(tmp_path):
    stream = BytesIO(); Image.new('RGB',(20,10)).save(stream,'PNG')
    result, target = run_worker(tmp_path,stream.getvalue(), 1024)
    assert result.returncode != 0
    assert not target.exists()


def test_actual_address_space_limit_rejects_large_raster(tmp_path):
    stream=BytesIO()
    Image.new('RGB',(4000,4000),'navy').save(stream,'PNG')
    result,target=run_worker(tmp_path,stream.getvalue(),64*1024*1024)
    assert result.returncode != 0
    assert not target.exists()
