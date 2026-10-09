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

VERSION = 4
LEGACY_DEFAULT = {"version": 1, "cover_zero_origin": False}
VERSION_TWO_DEFAULT = {"version": 2, "cover_zero_origin": False, "divider_wrap_none": False}
VERSION_THREE_DEFAULT = {"version": 3, "cover_zero_origin": False, "divider_wrap_none": False, "divider_white_text": False}
DEFAULT = {**VERSION_THREE_DEFAULT, "version": VERSION, "cover_metrics": []}
MAX_PDF_BYTES = 30 * 1024 * 1024
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def validate_profile(value=None):
    value = dict(DEFAULT) if value is None else value
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        raise ValueError("Unsupported saved PDF rendering profile.")
    schema = {1: LEGACY_DEFAULT, 2: VERSION_TWO_DEFAULT, 3: VERSION_THREE_DEFAULT, VERSION: DEFAULT}.get(value["version"])
    if schema is None or set(value) != set(schema) or any(type(value[key]) is not bool for key in schema if key not in {"version", "cover_metrics"}):
        raise ValueError("Unsupported saved PDF rendering profile.")
    # Version-one profiles remain byte-for-byte equivalent in identity payloads.
    # Do not add the new false flag to an already pinned paired design.
    result = dict(value)
    if "cover_metrics" in result:
        from app.monthly_report_cover_metrics import validate_records
        result["cover_metrics"] = validate_records(result["cover_metrics"])
    return result


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


def _pdf_divider_images(pdf, filters):
    """Decode only small candidate rasters after metadata and geometry checks."""
    if not filters:
        return []
    decoded, result = {}, []
    pixels = 0
    for page_number in range(len(pdf)):
        page = pdf[page_number]
        objects = page.get_images(full=True)
        # Nested form image lookup can invoke pixel hashing for the entire page.
        # Restrict this proof to directly referenced images and bounded metadata.
        if len(objects) > 64:
            return []
        candidates = [item for item in objects if item[-1] == 0 and item[0] > 0
                      and 0 < item[2] * item[3] <= 20_000_000
                      and any(abs(item[2] / item[3] - query["aspect"]) <= .01 for query in filters)]
        if not candidates:
            continue
        # hashes=False does not materialize image pixels. Its metadata lets us
        # reject repeated/ambiguous placements before extracting one candidate.
        metadata = page.get_image_info(hashes=False, xrefs=False)
        if len(metadata) > 256:
            return []
        for item in candidates:
            placements = [info for info in metadata if info["width"] == item[2] and info["height"] == item[3]]
            if len(placements) != 1:
                continue
            bbox = tuple(page.get_image_bbox(item))
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1] or any(abs(a - b) > .01 for a, b in zip(bbox, placements[0]["bbox"])):
                continue
            if not any(abs(bbox[2] - bbox[0] - query["width"]) <= 2
                       and abs(bbox[3] - bbox[1] - query["height"]) <= 2
                       and abs(bbox[1] - query["y"]) <= 2 for query in filters):
                continue
            xref = item[0]
            if xref not in decoded:
                pixels += item[2] * item[3]
                if pixels > 20_000_000 or len(decoded) >= 32:
                    return []
                raw = pdf.extract_image(xref)["image"]
                if len(raw) > MAX_PDF_BYTES:
                    return []
                decoded[xref] = _thumbnail(raw)
            result.append({"page": page_number + 1, "bbox": bbox, "thumbnail": decoded[xref]})
            if len(result) > 32:
                return []
    return result


