"""Passive Windows-metafile review rasterization; native bytes stay in the DOCX."""

from hashlib import sha256
from functools import lru_cache
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image


METAFILES = {'.emf', '.wmf'}
_RENDER_VERSION = 'passive-metafile-v2'


def supported_metafile(raw, suffix):
    # Deferred imports keep the package validator and inspector independent at
    # module initialization. These are the same validators used by native export.
    from app.monthly_report_native_package import _static_emf, _static_wmf
    if not {'.emf': _static_emf, '.wmf': _static_wmf}.get(suffix.lower(), lambda _: False)(raw):
        return False
    try:
        with Image.open(BytesIO(raw)) as picture:
            width, height = picture.size
        return 0 < min(width, height) and max(width, height) <= 20000 and width * height <= 100_000_000
    except (OSError, ValueError, SyntaxError, ZeroDivisionError, Image.DecompressionBombError):
        return False


def _image_package(raw, suffix):
    if not supported_metafile(raw, suffix):
        raise ValueError('This drawing is not a supported static metafile.')
    with Image.open(BytesIO(raw)) as picture:
        width, height = picture.size
    if min(width, height) <= 0 or max(width, height) / min(width, height) > 30:
        raise ValueError('This drawing has unsupported dimensions.')
    scale = min(7 / width, 9 / height)
    cx, cy = round(width * scale * 914400), round(height * scale * 914400)
    # A fresh passive package contains only the validated image: no source
    # macros, links, fields, text boxes, metadata or unreviewed neighbouring art.
    parts = {
        '[Content_Types].xml': f'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="{suffix[1:]}" ContentType="image/x-{suffix[1:]}"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''.encode(),
        '_rels/.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="doc" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/_rels/document.xml.rels': f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="image" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/drawing{suffix}"/></Relationships>'.encode(),
        'word/media/drawing' + suffix: raw,
        'word/document.xml': f'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body><w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:rPr><w:sz w:val="2"/></w:rPr></w:pPr><w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="0" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH><wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV><wp:extent cx="{cx}" cy="{cy}"/><wp:wrapNone/><wp:docPr id="1" name="Reviewed drawing"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="Drawing"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="image"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p><w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="0" w:footer="0"/></w:sectPr></w:body></w:document>'''.encode(),
    }
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return output.getvalue(), (cx / 12700, cy / 12700)


@lru_cache(maxsize=8)
def _renderer_fingerprint(binary, font_config, font_path):
    facts = [_RENDER_VERSION, binary, font_config, font_path]
    paths = [Path(binary)] if binary else []
    if font_config:
        paths.append(Path(font_config))
    try:
        result = subprocess.run(['fc-list', '-f', '%{file}\\n'], capture_output=True,
                                timeout=5, check=True)
        paths.extend(Path(name) for name in result.stdout.decode(errors='replace').splitlines())
    except (OSError, subprocess.SubprocessError):
        # No persistent cache reuse when the font environment cannot be bound.
        facts.append(str(os.getpid()))
    for path in sorted(set(paths)):
        try:
            stat = path.stat()
            facts.append(f'{path}:{stat.st_size}:{stat.st_mtime_ns}')
        except OSError:
            facts.append(str(path) + ':missing')
    return '\n'.join(facts).encode()


def rasterize_metafile(raw, suffix):
    """Prepare a full lossless raster for the existing pricing/image review gate."""
    import fitz
    from app import monthly_report_library as library
    from app.monthly_report_import import ImportError
    from app.monthly_report_word_pages import _RENDER_LOCK, _render

    suffix = suffix.lower()
    if not supported_metafile(raw, suffix):
        raise ImportError('This drawing could not be validated as a static image. It remains in review.')
    directory = library._root() / 'imports' / 'metafile-review'
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint = _renderer_fingerprint(shutil.which('libreoffice') or shutil.which('soffice') or '',
                                        os.environ.get('FONTCONFIG_FILE', ''), os.environ.get('FONTCONFIG_PATH', ''))
    key = sha256(fingerprint + suffix.encode() + raw).hexdigest()
    cached = directory / (key + '.png')
    if cached.exists() and cached.stat().st_size <= 24 * 1024 * 1024:
        return cached.read_bytes()
    if not _RENDER_LOCK.acquire(blocking=False):
        raise ImportError('Another report picture is being prepared. Try again in a moment.')
    try:
        package, size = _image_package(raw, suffix)
        with tempfile.TemporaryDirectory(prefix='drawing-', dir=directory) as temporary:
            temporary = Path(temporary)
            source = temporary / 'passive-drawing.docx'
            source.write_bytes(package)
            with fitz.open(_render(source, temporary)) as pdf:
                if len(pdf) != 1:
                    raise ImportError('The drawing did not fit its review page. It remains in review.')
                # The fresh image is anchored at page origin, independently of
                # paragraph metrics. Crop exactly its declared frame, preserving
                # all image pixels without adding letter-page margins to assets.
                frame = fitz.Rect(0, 0, *size)
                result = pdf[0].get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72),
                                          clip=frame, alpha=False).tobytes('png')
            if len(result) > 24 * 1024 * 1024:
                raise ImportError('The drawing review image exceeds the preparation limit.')
            staged = temporary / 'review.png'
            staged.write_bytes(result)
            staged.replace(cached)
            return result
    except (ValueError, OSError) as exc:
        raise ImportError('The static drawing could not be prepared for review. Your original is unchanged.') from exc
    finally:
        _RENDER_LOCK.release()
