"""Cover-only encoded admission, independent of decoded dimensions and DOCX budgets."""
from io import BytesIO
from dataclasses import replace
import pytest
from PIL import Image
from app.monthly_report_cover_ui import replace_cover_picture
from app.monthly_report_model import ResolvedBlock

MIB = 1024 * 1024

def image_bytes(size=31*MIB, fmt='PNG'):
    stream = BytesIO()
    Image.new('RGB', (20, 10), 'navy').save(stream, fmt)
    # Valid image plus inert trailing bytes exercises encoded admission, NOT
    # worst-case decoder memory; the resource probe covers real raster data.
    raw = stream.getvalue()
    return raw + b'\0' * max(0, size-len(raw))

@pytest.mark.parametrize('size', [30*MIB+1, 64*MIB-1, 64*MIB])
def test_large_cover_photo_normalizes_without_mutating_original(size):
    raw = image_bytes(size)
    before = hash(raw)
    assets = {}
    block = replace_cover_picture(ResolvedBlock('cover_photo', 'Omit'), raw, '.png', assets)
    assert block.source == 'Replace once'
    assert hash(raw) == before
    normalized = assets[block.asset_hashes[0]]
    assert len(normalized) < 10000
    with Image.open(BytesIO(normalized)) as im:
        assert im.size == (20, 10)

@pytest.mark.parametrize('slot', ['client_logo', 'brand_logo', 'contact_matrix'])
def test_noncover_cap_stays_30mib(slot):
    with pytest.raises(ValueError):
        replace_cover_picture(ResolvedBlock(slot, 'Omit'), image_bytes(), '.png', {})

def test_above_cover_cap_retains_existing_block_and_assets():
    old = ResolvedBlock('cover_photo', 'Library', asset_hashes=('old',))
    assets = {'old': b'original'}
    with pytest.raises(ValueError):
        replace_cover_picture(old, image_bytes(64*MIB+1), '.png', assets)
    assert assets == {'old': b'original'} and old.asset_hashes == ('old',)

@pytest.mark.parametrize('claimed_size', [None, 1, 64*MIB+1])
def test_bounded_read_cannot_trust_reported_size(claimed_size):
    from app.monthly_report_cover_images import read_picture_upload
    class GrowingUpload(BytesIO):
        def read(self, count=-1):
            assert count == 64*MIB+1
            self.count = count
            return b'x' * count
    source = GrowingUpload(b'input')
    source.seek(3)
    if claimed_size is not None:
        source.size = claimed_size
    with pytest.raises(ValueError, match='64 MiB'):
        read_picture_upload(source, cover_photo=True)
    assert source.tell() == 3
    if claimed_size == 64*MIB+1:
        assert not hasattr(source, 'count'), 'Reject known overflow before reading'

@pytest.mark.parametrize('size', [64*MIB-1, 64*MIB])
def test_read_accepts_boundary_and_restores_cursor(size):
    from app.monthly_report_cover_images import read_picture_upload
    source = BytesIO(b'x' * size)
    source.seek(7)
    raw = read_picture_upload(source, cover_photo=True)
    assert len(raw) == size and source.tell() == 7

@pytest.mark.parametrize('fmt,suffix', [('PNG','.png'),('JPEG','.jpg'),('WEBP','.webp')])
def test_each_photo_format_reencodes_with_same_geometry(fmt, suffix):
    assets = {}
    raw = image_bytes(31*MIB, fmt)
    block = replace_cover_picture(ResolvedBlock('cover_photo','Omit'), raw, suffix, assets)
    with Image.open(BytesIO(assets[block.asset_hashes[0]])) as image:
        assert image.format == 'JPEG' and image.size == (20, 10)