def _divider_evidence(source):
    """Measure only recognized full-page wrapped divider photo frames."""
    from app.monthly_report_import import _is_native_divider_background, _text
    result, pixels = [], 0
    with ZipFile(source) as archive:
        root = etree.fromstring(archive.read("word/document.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
        relations = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {node.get("Id"): posixpath.normpath(posixpath.join("word", node.get("Target", "")))
                   for node in relations if node.get("TargetMode") != "External"}
        for paragraph in root.findall(".//w:p", NS):
            if not _is_native_divider_background(paragraph, _text(paragraph)):
                continue
            for anchor in paragraph.findall(".//wp:anchor", NS):
                y = anchor.find("wp:positionV", NS)
                extent = anchor.find("wp:extent", NS)
                wrap = anchor.find("wp:wrapTopAndBottom", NS)
                blips = anchor.findall(".//a:blip", NS)
                if y is None or y.get("relativeFrom") != "page" or extent is None or wrap is None or not blips:
                    continue
                try:
                    width, height = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
                    if width <= 6_000_000 or height <= 6_000_000:
                        continue
                    # An unmeasurable candidate must not let other positive
                    # matches enable the global divider flag for this design.
                    if len(blips) != 1 or len(result) >= 8:
                        return []
                    transforms = anchor.findall(".//a:xfrm", NS)
                    if any(any(transform.get(k, "0") not in {"0", "false"} for k in ("rot", "flipH", "flipV")) for transform in transforms):
                        return []
                    offset = y.find("wp:posOffset", NS)
                    if offset is None:
                        return []
                    target = targets.get(blips[0].get("{" + NS["r"] + "}embed"))
                    if not target or target not in archive.namelist() or archive.getinfo(target).file_size > MAX_PDF_BYTES:
                        return []
                    crops = anchor.findall(".//a:srcRect", NS)
                    if len(crops) > 1:
                        return []
                    crop = {side: int(crops[0].get(side, "0")) if crops else 0 for side in ("l", "t", "r", "b")}
                    if any(value < 0 or value >= 100000 for value in crop.values()) or crop["l"] + crop["r"] >= 100000 or crop["t"] + crop["b"] >= 100000:
                        return []
                    with Image.open(BytesIO(archive.read(target))) as image:
                        pixels += image.width * image.height
                        if pixels > 20_000_000:
                            return []
                        bounds = (round(image.width * crop["l"] / 100000), round(image.height * crop["t"] / 100000),
                                  round(image.width * (1 - crop["r"] / 100000)), round(image.height * (1 - crop["b"] / 100000)))
                        cropped = image.crop(bounds).convert("RGB")
                        if not cropped.width or not cropped.height:
                            return []
                        result.append({"width": width / 12700, "height": height / 12700, "y": int(offset.text) / 12700,
                                       "aspect": cropped.width / cropped.height,
                                       "thumbnail": base64.b64encode(cropped.resize((64, 64)).tobytes()).decode()})
                except (ValueError, OSError, KeyError, TypeError, Image.DecompressionBombError):
                    return []
    return result


def _match_dividers(source, observed):
    matches, used = [], set()
    for original in source:
        expected = Image.frombytes("RGB", (64, 64), base64.b64decode(original["thumbnail"]))
        candidates = []
        for index, item in enumerate(observed):
            x0, y0, x1, y1 = item["bbox"]
            if max(abs(x1 - x0 - original["width"]), abs(y1 - y0 - original["height"]), abs(y0 - original["y"])) > 2:
                continue
            actual = Image.frombytes("RGB", (64, 64), base64.b64decode(item["thumbnail"]))
            error = sum(ImageStat.Stat(ImageChops.difference(expected, actual)).mean) / 3
            if error <= 3:
                candidates.append((index, {"page": item["page"], "image_error": round(error, 4),
                                          "frame_error_points": [round(x1 - x0 - original["width"], 4),
                                                                 round(y1 - y0 - original["height"], 4), round(y0 - original["y"], 4)]}))
        if len(candidates) != 1 or candidates[0][0] in used:
            return []
        used.add(candidates[0][0]); matches.append(candidates[0][1])
    return matches


def _title_key(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _divider_title_evidence(source):
    """Find every text use affected by the narrow opaque-white style bridge."""
    from app.monthly_report_import import _heading
    from app.monthly_report_render_compat import _divider_text_fill
    word = "{" + NS["w"] + "}"
    with ZipFile(source) as archive:
        if "word/styles.xml" not in archive.namelist():
            return []
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        styles = etree.fromstring(archive.read("word/styles.xml"), parser)
        before = {style.get(word + "styleId"): etree.tostring(style) for style in styles.findall(word + "style")}
        _divider_text_fill(styles)
        eligible = {style.get(word + "styleId") for style in styles.findall(word + "style")
                    if before[style.get(word + "styleId")] != etree.tostring(style)}
        if not eligible:
            return []
        # Derived styles inherit the bridge too. Their use must satisfy the
        # same title proof, rather than silently recoloring unrelated prose.
        while True:
            derived = {style.get(word + "styleId") for style in styles.findall(word + "style")
                       if style.find(word + "basedOn") is not None
                       and style.find(word + "basedOn").get(word + "val") in eligible}
            if derived <= eligible:
                break
            eligible.update(derived)
        def affected_text(paragraph):
            style = paragraph.find("w:pPr/w:pStyle", NS)
            paragraph_style = style.get(word + "val") if style is not None else ""
            runs = [run for run in paragraph.iter(word + "r")
                    if next(run.iterancestors(word + "p"), None) is paragraph]
            text = "".join(node.text or "" for run in runs for node in run.findall("w:t", NS))
            affected = paragraph_style in eligible or any(
                run.find("w:rPr/w:rStyle", NS) is not None
                and run.find("w:rPr/w:rStyle", NS).get(word + "val") in eligible for run in runs)
            return text if affected else ""

        # styles.xml is global. A body-title match cannot authorize recoloring
        # header/footer, note, or other story text (including inherited styles).
        # Scan XML metadata only, with an aggregate bound before decompression.
        stories = [item for item in archive.infolist() if item.filename.startswith("word/")
                   and item.filename.endswith(".xml")
                   and item.filename not in {"word/document.xml", "word/styles.xml"}]
        if len(stories) > 512 or sum(item.file_size for item in stories) > MAX_PDF_BYTES:
            return []
        for item in stories:
            story = etree.fromstring(archive.read(item), parser)
            if any(affected_text(paragraph).strip() for paragraph in story.findall(".//w:p", NS)):
                return []
        root = etree.fromstring(archive.read("word/document.xml"), parser)
        groups = {}
        for paragraph in root.findall(".//w:p", NS):
            text = affected_text(paragraph)
            if not text.strip():
                continue
            container = next(paragraph.iterancestors(word + "txbxContent"), None)
            if container is None:
                return []  # A global style bridge must not alter ordinary prose.
            groups.setdefault(container, []).append(text)
        titles, occurrences = [], {}
        alternate_tag = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
        for container, paragraphs in groups.items():
            text = " ".join(paragraphs)
            if not _heading(text) or len(text) > 400:
                return []
            title = _title_key(text)
            alternate = next(container.iterancestors(alternate_tag), None)
            branch = container
            if alternate is not None:
                while branch.getparent() is not alternate:
                    branch = branch.getparent()
            owner = alternate if alternate is not None else container
            previous = occurrences.setdefault(owner, {})
            # Choice/Fallback are alternative renderings of one title. Two
            # live textboxes in a branch, differing alternative titles, or the
            # same heading at another location need separate PDF proof.
            if branch in previous or (previous and title not in previous.values()):
                return []
            if not previous:
                if title in titles:
                    return []
                titles.append(title)
            previous[branch] = title
        return titles if len(titles) <= 32 else []


def _pdf_title_colors(pdf, titles):
    if not titles:
        return []
    results, characters = [], 0
    for page_number in range(len(pdf)):
        page = pdf[page_number]
        spans = page.get_texttrace()  # Text operators only; no image decoding.
        if len(spans) > 10000:
            return []
        selected = []
        for span in spans:
            chars = span["chars"]
            characters += len(chars)
            if characters > 2_000_000:
                return []
            bbox = span["bbox"]
            if span["size"] < 20 or bbox[1] < page.rect.height * .45 or bbox[1] >= page.rect.height:
                continue
            text = "".join(chr(char[0]) for char in chars)
            if re.search(r"[a-z]", text, re.IGNORECASE):
                selected.append((text, span))
        title = _title_key("".join(text for text, _ in selected))
        if title not in titles:
            continue
        white = all(span["type"] == 0 and span["opacity"] >= .999
                    and len(span["color"]) in (1, 3) and all(channel >= .999 for channel in span["color"])
                    for _, span in selected)
        # Prove a covering opaque rectangle before rejecting visibility.
        # Bounding boxes of later transparent shadow bitmaps do not establish
        # coverage and would reject the authentic ENFRA divider typography.
        painting = page.get_drawings()
        if len(painting) > 20000:
            return []
        for _, span in selected:
            x0, y0, x1, y1 = span["bbox"]
            area = max(0, x1 - x0) * max(0, y1 - y0)
            for drawing in painting:
                if (drawing.get("seqno", -1) <= span["seqno"] or drawing.get("fill") is None
                        or drawing.get("fill_opacity", 0) < .999 or len(drawing.get("items", ())) != 1):
                    continue
                item = drawing["items"][0]
                if item[0] != "re":
                    continue
                bbox = item[1]
                overlap = max(0, min(x1, bbox[2]) - max(x0, bbox[0])) * max(0, min(y1, bbox[3]) - max(y0, bbox[1]))
                if area <= 0 or overlap > area * .1:
                    white = False
        results.append({"title": title, "page": page_number + 1, "opaque_visible_white": white})
        if len(results) > 64:
            return []
    return results


def _match_title_colors(titles, observed):
    matches = []
    for title in titles:
        candidates = [item for item in observed if item["title"] == title]
        if len(candidates) != 1 or not candidates[0]["opaque_visible_white"]:
            return []
        matches.append(candidates[0])
    return matches


def _pdf_evidence(path, dividers=(), divider_titles=(), cover_queries=()):
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
        divider_images = _pdf_divider_images(pdf, dividers)
        title_colors = _pdf_title_colors(pdf, divider_titles)
        from app.monthly_report_cover_metrics import pdf_cover_lines
        cover_lines = pdf_cover_lines(page, list(cover_queries))
        return {"cover_lines": cover_lines, "text": text, "images": images, "divider_images": divider_images, "divider_title_colors": title_colors, "producer": str((pdf.metadata or {}).get("producer", ""))[:500],
                "pages": len(pdf)}


def inspect_companion(path, dividers=(), divider_titles=(), *, cover_queries=()):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("The companion PDF must be nonempty and at most 30 MB.")
    try:
        result = subprocess.run([sys.executable, "-m", __name__, str(path.resolve())],
                                input=json.dumps({"dividers": dividers, "divider_titles": divider_titles, "cover_queries": list(cover_queries)}).encode(),
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
    dividers = _divider_evidence(source)
    filters = [{key: item[key] for key in ("width", "height", "y", "aspect")} for item in dividers]
    source_titles = _divider_title_evidence(source)
    evidence = inspect_companion(companion_pdf, filters, source_titles)
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
    divider_measurements = _match_dividers(dividers, evidence.get("divider_images", ()))
    divider_none = bool(dividers) and len(divider_measurements) == len(dividers)
    title_measurements = _match_title_colors(source_titles, evidence.get("divider_title_colors", ()))
    white_titles = bool(source_titles) and len(title_measurements) == len(source_titles)
    profile = {"version": VERSION, "cover_zero_origin": zero, "divider_wrap_none": divider_none,
               "divider_white_text": white_titles, "cover_metrics": []}
    from app.monthly_report_cover_metrics import calibrate_cover_metrics
    metrics, metrics_audit = calibrate_cover_metrics(source, companion_pdf, profile)
    profile["cover_metrics"] = metrics
    return {"render_profile":profile, "cover_typography":metrics_audit, "divider_measurements":divider_measurements,
            "divider_title_measurements":title_measurements, "producer":evidence['producer'], "cover_measurements":measurements,
            "pair_status":"measured-cover-typography" if metrics else "measured-zero-origin" if zero else "measured-divider-wrap" if divider_none else "preserve-native", "pages":evidence['pages']}


if __name__ == '__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20))
        request = sys.stdin.buffer.read(65537)
        if len(request) > 65536:
            raise ValueError("Calibration request exceeds its bound.")
        request = json.loads(request or b'{}')
        filters = request.get("dividers", [])
        titles = request.get("divider_titles", [])
        if not isinstance(titles, list) or len(titles) > 32 or any(not isinstance(t, str) or len(t) > 400 for t in titles):
            raise ValueError("Invalid divider title candidates.")
        if not isinstance(filters, list) or len(filters) > 8:
            raise ValueError("Too many divider candidates.")
        print(json.dumps(_pdf_evidence(sys.argv[1], filters, titles, request.get("cover_queries", []))))
    except Exception:
        sys.exit(1)
