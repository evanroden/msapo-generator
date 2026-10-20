"""Remove authoring metadata from pictures inside a finished report package.

A generated report can carry pictures kept from an installed design, a source
report or an approved logo. Their EXIF, XMP, IPTC and comment records can name
the original author, software or device. This module strips those records from
the export derivative only:

* decoded pixels, dimensions, colour profiles (ICC), JFIF density, PNG pHYs and
  the display orientation stay the same; no picture is re-encoded;
* source originals, the design store and saved asset records are not touched;
* anything that is not a recognised JPEG, PNG, GIF or WebP container (XML parts,
  TIFF, BMP, EMF/WMF, malformed data) passes through unchanged.

When a JPEG or PNG declares a non-default orientation, a minimal EXIF record
holding only that orientation is kept so the picture still displays upright.
"""
from __future__ import annotations

import struct
import zlib
from io import BytesIO
from zipfile import BadZipFile, ZipFile, ZipInfo

_ORIENTATION_TAG = 0x0112
_EXIF_PREFIX = b"Exif\x00\x00"

# JPEG application segments that affect decoding or colour are kept. Everything
# else in APP0-APP15 and every COM segment is authoring/device metadata.
_JPEG_KEEP_APP = {
    0xE0: (b"JFIF\x00", b"AVI1"),   # JFIF density / Motion-JPEG layout
    0xE2: (b"ICC_PROFILE\x00",),    # colour profile
    0xEE: (b"Adobe",),              # colour transform flag used by decoders
}
_PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}
_GIF_XMP = b"XMP DataXMP"


def _orientation(tiff: bytes) -> int:
    """Return the IFD0 orientation from a TIFF-structured EXIF block, or 1."""
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return 1
    order = "<" if tiff[:2] == b"II" else ">"
    try:
        offset = struct.unpack(order + "I", tiff[4:8])[0]
        (count,) = struct.unpack(order + "H", tiff[offset:offset + 2])
        for index in range(count):
            entry = tiff[offset + 2 + 12 * index:offset + 14 + 12 * index]
            if len(entry) < 12:
                return 1
            tag, kind, number = struct.unpack(order + "HHI", entry[:8])
            if tag == _ORIENTATION_TAG and kind == 3 and number == 1:
                value = struct.unpack(order + "H", entry[8:10])[0]
                return value if 1 <= value <= 8 else 1
    except struct.error:
        return 1
    return 1


def _orientation_tiff(value: int) -> bytes:
    """A TIFF block with one IFD0 entry: Orientation (SHORT, 1 value)."""
    return (b"MM\x00\x2a\x00\x00\x00\x08" + struct.pack(">H", 1)
            + struct.pack(">HHIHH", _ORIENTATION_TAG, 3, 1, value, 0)
            + b"\x00\x00\x00\x00")


def _jpeg_segment_kept(marker: int, payload: bytes) -> bool:
    if marker == 0xFE:
        return False  # COM
    if 0xE0 <= marker <= 0xEF:
        return payload.startswith(_JPEG_KEEP_APP.get(marker, ()))
    return True