@pytest.mark.parametrize('width,height', [(8000,5001), (1000000,1000000)])
def test_dimensions_rejected_before_raster_decode(monkeypatch, width, height):
    from app import monthly_report_docx as docx
    class Header:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def load(self): raise AssertionError('must not decode')
    header = Header()
    header.width, header.height = width,height
    monkeypatch.setattr(docx.Image, 'open', lambda *a: header)
    with pytest.raises(ValueError, match='too large to decode'):
        replace_cover_picture(ResolvedBlock('cover_photo','Omit'), b'x', '.png', {})

def test_multiframe_still_rejected_and_existing_assets_retained():
    raw = BytesIO()
    Image.new('RGB',(20,10),'red').save(raw, 'WEBP', save_all=True,
        append_images=[Image.new('RGB',(20,10),'blue')], duration=100, loop=0)
    assets = {'old':b'unchanged'}
    with pytest.raises(ValueError, match='single image'):
        replace_cover_picture(ResolvedBlock('cover_photo','Library',asset_hashes=('old',)), raw.getvalue(), '.webp', assets)
    assert assets == {'old':b'unchanged'}

def test_other_resource_envelopes_unchanged():
    from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES, MAX_VIEW_MEDIA_BYTES
    from app.monthly_report_import import MAX_DOCX_BYTES, MAX_NORMALIZED_BYTES
    from app.ocr import _MAX_PIXELS_PER_FRAME
    assert (MAX_VIEW_SOURCE_BYTES,MAX_VIEW_MEDIA_BYTES) == (24*MIB,16*MIB)
    assert (MAX_DOCX_BYTES,MAX_NORMALIZED_BYTES) == (128*MIB,60*MIB)
    assert _MAX_PIXELS_PER_FRAME == 40_000_000

def test_advanced_photo_uploader_advertises_effective_cap():
    from test_monthly_report_cover_ui import cover_app, button
    app = cover_app(empty=True)
    button(app, 'Change cover photo').click().run()
    widget = app.get('file_uploader')[0]
    assert widget.proto.max_upload_size_mb == 68
    assert '64 MiB' in widget.proto.help and '40 million pixels' in widget.proto.help
    assert not app.exception

@pytest.mark.parametrize('orientation', range(1,9))
def test_orientation_and_frame_fit_survive_pretranspose_reduction(orientation):
    from PIL import ImageOps, ImageDraw
    source = Image.new('RGB', (2100, 1200), 'white')
    draw = ImageDraw.Draw(source)
    for box, color in [((0,0,500,500),'red'),((1600,0,2099,500),'green'),
                       ((0,700,500,1199),'blue'),((1600,700,2099,1199),'yellow')]:
        draw.rectangle(box,fill=color)
    exif = Image.Exif(); exif[274] = orientation
    raw = BytesIO(); source.save(raw,'PNG',exif=exif)
    assets = {}
    block = replace_cover_picture(ResolvedBlock('cover_photo','Omit'),raw.getvalue(),'.png',assets)
    with Image.open(BytesIO(raw.getvalue())) as original:
        expected = ImageOps.exif_transpose(original)
        expected.thumbnail((1400,1800),Image.Resampling.LANCZOS)
    with Image.open(BytesIO(assets[block.asset_hashes[0]])) as actual:
        assert actual.size == expected.size
        for x,y in [(30,30),(actual.width-30,30),(30,actual.height-30),(actual.width-30,actual.height-30)]:
            assert max(abs(a-b) for a,b in zip(actual.getpixel((x,y)),expected.getpixel((x,y)))) <= 5
        assert actual.getexif().get(274) is None


def test_busy_normalization_keeps_artwork_and_retry_works():
    import threading
    from app.monthly_report_render_jobs import work_slot
    held, release = threading.Event(), threading.Event()
    def competing_report():
        with work_slot():
            held.set(); release.wait(5)
    thread = threading.Thread(target=competing_report)
    thread.start(); assert held.wait(5)
    assets = {'old':b'unchanged'}
    block = ResolvedBlock('cover_photo','Library',asset_hashes=('old',))
    raw = image_bytes(0)
    try:
        with pytest.raises(ValueError,match='Try again shortly'):
            replace_cover_picture(block,raw,'.png',assets)
        assert assets == {'old':b'unchanged'}
    finally:
        release.set(); thread.join(5)
    updated = replace_cover_picture(block,raw,'.png',assets)
    assert updated.asset_hashes != block.asset_hashes and assets['old'] == b'unchanged'

