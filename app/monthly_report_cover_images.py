"""Direct cover-photo admission, not DOCX/native-artwork or logo policy."""

from dataclasses import dataclass

MAX_COVER_PHOTO_BYTES = 64 * 1024 * 1024
MAX_REPORT_IMAGE_BYTES = 30 * 1024 * 1024
_MIB = 1024 * 1024
MEMORY_ERROR = ("This photograph needs more memory than is currently available. "
                "Resize a copy or try again when other reports finish; your current artwork is unchanged.")


def image_byte_limit(*, cover_photo=False):
    return MAX_COVER_PHOTO_BYTES if cover_photo else MAX_REPORT_IMAGE_BYTES


def image_size_error(*, cover_photo=False):
    return (f"Choose an image no larger than {image_byte_limit(cover_photo=cover_photo) // (1024 * 1024)} MiB. "
            "Export a smaller copy; your current artwork is unchanged.")


def read_picture_upload(upload, *, cover_photo=False):
    """Never copy an unbounded upload; restore its cursor for later reruns."""
    limit = image_byte_limit(cover_photo=cover_photo)
    if getattr(upload, 'size', 0) > limit:
        raise ValueError(image_size_error(cover_photo=cover_photo))
    position = upload.tell()
    try:
        upload.seek(0)
        raw = upload.read(limit + 1)
    finally:
        upload.seek(position)
    if len(raw) > limit:
        raise ValueError(image_size_error(cover_photo=cover_photo))
    if not raw:
        raise ValueError("This image is empty. Choose another image; your current artwork is unchanged.")
    return raw


def check_cover_headroom(encoded_bytes, *, pixels=0, image_format="", coefficient_bytes=0):
    """Conservative admission estimate, not a claim about every codec's RSS.

    Native uploader buffers already count in the actual cgroup's usage. Reserve
    further encoded copies, decoder/work rasters and fixed working overhead.
    JPEG uses decoder downsampling AFTER its original pixel gate; other codecs
    must retain enough room for their full raster. Unknown cgroups still get a
    bounded fallback, rather than interpreting unknown as unlimited memory.
    """
    from app.monthly_report_render_jobs import memory_headroom
    headroom = memory_headroom()
    available = headroom if headroom is not None else 256 * _MIB
    if image_format == "JPEG":
        raster = 96 * _MIB  # Decoder draft plus resize/output working copies.
    else:
        factor = {"WEBP": 24, "HEIF": 16}.get(image_format, 8)
        raster = pixels * factor
    required = 2 * encoded_bytes + raster + coefficient_bytes + 32 * _MIB
    if available < required:
        raise ValueError(MEMORY_ERROR)


@dataclass(frozen=True)
class CoverHeader:
    format: str
    width: int
    height: int
    coefficient_bytes: int = 0


def cover_codec_header(raw):
    """Read bounded JPEG/WebP metadata BEFORE initializing their decoders.

    No decompression, metadata copying, source edits or entropy-stream scan.
    Ambiguous/unsupported headers fail closed rather than assuming low memory.
    Other admitted formats retain their normal header-only Pillow inspection.
    """
    data = memoryview(raw)
    invalid = "Choose a fresh PNG or JPEG export; this photograph's header could not be read safely."
    if raw.startswith(b'\xff\xd8'):
        pos, frame = 2, None
        for _ in range(4096):
            if pos >= len(data) or data[pos] != 255:
                break
            while pos < len(data) and data[pos] == 255:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]; pos += 1
            if marker in (0, 0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                break
            if marker == 1:  # TEM is the only stand-alone non-image marker.
                continue
            if pos + 2 > len(data):
                break
            length = int.from_bytes(data[pos:pos+2], 'big')
            end = pos + length
            if length < 2 or end > len(data):
                break
            payload = data[pos+2:end]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                if marker not in (0xC0, 0xC1, 0xC2) or frame is not None or len(payload) < 6:
                    break
                height = int.from_bytes(payload[1:3], 'big')
                width = int.from_bytes(payload[3:5], 'big')
                components = payload[5]
                if (payload[0] != 8 or not width or not height or components not in (1, 3, 4)
                        or len(payload) != 6 + 3 * components):
                    break
                sampling = [payload[7+3*i] for i in range(components)]
                if any(not (1 <= value >> 4 <= 4 and 1 <= (value & 15) <= 4) for value in sampling):
                    break
                frame = (width, height, components, marker == 0xC2)
            if marker == 0xDA:  # First scan: noninterleaved sequential needs coefficient storage too.
                if frame is None or not payload or len(payload) != 1 + 2*payload[0] + 3:
                    break
                width, height, components, progressive = frame
                if not 1 <= payload[0] <= components:
                    break
                coefficients = 0
                if progressive or payload[0] != components:
                    # Every component at full resolution, rounded to maximum
                    # MCU edges, is conservative even for unusual sampling.
                    coefficients = ((width+31)//32*32) * ((height+31)//32*32) * components * 2
                return CoverHeader('JPEG', width, height, coefficients)
            pos = end
        raise ValueError(invalid)
    if len(data) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        end = 8 + int.from_bytes(data[4:8], 'little')
        if end > len(data) or end < 12:
            raise ValueError(invalid)
        pos, canvas = 12, None
        for _ in range(4096):
            if pos + 8 > end:
                break
            kind = bytes(data[pos:pos+4])
            size = int.from_bytes(data[pos+4:pos+8], 'little')
            start = pos+8; stop = start+size
            if stop > end:
                break
            payload = data[start:stop]
            if kind in (b'ANIM', b'ANMF'):
                raise ValueError("Choose a single image; use a PDF for multiple pages.")
            if kind == b'VP8X':
                if size != 10 or canvas is not None:
                    break
                if payload[0] & 2:
                    raise ValueError("Choose a single image; use a PDF for multiple pages.")
                canvas = (1+int.from_bytes(payload[4:7], 'little'), 1+int.from_bytes(payload[7:10], 'little'))
            elif kind in (b'VP8 ', b'VP8L'):
                if kind == b'VP8 ':
                    if size < 10 or payload[0] & 1 or bytes(payload[3:6]) != b'\x9d\x01\x2a':
                        break
                    dimensions = (int.from_bytes(payload[6:8], 'little') & 0x3FFF,
                                  int.from_bytes(payload[8:10], 'little') & 0x3FFF)
                else:
                    if size < 5 or payload[0] != 0x2F:
                        break
                    bits = int.from_bytes(payload[1:5], 'little')
                    if bits >> 29:
                        break
                    dimensions = ((bits & 0x3FFF)+1, ((bits >> 14) & 0x3FFF)+1)
                if not all(dimensions) or (canvas is not None and dimensions != canvas):
                    break
                return CoverHeader('WEBP', *dimensions)
            pos = stop + (size & 1)
        raise ValueError(invalid)
    return None


def normalize_cover_photo(raw, suffix):
    """Share report assembly admission; busy/error never replaces old artwork."""
    from app.monthly_report_render_jobs import work_slot, RenderBusy
    from app.monthly_report_docx import normalize_report_image
    try:
        with work_slot(wait_seconds=0):
            return normalize_report_image(raw, suffix, cover_photo=True)
    except RenderBusy as exc:
        raise ValueError("Another report or photograph is being prepared. Try again shortly; your current artwork is unchanged.") from exc
