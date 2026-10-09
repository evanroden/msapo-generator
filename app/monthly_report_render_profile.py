"""Immutable, measured PDF compatibility evidence for an installed Word design."""
from io import BytesIO
import base64
import hashlib
import json
from pathlib import Path
import posixpath
import re
import subprocess
import sys
from zipfile import ZipFile

from lxml import etree
from PIL import Image, ImageChops, ImageStat

VERSION = 1
DEFAULT = {"version": VERSION, "cover_zero_origin": False}
MAX_PDF_BYTES = 30 * 1024 * 1024
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def validate_profile(value=None):
    value = dict(DEFAULT) if value is None else value
    if (not isinstance(value, dict) or set(value) != set(DEFAULT)
            or type(value["version"]) is not int or value["version"] != VERSION
            or type(value["cover_zero_origin"]) is not bool):
        raise ValueError("Unsupported saved PDF rendering profile.")
    return dict(value)


def identity(source_hash, pdf_hash, profile):
    payload = {"source_sha256": source_hash, "companion_sha256": pdf_hash,
               "render_profile": validate_profile(profile)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _thumbnail(raw):
    with Image.open(BytesIO(raw)) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("Reference cover image exceeds the calibration image limit.")
        image.load()
        image = image.convert("RGB").resize((64, 64))
        return base64.b64encode(image.tobytes()).decode()


def _pdf_evidence(path):
    """Runs only in the bounded subprocess, never executes document actions."""
    import pymupdf as fitz
    with fitz.open(path) as pdf:
        if pdf.is_encrypted or not 1 <= len(pdf) <= 500:
            raise ValueError("Use an unlocked reference PDF with 1 to 500 pages.")
        page = pdf[0]
        text = page.get_text()
        if len(text) > 100_000:
            raise ValueError("Reference cover text exceeds the calibration limit.")
        images = []
        # Read image dictionaries before requesting pixel hashes: get_image_info
        # with xrefs decodes images, so checking its result would be too late.
        objects = page.get_images(full=True)
        pixels = sum(item[2] * item[3] for item in objects)
        safe_images = len(objects) <= 32 and pixels <= 20_000_000
        for info in (page.get_image_info(xrefs=True) if safe_images else []):
            if not info.get("xref") or info["width"] * info["height"] > 20_000_000:
                continue
            data = pdf.extract_image(info["xref"])
            if len(data["image"]) <= MAX_PDF_BYTES:
                images.append({"bbox": info["bbox"], "thumbnail": _thumbnail(data["image"])})
        return {"text": text, "images": images, "producer": str((pdf.metadata or {}).get("producer", ""))[:500],
                "pages": len(pdf)}


def inspect_companion(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("The companion PDF must be nonempty and at most 30 MB.")
    try:
        result = subprocess.run([sys.executable, "-m", __name__, str(path.resolve())],
                                capture_output=True, timeout=25, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Reference PDF inspection timed out. The existing design is unchanged.") from exc
    if result.returncode or len(result.stdout) > 1_000_000:
        raise ValueError("Reference PDF could not be safely inspected. The existing design is unchanged.")
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Reference PDF inspection returned invalid evidence.") from exc


def _cover_evidence(source):
    with ZipFile(source) as archive:
        root = etree.fromstring(archive.read("word/document.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
        body = root.find("w:body", NS)
        cover = []
        for node in body:
            cover.append(node)
            if node.find('.//w:sectPr', NS) is not None or node.tag == '{' + NS['w'] + '}sectPr':
                break
            if len(cover) >= 100:
                break
        texts = []
        for node in cover:
            for paragraph in node.iter('{' + NS['w'] + '}p'):
                text = ''.join(paragraph.xpath('./w:r/w:t/text()', namespaces=NS))
                if text.strip() and text.strip().casefold() not in {'=', 'insert client logo', 'insert logo'}:
                    texts.append(text)
        rels = etree.fromstring(archive.read('word/_rels/document.xml.rels'))
        targets = {n.get('Id'):posixpath.normpath(posixpath.join('word',n.get('Target',''))) for n in rels if n.get('TargetMode') != 'External'}
        images = []
        for node in cover:
            for anchor in node.iter('{' + NS['wp'] + '}anchor'):
                y = anchor.find('wp:positionV', NS)
                extent = anchor.find('wp:extent', NS)
                blips = anchor.findall('.//a:blip', NS)
                # Calibrate a plain photo frame, not grouped/decorative artwork.
                if y is None or y.get('relativeFrom') != 'paragraph' or extent is None or len(blips) != 1:
                    continue
                if any(any(value not in {'0', '0.0'} for value in crop.attrib.values()) for crop in anchor.findall('.//a:srcRect', NS)):
                    continue
                offset = y.find('wp:posOffset', NS)
                target = targets.get(blips[0].get('{' + NS['r'] + '}embed'))
                if offset is None or not target or target not in archive.namelist():
                    continue
                width, height = int(extent.get('cx', '0'))/12700, int(extent.get('cy', '0'))/12700
                if width < 200 or height < 100:
                    continue
                images.append({'y':int(offset.text)/12700, 'width':width, 'height':height,
                               'thumbnail':_thumbnail(archive.read(target))})
        return texts, images


def calibrate(source, companion_pdf):
    evidence = inspect_companion(companion_pdf)
    texts, source_images = _cover_evidence(source)
    tokens = lambda text:set(re.findall(r'[a-z0-9]+',text.casefold()))
    cover_tokens = tokens(' '.join(texts))
    if len(cover_tokens) < 8 or not cover_tokens <= tokens(evidence['text']):
        raise ValueError("The companion PDF cover does not match this Word report's identity and text.")
    measurements = []
    for original in source_images:
        matches=[]
        source_image=Image.frombytes('RGB',(64,64),base64.b64decode(original['thumbnail']))
        for item in evidence['images']:
            x0,y0,x1,y1=item['bbox']
            if abs((x1-x0)-original['width'])>2 or abs((y1-y0)-original['height'])>2:
                continue
            candidate=Image.frombytes('RGB',(64,64),base64.b64decode(item['thumbnail']))
            error=sum(ImageStat.Stat(ImageChops.difference(source_image,candidate)).mean)/3
            if error<=3:
                matches.append({'origin_points':round(y0-original['y'],4),'image_error':round(error,4)})
        if len(matches)==1:
            measurements.extend(matches)
    # Require independent identity, source-image pixels, frame size and origin.
    # Producer is audit information, never a rendering-behavior selector.
    zero = bool(measurements) and all(abs(m['origin_points'])<=2 for m in measurements)
    profile = {"version": VERSION, "cover_zero_origin": zero}
    return {"render_profile":profile, "producer":evidence['producer'], "cover_measurements":measurements,
            "pair_status":"measured-zero-origin" if zero else "preserve-native", "pages":evidence['pages']}


if __name__ == '__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20))
        print(json.dumps(_pdf_evidence(sys.argv[1])))
    except Exception:
        sys.exit(1)
