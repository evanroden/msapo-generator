"""Synthetic cover admission probe; run each case in a fresh capped image.

Generate in a separate bounded container (1536 MiB, 180s); seven files total at
most 448 MiB. Codec originals plus padding deliberately exercise encoded-byte
and decoded-pixel ceilings together. They are not private or production files.
Local --simulate-512 is measurement only, never capped-container acceptance.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import resource
import sys
import time
from threading import Event, Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIB = 1024 * 1024


def generate(folder):
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (7000, 3100), 'navy')
    image.save(folder / 'large.png', compress_level=0)
    image.close()
    image = Image.frombytes('RGB', (8000, 5000), bytes(range(256)) * (120_000_000 // 256))
    image.save(folder / 'large.jpg', quality=95, subsampling=0)
    image.save(folder / 'progressive-444.jpg', quality=95, subsampling=0, progressive=True)
    image.save(folder / 'progressive-420.jpg', quality=95, subsampling=2, progressive=True)
    gray = image.convert('L')
    gray.save(folder / 'progressive-gray.jpg', quality=95, progressive=True)
    gray.close()
    image.save(folder / 'large.webp', 'WEBP', quality=80)
    from pillow_heif import register_heif_opener
    register_heif_opener(thumbnails=False)
    image.save(folder / 'large.heic', 'HEIF', quality=70)
    image.close()
    for name in ('large.jpg', 'large.webp', 'large.heic', 'progressive-444.jpg', 'progressive-420.jpg', 'progressive-gray.jpg'):
        path = folder / name
        assert path.stat().st_size <= 64*MIB
        with path.open('ab') as stream:
            remaining = 64*MIB - path.stat().st_size
            while remaining > 0:
                chunk = min(remaining, MIB)
                stream.write(b'\0' * chunk)
                remaining -= chunk
    assert sum(path.stat().st_size for path in folder.iterdir()) <= 448*MIB


def cgroup_memory():
    for root, limit, used in [('/sys/fs/cgroup','memory.max','memory.current'),
                              ('/sys/fs/cgroup/memory','memory.limit_in_bytes','memory.usage_in_bytes')]:
        try:
            return int((Path(root)/limit).read_text()), int((Path(root)/used).read_text())
        except (OSError, ValueError):
            pass
    return None, None


def current_rss():
    # Linux /proc is available in the production Docker image. Peak RSS is
    # deliberately not substituted for current usage in the local simulation.
    return next(int(line.split()[1])*1024 for line in Path('/proc/self/status').read_text().splitlines()
                if line.startswith('VmRSS:'))


def probe(args):
    from app.monthly_report_cover_images import read_picture_upload, MEMORY_ERROR
    from app.monthly_report_cover_ui import replace_cover_picture
    from app.monthly_report_model import ResolvedBlock
    from app import monthly_report_render_jobs as jobs
    from PIL import Image
    limit, _ = cgroup_memory()
    if os.environ.get('RESOURCE_REQUIRE_512_MB') == '1':
        assert limit is not None and 0 < limit <= 512*MIB, 'Real 512 MiB cgroup required'
        assert not args.simulate_512
    if args.simulate_512:
        jobs.memory_headroom = lambda: max(0, 512*MIB-current_rss())
    baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Native uploader buffers survive a busy decoder refusal; retain every
    # visitor's original throughout the probe, not only inside worker scopes.
    uploads = [BytesIO(args.probe.read_bytes()) for _ in range(args.concurrent)]
    assert all(30*MIB < len(upload.getbuffer()) <= 64*MIB for upload in uploads)
    old = ResolvedBlock('cover_photo','Library',asset_hashes=('old',))
    def run(index):
        upload = uploads[index]
        raw = read_picture_upload(upload, cover_photo=True)
        assets = {'old':b'unchanged'}
        try:
            block = replace_cover_picture(old, raw, args.probe.suffix, assets)
        except ValueError as exc:
            assert assets == {'old':b'unchanged'}
            assert str(exc).startswith('Another report') or str(exc) == MEMORY_ERROR
            return {'refusal':'busy' if str(exc).startswith('Another report') else 'memory'}
        assert assets['old'] == b'unchanged'
        normalized = assets[block.asset_hashes[0]]
        with Image.open(BytesIO(normalized)) as image:
            dimensions = image.size
            assert image.format == 'JPEG' and image.width <= 1400 and image.height <= 1800
        assert len(normalized) < 30*MIB
        return {'input_bytes':len(raw),'output_bytes':len(normalized),'dimensions':dimensions}
    started = time.monotonic()
    if args.slot_retry:
        # Both foreground export and preview use this actual shared gate. This
        # proves overlapping admission/unchanged artwork, not PDF fidelity.
        for preview in (False, True):
            held, release = Event(), Event()
            def competing_report():
                with jobs.work_slot(preview=preview):
                    held.set()
                    assert release.wait(10)
            thread = Thread(target=competing_report)
            thread.start()
            try:
                assert held.wait(10)
                assert run(0) == {'refusal':'busy'}
            finally:
                release.set(); thread.join(10)
        results = [run(0)]
        assert 'output_bytes' in results[0], 'Retry after report work must succeed'
    else:
        with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
            results = list(pool.map(run, range(args.concurrent)))
    if args.expect == 'success':
        assert any('output_bytes' in result for result in results), results
    elif args.expect == 'memory':
        assert all(result.get('refusal') in ('memory','busy') for result in results), results
        assert any(result.get('refusal') == 'memory' for result in results), results
    print(json.dumps({'file':args.probe.name,'concurrent':args.concurrent,'slot_retry':args.slot_retry,
        'simulation_only':args.simulate_512,'cgroup_limit_bytes':limit,
        'seconds':round(time.monotonic()-started,3),'baseline_rss_kib':baseline,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'results':results}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate',type=Path)
    parser.add_argument('--probe',type=Path)
    parser.add_argument('--concurrent',type=int,choices=(1,2),default=1)
    parser.add_argument('--expect',choices=('success','memory','safe'),default='safe')
    parser.add_argument('--slot-retry',action='store_true')
    parser.add_argument('--simulate-512',action='store_true')
    args = parser.parse_args()
    if args.generate:
        generate(args.generate)
    else:
        assert args.probe is not None
        probe(args)