@pytest.mark.parametrize('suffix', ['.heic','.heif'])
def test_heif_cover_photo_uses_same_larger_admission(suffix):
    from pillow_heif import register_heif_opener
    register_heif_opener(thumbnails=False)
    stream = BytesIO()
    Image.new('RGB',(20,10),'navy').save(stream,'HEIF')
    original = stream.getvalue()
    raw = original + b'\0' * (31*MIB-len(original))
    assets = {}
    block = replace_cover_picture(ResolvedBlock('cover_photo','Omit'), raw,suffix,assets)
    assert raw.startswith(original)
    with Image.open(BytesIO(assets[block.asset_hashes[0]])) as output:
        assert output.size == (20,10) and output.format == 'JPEG'

@pytest.mark.parametrize('orientation', range(1,9))
def test_jpeg_geometry_and_quality_against_legacy_normalizer(orientation):
    from PIL import ImageChops, ImageStat
    from app.monthly_report_docx import normalize_report_image
    # Odd dimensions catch JPEG draft rounding; textured gradients test
    # resampling quality rather than accepting flat-color-only parity.
    source = Image.effect_noise((401,601),15).convert('RGB').resize((4001,6003),Image.Resampling.BICUBIC)
    exif = Image.Exif(); exif[274] = orientation
    stream = BytesIO(); source.save(stream,'JPEG',quality=92,exif=exif)
    raw = stream.getvalue()
    legacy = normalize_report_image(raw,'.jpg')
    current = normalize_report_image(raw,'.jpg',cover_photo=True)
    assert (current.width,current.height) == (legacy.width,legacy.height)
    with Image.open(BytesIO(current.data)) as a, Image.open(BytesIO(legacy.data)) as b:
        difference = ImageStat.Stat(ImageChops.difference(a,b))
        assert max(difference.mean) < 3, difference.mean
        assert max(difference.rms) < 5, difference.rms


def test_low_headroom_refuses_before_decoder_open(monkeypatch):
    from app import monthly_report_docx as docx
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1)
    monkeypatch.setattr(docx.Image, 'open', lambda *a: pytest.fail('decoder must not open'))
    with pytest.raises(ValueError,match='needs more memory'):
        replace_cover_picture(ResolvedBlock('cover_photo','Omit'),b'input','.png',{})

@pytest.mark.parametrize('codec,factor', [('WEBP',24),('HEIF',16),('PNG',8)])
def test_codec_memory_estimate_boundary(monkeypatch, codec, factor):
    from app.monthly_report_cover_images import check_cover_headroom
    from app import monthly_report_render_jobs as jobs
    required = 2 * 64*MIB + 40_000_000*factor + 32*MIB
    monkeypatch.setattr(jobs,'memory_headroom',lambda: required-1)
    with pytest.raises(ValueError,match='needs more memory'):
        check_cover_headroom(64*MIB,pixels=40_000_000,image_format=codec)
    monkeypatch.setattr(jobs,'memory_headroom',lambda: required)
    check_cover_headroom(64*MIB,pixels=40_000_000,image_format=codec)