def _strip_jpeg(raw: bytes) -> bytes:
    if not raw.startswith(b"\xff\xd8"):
        return raw
    out = bytearray(b"\xff\xd8")
    pos, size, orientation, after_app0 = 2, len(raw), 1, None
    in_scan = False
    while pos < size:
        if in_scan:
            # Entropy-coded data: 0xFF is followed by 0x00 (stuffing), a
            # restart marker or fill bytes; anything else is a real marker.
            mark = raw.find(b"\xff", pos)
            while mark != -1 and mark + 1 < size and (
                    raw[mark + 1] == 0x00 or 0xD0 <= raw[mark + 1] <= 0xD7 or raw[mark + 1] == 0xFF):
                mark = raw.find(b"\xff", mark + 2 if raw[mark + 1] != 0xFF else mark + 1)
            if mark == -1 or mark + 1 >= size:
                return raw  # no end of image: leave unusual data unchanged
            out += raw[pos:mark]
            pos = mark
            in_scan = False
            continue
        if raw[pos] != 0xFF:
            return raw
        while pos < size and raw[pos] == 0xFF:
            pos += 1
        if pos >= size:
            return raw
        marker = raw[pos]
        pos += 1
        if marker == 0xD9:  # end of the primary image; later data is dropped
            out += b"\xff\xd9"
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            out += bytes((0xFF, marker))
            continue
        if pos + 2 > size:
            return raw
        length = int.from_bytes(raw[pos:pos + 2], "big")
        if length < 2 or pos + length > size:
            return raw
        payload = raw[pos + 2:pos + length]
        segment = bytes((0xFF, marker)) + raw[pos:pos + length]
        pos += length
        if marker == 0xE1 and payload.startswith(_EXIF_PREFIX):
            orientation = _orientation(payload[len(_EXIF_PREFIX):]) if orientation == 1 else orientation
        if _jpeg_segment_kept(marker, payload):
            out += segment
            if marker == 0xE0 and after_app0 is None and len(out) == 2 + len(segment):
                after_app0 = len(out)
        if marker == 0xDA:
            in_scan = True
    else:
        return raw  # data ended before an end-of-image marker
    if orientation != 1:
        record = _EXIF_PREFIX + _orientation_tiff(orientation)
        at = after_app0 or 2
        out[at:at] = b"\xff\xe1" + struct.pack(">H", len(record) + 2) + record
    return bytes(out)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _strip_png(raw: bytes) -> bytes:
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw
    out, pos, size = bytearray(raw[:8]), 8, len(raw)
    while pos < size:
        if pos + 12 > size:
            return raw
        length = struct.unpack(">I", raw[pos:pos + 4])[0]
        kind = raw[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > size:
            return raw
        data = raw[pos + 8:pos + 8 + length]
        if kind == b"eXIf":
            tiff = data[len(_EXIF_PREFIX):] if data.startswith(_EXIF_PREFIX) else data
            value = _orientation(tiff)
            if value != 1:
                out += _png_chunk(b"eXIf", _orientation_tiff(value))
        elif kind not in _PNG_DROP:
            out += raw[pos:end]
        pos = end
        if kind == b"IEND":
            return bytes(out)
    return raw


def _gif_sub_blocks(raw: bytes, pos: int) -> int:
    """Return the offset just after a GIF data sub-block sequence."""
    while True:
        if pos >= len(raw):
            raise ValueError("truncated GIF")
        length = raw[pos]
        pos += 1 + length
        if length == 0:
            return pos


def _strip_gif(raw: bytes) -> bytes:
    if not raw.startswith((b"GIF87a", b"GIF89a")) or len(raw) < 13:
        return raw
    try:
        pos = 13
        if raw[10] & 0x80:
            pos += 3 * (2 << (raw[10] & 0x07))
        out = bytearray(raw[:pos])
        while pos < len(raw):
            block = raw[pos]
            if block == 0x3B:  # trailer
                out += raw[pos:pos + 1]
                return bytes(out)
            if block == 0x21:  # extension
                label = raw[pos + 1]
                end = _gif_sub_blocks(raw, pos + 2)
                application = raw[pos + 3:pos + 14] if label == 0xFF else b""
                if label != 0xFE and application != _GIF_XMP:
                    out += raw[pos:end]
                pos = end
            elif block == 0x2C:  # image descriptor (+ local colour table) + LZW data
                flags = raw[pos + 9]
                start = pos
                pos += 10
                if flags & 0x80:
                    pos += 3 * (2 << (flags & 0x07))
                pos = _gif_sub_blocks(raw, pos + 1)
                out += raw[start:pos]
            else:
                return raw
    except (IndexError, ValueError):
        return raw
    return raw


def _strip_webp(raw: bytes) -> bytes:
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        return raw
    chunks, pos, size, removed = [], 12, len(raw), False
    while pos < size:
        if pos + 8 > size:
            return raw
        kind = raw[pos:pos + 4]
        length = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        end = pos + 8 + length + (length & 1)
        if end > size:
            return raw
        if kind in (b"EXIF", b"XMP "):
            removed = True
        else:
            chunks.append(bytearray(raw[pos:end]))
        pos = end
    if not removed:
        return raw
    for chunk in chunks:
        if chunk[:4] == b"VP8X" and len(chunk) >= 9:
            chunk[8] &= ~0x0C & 0xFF  # clear the EXIF and XMP presence flags
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def strip_image_metadata(raw: bytes) -> bytes:
    """Return the picture without authoring metadata, or the input unchanged."""
    if raw.startswith(b"\xff\xd8"):
        return _strip_jpeg(raw)
    if raw.startswith(b"\x89PNG"):
        return _strip_png(raw)
    if raw.startswith(b"GIF8"):
        return _strip_gif(raw)
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return _strip_webp(raw)
    return raw


def sanitize_package_media(package: bytes) -> bytes:
    """Strip picture metadata in a DOCX/ZIP package; other parts are untouched.

    Entry order, names, timestamps and compression are preserved. When no
    picture carries removable metadata, or the bytes are not a ZIP package,
    the original bytes are returned as-is.
    """
    try:
        source = ZipFile(BytesIO(package))
    except BadZipFile:
        return package
    output = BytesIO()
    changed = False
    with source, ZipFile(output, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if not info.is_dir():
                clean = strip_image_metadata(data)
                if clean != data:
                    changed, data = True, clean
            entry = ZipInfo(info.filename, info.date_time)
            entry.compress_type = info.compress_type
            entry.create_system = info.create_system
            entry.external_attr = info.external_attr
            target.writestr(entry, data)
    return output.getvalue() if changed else package