def test_starting_report_replacement_uses_cover_limit_and_preserves_failed_selection(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_section_ui as ui
    original_uploader = ui.st.file_uploader
    incoming = {'file':None}
    def upload(*args,**kwargs):
        widget = original_uploader(*args,**kwargs)
        return incoming['file'] or widget
    monkeypatch.setattr(ui.st,'file_uploader',upload)
    app = AppTest.from_string('''
import streamlit as st
from types import SimpleNamespace
from app.monthly_report_section_ui import _replacement_pictures
plan = st.session_state.setdefault('plan', {})
_replacement_pictures(SimpleNamespace(key='cover'), 'source-cover', plan)
''').run()
    assert not app.exception
    assert app.get('file_uploader')[0].proto.max_upload_size_mb == 64
    source = BytesIO(image_bytes()); source.name = 'synthetic.png'; source.size = len(source.getbuffer())
    incoming['file'] = source
    app.run()
    assert not app.exception and not app.error
    before = app.session_state.plan['new_assets']
    assert before[0][0] == 'cover_photo'
    bad = BytesIO(b'not-an-image'); bad.name = 'bad.png'; bad.size = len(bad.getbuffer())
    incoming['file'] = bad
    app.run()
    assert not app.exception and app.error
    assert app.session_state.plan['new_assets'] == before


def test_progressive_jpeg_coefficients_reserved_before_pillow(monkeypatch):
    from app import monthly_report_docx as docx
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_cover_images import cover_codec_header
    stream = BytesIO()
    Image.new('RGB',(8000,5000),'navy').save(stream,'JPEG',progressive=True,subsampling=0)
    raw = stream.getvalue()
    raw += b'\0' * (64*MIB-len(raw))
    header = cover_codec_header(raw)
    assert header.format == 'JPEG' and header.coefficient_bytes >= 240_000_000
    monkeypatch.setattr(jobs,'memory_headroom',lambda: 350*MIB)
    monkeypatch.setattr(docx.Image,'open',lambda *a: pytest.fail('progressive decode must not initialize'))
    with pytest.raises(ValueError,match='needs more memory'):
        replace_cover_picture(ResolvedBlock('cover_photo','Omit'),raw,'.jpg',{})


def test_webp_headers_checked_before_anim_decoder_initialization(monkeypatch):
    from app import monthly_report_docx as docx
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_cover_images import cover_codec_header
    stream = BytesIO()
    Image.new('RGB',(8000,5000),'navy').save(stream,'WEBP')
    raw = stream.getvalue()
    header = cover_codec_header(raw)
    assert (header.width,header.height) == (8000,5000)
    monkeypatch.setattr(jobs,'memory_headroom',lambda: 350*MIB)
    monkeypatch.setattr(docx.Image,'open',lambda *a: pytest.fail('WebP AnimDecoder must not initialize'))
    with pytest.raises(ValueError,match='needs more memory'):
        replace_cover_picture(ResolvedBlock('cover_photo','Omit'),raw,'.png',{})


@pytest.mark.parametrize('progressive', [False,True])
@pytest.mark.parametrize('mode', ['L','RGB','CMYK'])
def test_jpeg_header_components_and_original_dimensions(progressive,mode):
    from app.monthly_report_cover_images import cover_codec_header
    stream = BytesIO()
    Image.new(mode,(81,57)).save(stream,'JPEG',progressive=progressive,subsampling=0)
    header = cover_codec_header(stream.getvalue())
    assert (header.format,header.width,header.height)==('JPEG',81,57)
    if progressive:
        assert header.coefficient_bytes >= 81*57*len(mode)*2
    else:
        assert header.coefficient_bytes == 0


@pytest.mark.parametrize('lossless', [False,True])
@pytest.mark.parametrize('alpha', [False,True])
def test_webp_header_variants(lossless,alpha):
    from app.monthly_report_cover_images import cover_codec_header
    stream = BytesIO()
    Image.new('RGBA' if alpha else 'RGB',(81,57),(40,50,60,90) if alpha else 'navy').save(stream,'WEBP',lossless=lossless)
    header = cover_codec_header(stream.getvalue())
    assert (header.format,header.width,header.height)==('WEBP',81,57)


@pytest.mark.parametrize('raw',[b'\xff\xd8', b'\xff\xd8\xff\xe0\xff\xff',
    b'RIFF\xff\xff\xff\xffWEBP', b'RIFF\x0c\0\0\0WEBPVP8 '])
def test_truncated_codec_headers_fail_closed(raw):
    from app.monthly_report_cover_images import cover_codec_header
    with pytest.raises(ValueError,match='header could not be read safely'):
        cover_codec_header(raw)


def test_oversized_webp_dimensions_rejected_without_initializing_decoder(monkeypatch):
    from app import monthly_report_docx as docx
    width,height = 8000,6000
    bits = (width-1) | ((height-1)<<14)
    payload = b'\x2f' + bits.to_bytes(4,'little')
    chunk = b'VP8L' + len(payload).to_bytes(4,'little') + payload + b'\0'
    raw = b'RIFF' + (4+len(chunk)).to_bytes(4,'little') + b'WEBP' + chunk
    monkeypatch.setattr(docx.Image,'open',lambda *a: pytest.fail('oversized WebP must not initialize'))
    with pytest.raises(ValueError,match='too large to decode safely'):
        replace_cover_picture(ResolvedBlock('cover_photo','Omit'),raw,'.webp',{})


def test_noninterleaved_jpeg_reserves_original_coefficients():
    from app.monthly_report_cover_images import cover_codec_header
    stream = BytesIO()
    Image.new('RGB',(81,57),'navy').save(stream,'JPEG',subsampling=0)
    raw = stream.getvalue()
    scan = raw.index(b'\xff\xda')
    length = int.from_bytes(raw[scan+2:scan+4],'big')
    # A synthetic one-component first-scan header proves admission accounting;
    # this is intentionally not claimed as an entropy-valid multi-scan image.
    payload = b'\x01' + raw[scan+5:scan+7] + b'\0\x3f\0'
    changed = raw[:scan+2] + (len(payload)+2).to_bytes(2,'big') + payload + raw[scan+2+length:]
    assert cover_codec_header(changed).coefficient_bytes >= 81*57*3*2

@pytest.mark.parametrize("platform_base", [1000, 1024])
def test_cover_native_transport_ceiling_preserves_exact_backend_cap(platform_base):
    from app.monthly_report_cover_images import cover_uploader_limit_mb, read_picture_upload
    ceiling = cover_uploader_limit_mb()
    assert ceiling == 68
    assert 64*MIB <= ceiling*platform_base**2
    class Oversized:
        size = 64*MIB+1
        def tell(self): raise AssertionError("overflow must reject before any read/copy")
    with pytest.raises(ValueError, match="64 MiB"):
        read_picture_upload(Oversized(), cover_photo=True)


def test_cover_native_transport_padding_is_in_actual_memory_headroom(monkeypatch):
    from app import monthly_report_cover_images as images, monthly_report_render_jobs as jobs
    # Two worst-case Windows-native buffers (68 MiB each) are already resident.
    # No decoder may ignore them merely because the exact server cap is64MiB.
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 512*MIB-192*MIB-2*68*MIB)
    with pytest.raises(ValueError, match="memory"):
        images.check_cover_headroom(64*MIB, pixels=40_000_000, image_format="JPEG")


def test_installed_streamlit_frontend_converts_cover_ceiling_on_both_platforms():
    """Execute the actual locked bundle conversion, not a mock of its units."""
    import json
    from pathlib import Path
    import re
    import subprocess
    import streamlit
    from app.monthly_report_cover_images import cover_uploader_limit_mb
    folder = Path(streamlit.__file__).parent/'static/static/js'
    files = list(folder.glob('*.js'))
    uploader = next(p.read_text() for p in files
                    if p.name.startswith('FileUploader.') and 'maxUploadSizeMb' in p.read_text())
    assert re.search(r'\w+\(\w+,\w+\.Megabyte,\w+\.Byte\)', uploader)
    bundle = next(p.read_text() for p in files
                  if 'Megabyte=' in p.read_text() and 'nt=s()?1024:1e3' in p.read_text())
    conversion = re.search(r'it=(\(e,t,n\)=>\{.*?\}),at=', bundle).group(1)
    platform_bundle = next(p.read_text() for p in files
                           if 'function Vt(){return/^Win/i.test(navigator.platform)}' in p.read_text())
    platform = re.search(r'function Vt\(\)\{[^}]+\}', platform_bundle).group(0)
    script = """
const results=[];
for(const name of ['Linux x86_64','MacIntel','Win32']){
 const navigator={platform:name};
 PLATFORM
 const s=Vt, nt=s()?1024:1e3, rt=['gb','mb','kb','b'];
 const convert=CONVERT;
 results.push([name,convert(64,'mb','b'),convert(CEILING,'mb','b')]);
}
console.log(JSON.stringify(results));
""".replace('PLATFORM', platform).replace('CONVERT', conversion).replace('CEILING', str(cover_uploader_limit_mb()))
    rows = json.loads(subprocess.check_output(['node','-e',script], text=True, timeout=10))
    assert rows == [
        ['Linux x86_64',64_000_000,68_000_000],
        ['MacIntel',64_000_000,68_000_000],
        ['Win32',64*MIB,68*MIB],
    ]
    assert all(native >= 64*MIB for _,_,native in rows)


def test_ordinary_cover_widget_uses_transport_ceiling_but_help_keeps_exact_cap(tmp_path, monkeypatch):
    from test_cover_recovery_ui import harness
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = harness()
    widget = app.get('file_uploader')[0]
    assert widget.proto.max_upload_size_mb == 68
    assert '64 MiB' in widget.proto.help
    assert not app.exception


def test_native_deepcopy_read_reuses_immutable_buffer_without_second_copy():
    from copy import deepcopy
    import tracemalloc
    from streamlit.proto.Common_pb2 import FileURLs
    from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec
    from app.monthly_report_cover_images import read_picture_upload
    raw = b'x' * (8*MIB)
    native = UploadedFile(UploadedFileRec('id', 'photo.jpg', 'image/jpeg', raw), FileURLs())
    tracemalloc.start()
    try:
        returned = deepcopy(native)  # Locked Streamlit register_widget behavior.
        returned.seek(7)
        before, _ = tracemalloc.get_traced_memory()
        result = read_picture_upload(returned, cover_photo=True)
        _, peak = tracemalloc.get_traced_memory()
        assert peak - before < MIB, 'Reading must not allocate another full uploaded buffer'
        assert result is BytesIO.getvalue(returned)
        assert result == raw and returned.tell() == 7
        returned.seek(0); returned.write(b'y')
        assert result == raw, 'Returned bytes remain immutable after uploader mutation'
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize('claimed_size', [0, 1, 64*MIB])
def test_native_actual_size_guard_rejects_lying_metadata_without_materializing(claimed_size):
    from streamlit.proto.Common_pb2 import FileURLs
    from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec
    from app.monthly_report_cover_images import read_picture_upload
    source = UploadedFile(UploadedFileRec('id', 'photo.jpg', 'image/jpeg', b'x'*(64*MIB+1)), FileURLs())
    source.size = claimed_size
    source.seek(7)
    import tracemalloc
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match='64 MiB'):
            read_picture_upload(source, cover_photo=True)
        assert tracemalloc.get_traced_memory()[1] < MIB
        assert source.tell() == 7
    finally:
        tracemalloc.stop()


def test_untrusted_bytesio_subclass_stays_on_bounded_read_not_getvalue():
    from app.monthly_report_cover_images import read_picture_upload
    class Foreign(BytesIO):
        def getvalue(self):
            raise AssertionError('Untrusted getvalue must not run')
        def read(self, count=-1):
            assert count == 64*MIB+1
            return super().read(count)
    source=Foreign(b'abc'); source.seek(1)
    assert read_picture_upload(source, cover_photo=True)==b'abc'
    assert source.tell()==1
