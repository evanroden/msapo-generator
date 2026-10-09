"""Closed, passive OOXML clone retaining native report geometry and typography.

This is not a layout reconstruction: compatibility choices/fallbacks remain wrapped
so the office renderer selects one, and image bytes are not resampled.
"""
from io import BytesIO
from pathlib import Path
import posixpath
import struct
from zipfile import ZipFile, ZIP_DEFLATED

from defusedxml import ElementTree as SafeET
from lxml import etree as XML
from PIL import Image, UnidentifiedImageError

from app.monthly_report_import import ImportError, _package, _resolve

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
SAFE_FIELDS = {'PAGE', 'NUMPAGES', 'SECTION', 'SECTIONPAGES'}
IMPLICIT = {'styles', 'numbering', 'theme', 'fontTable', 'settings', 'webSettings'}
NOTE_KINDS = {'footnotes', 'endnotes'}
XML_KINDS = IMPLICIT | NOTE_KINDS | {'header', 'footer', 'diagramData', 'diagramLayout', 'diagramQuickStyle', 'diagramColors', 'diagramDrawing'}
REMOVE = {'attachedTemplate', 'updateFields', 'mailMerge', 'dataBinding', 'printerSettings', 'docVars'}
REJECT = {'object', 'OLEObject', 'altChunk', 'control', 'movie', 'audioFile', 'videoFile', 'contentPart'}


def _static_emf(raw):
    """Validate a bounded static Windows enhanced-metafile record stream.

    EMF drawing records contain coordinates, fonts and pixel data, not package
    relationships. Reject driver escape/OpenGL records and arbitrary comments;
    the documented EMF+ comment is another bounded drawing-record stream.
    """
    if len(raw) < 88 or len(raw) > 32 * 1024 * 1024:
        return False
    kind, header_size = struct.unpack_from('<II', raw)
    if kind != 1 or header_size < 88 or raw[40:44] != b' EMF':
        return False
    size, declared = struct.unpack_from('<II', raw, 48)
    if size != len(raw) or not 2 <= declared <= 200_000:
        return False
    offset = count = 0
    while offset < len(raw):
        if offset + 8 > len(raw):
            return False
        kind, length = struct.unpack_from('<II', raw, offset)
        if length < 8 or length % 4 or offset + length > len(raw) or not 1 <= kind <= 122:
            return False
        if kind in {102, 103, 105, 106, 110}:
            return False  # OpenGL/driver escape operations are not passive pages.
        if kind == 70:
            if length < 16 or raw[offset + 12:offset + 16] != b'EMF+':
                return False
            comment_size = struct.unpack_from('<I', raw, offset + 8)[0]
            if comment_size < 4 or comment_size > length - 12:
                return False
            pos, end = offset + 16, offset + 12 + comment_size
            while pos < end:
                if pos + 12 > end:
                    return False
                record, flags, total, data_size = struct.unpack_from('<HHII', raw, pos)
                if not 0x4001 <= record <= 0x403A or total < 12 or total % 4 or data_size > total - 12 or pos + total > end:
                    return False
                pos += total
        offset += length
        count += 1
        if count > declared or (kind == 14 and offset != len(raw)):
            return False
    return kind == 14 and count == declared


def _static_wmf(raw):
    """Accept bounded static WMF drawing records and validated nested EMF only.

    Driver escapes are rejected. The sole supported escape is Microsoft's
    META_ESCAPE_ENHANCED_METAFILE framing, whose complete embedded stream must
    independently pass the same static EMF validator as a standalone image.
    """
    if not 24 <= len(raw) <= 32 * 1024 * 1024 or len(raw) % 2:
        return False
    start = 0
    if raw[:4] == b'\xd7\xcd\xc6\x9a':
        if len(raw) < 46:
            return False
        checksum = 0
        for word in struct.unpack_from('<10H', raw):
            checksum ^= word
        if checksum != struct.unpack_from('<H', raw, 20)[0]:
            return False
        start = 22
    kind, header, version, size, objects, maximum, reserved = struct.unpack_from('<HHHIHIH', raw, start)
    if kind not in {1, 2} or header != 9 or version not in {0x100, 0x300} or size * 2 != len(raw) - start or reserved:
        return False
    # Static state, window/viewport, clipping and bitmap drawing records.
    allowed = {0, 0x1e, 0x103, 0x107, 0x127, 0x12c, 0x20b, 0x20c, 0x416, 0xb41, 0x940}
    offset, count, largest = start + 18, 0, 0
    chunks, total, expected, received = [], None, None, 0
    while offset + 6 <= len(raw):
        words, function = struct.unpack_from('<IH', raw, offset)
        length = words * 2
        if words < 3 or offset + length > len(raw) or count >= 200_000:
            return False
        if function == 0x626:
            if length < 44:
                return False
            escape, byte_count = struct.unpack_from('<HH', raw, offset + 6)
            identifier, comment, emf_version = struct.unpack_from('<III', raw, offset + 10)
            flags, records, current, remaining, declared = struct.unpack_from('<IIIII', raw, offset + 24)
            if (escape != 15 or identifier != 0x43464d57 or comment != 1 or emf_version != 0x10000
                    or flags or not 1 <= records <= 4096 or not 0 < current <= 8192
                    or byte_count != 34 + current or length != 44 + current
                    or declared > 32 * 1024 * 1024):
                return False
            if total is None:
                total, expected = declared, records
            if declared != total or records != expected or received + current + remaining != total:
                return False
            chunks.append(raw[offset + 44:offset + length]); received += current
        elif function not in allowed or (chunks and received != total):
            return False
        offset += length; count += 1; largest = max(largest, words)
        if function == 0:
            if words != 3 or offset != len(raw):
                return False
            return (largest == maximum and (not chunks or
                    (len(chunks) == expected and received == total and _static_emf(b''.join(chunks)))))
    return False


def _xml(raw):
    """Bound complexity before parsing with namespace/prefix-preserving lxml."""
    depth = nodes = 0
    try:
        for event, element in SafeET.iterparse(BytesIO(raw), events=('start', 'end'), forbid_dtd=True):
            if event == 'start':
                depth += 1
                nodes += 1
                if depth > 100 or nodes > 1_000_000:
                    raise ImportError('The native report exceeds the XML complexity budget.')
            else:
                depth -= 1
                element.clear()
        return XML.fromstring(raw, XML.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except ImportError:
        raise
    except Exception as exc:
        raise ImportError('The native report contains invalid or unsafe XML.') from exc


def _local(node):
    return XML.QName(node).localname


def _passive_markup(root):
    # Fields must be evaluated as complete groups, because instruction text is
    # routinely split across runs. Non-whitelisted instructions retain only their
    # cached result, never a live command or an external-document request.
    stack = []
    groups = []
    for node in list(root.iter()):
        if not isinstance(node.tag, str):
            continue
        # Office's opaque round-trip drawing cache is itself a base64 ZIP. It
        # can retain old embedded images after the visible shape was edited,
        # and its expansion is outside the outer DOCX budgets. The explicit
        # DrawingML/VML geometry and live text are authoritative; never decode
        # or forward this redundant nested package to the office renderer.
        node.attrib.pop('{urn:schemas-microsoft-com:office:office}gfxdata', None)
        name = _local(node)
        if name in REJECT:
            raise ImportError(f'This report contains unsupported visible {name} content; its native layout cannot be preserved automatically.')
        if name in REMOVE:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
            continue
        if name == 'fldSimple':
            instruction = node.get('{' + W + '}instr', '').strip().split()
            if not instruction or instruction[0].upper() not in SAFE_FIELDS:
                node.attrib.pop('{' + W + '}instr', None)
                node.tag = '{' + W + '}sdtContent'
        if name == 'fldChar':
            kind = node.get('{' + W + '}fldCharType')
            if kind == 'begin':
                stack.append([node])
            elif stack:
                stack[-1].append(node)
                if kind == 'end':
                    groups.append(stack.pop())
        elif name == 'instrText':
            if stack:
                stack[-1].append(node)
            else:
                raise ImportError('This report contains an unbalanced Word field.')
        if name in {'imagedata', 'fill'} and any(node.get(k) for k in ('src', 'href')):
            raise ImportError('This native report contains a linked drawing without a local image.')
        for attribute in list(node.attrib):
            if XML.QName(attribute).localname.lower() in {'href', 'action', 'onload', 'onclick'}:
                del node.attrib[attribute]
    if stack:
        raise ImportError('This report contains an unbalanced Word field.')
    for group in groups:
        instruction = ''.join(n.text or '' for n in group if _local(n) == 'instrText').strip().split()
        if not instruction or instruction[0].upper() not in SAFE_FIELDS:
            for node in group:
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
    # Flatten inactive simple fields while preserving cached runs and formatting.
    for node in list(root.iter('{' + W + '}sdtContent')):
        if node.getparent() is not None and _local(node.getparent()) != 'sdt':
            parent, index = node.getparent(), node.getparent().index(node)
            for child in list(node):
                parent.insert(index, child)
                index += 1
            parent.remove(node)


def passive_docx(path: Path) -> bytes:
    """Return a bounded native DOCX with only reachable passive dependencies.

    Raises ImportError rather than silently dropping visible unsupported objects
    or missing images. Original input is never modified.
    """
    path = Path(path)
    with _package(path) as archive:
        names = set(archive.namelist())
        types = _xml(archive.read('[Content_Types].xml'))
        overrides = {e.get('PartName', '').lstrip('/'): e.get('ContentType', '') for e in types if _local(e) == 'Override'}
        defaults = {e.get('Extension', '').casefold(): e.get('ContentType', '') for e in types if _local(e) == 'Default'}
        output, visiting = {}, set()
        doc_rel_path = 'word/_rels/document.xml.rels'
        doc_relationships = _xml(archive.read(doc_rel_path)) if doc_rel_path in names else ()
        doc_relations = {rel.get('Id'): rel for rel in doc_relationships}
        borrowed_diagrams = set()
        note_ids = {kind: set() for kind in NOTE_KINDS}

        def copy(name, kind):
            if name in output or name in visiting:
                return
            if name not in names or not name.startswith('word/'):
                raise ImportError('A native report dependency is missing or outside the Word package.')
            visiting.add(name)
            raw = archive.read(name)
            if kind in {'image', 'hdphoto'}:
                try:
                    if Path(name).suffix.lower() == '.emf':
                        if not _static_emf(raw):
                            raise ValueError('unsupported metafile')
                    elif Path(name).suffix.lower() == '.wmf':
                        if not _static_wmf(raw):
                            raise ValueError('unsupported metafile')
                    else:
                        with Image.open(BytesIO(raw)) as picture:
                            if picture.format not in {'PNG', 'JPEG', 'GIF', 'TIFF', 'BMP', 'WEBP'}:
                                raise ValueError('unsupported raster')
                            picture.verify()
                except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
                    raise ImportError('This native report contains an unsupported image format; a PNG/JPEG replacement is needed to preserve that drawing.') from exc
                output[name] = raw
            elif kind == 'font':
                # Embedded local font binaries are passive. Their package format
                # and font-key remain unchanged for Word's obfuscation handling.
                output[name] = raw
            else:
                root = _xml(raw)
                original_xml = XML.tostring(root)
                _passive_markup(root)
                if name == 'word/document.xml':
                    for note_kind in NOTE_KINDS:
                        note_ids[note_kind] = {node.get('{' + W + '}id') for node in root.iter('{' + W + '}' + note_kind[:-1] + 'Reference')}
                if kind in NOTE_KINDS:
                    available = {note.get('{' + W + '}id') for note in root}
                    if note_ids[kind] - available:
                        raise ImportError('A native report references a missing note.')
                    for note in list(root):
                        if note.get('{' + W + '}id') not in note_ids[kind] and note.get('{' + W + '}type') not in {'separator', 'continuationSeparator', 'continuationNotice'}:
                            root.remove(note)
                relname = posixpath.join(posixpath.dirname(name), '_rels', posixpath.basename(name) + '.rels')
                relationships = _xml(archive.read(relname)) if relname in names else XML.Element('{' + REL + '}Relationships', nsmap={None: REL})
                # Only HD Photo edit-history layers can use a standard rendered
                # fallback. Ordinary PNG/JPEG imgLayers are visible components
                # (the standard blip can be a plain placeholder), so retain them.
                by_id = {rel.get('Id'): rel for rel in relationships}
                if name == 'word/document.xml':
                    kinds = {rel.get('Type', '').rsplit('/', 1)[-1] for rel in relationships}
                    if any(note_ids[kind] and kind not in kinds for kind in NOTE_KINDS):
                        raise ImportError('A native report references a missing note part.')
                for node in list(root.iter('{http://schemas.microsoft.com/office/drawing/2010/main}imgProps')):
                    layers = list(node.iter('{http://schemas.microsoft.com/office/drawing/2010/main}imgLayer'))
                    layer_rels = [by_id.get(layer.get('{' + R + '}embed')) for layer in layers]
                    if not layer_rels or not all(rel is not None and rel.get('Type', '').endswith('/hdphoto') for rel in layer_rels):
                        continue
                    # Some Word authors label ordinary JPEG/PNG layers as HD
                    # Photo relationships. These are visible, supported raster
                    # components, not opaque WDP edit history; retain the effects.
                    supported_layers = True
                    for relation in layer_rels:
                        if relation.get('TargetMode', '').casefold() == 'external':
                            supported_layers = False
                            break
                        layer_target = _resolve(name, relation.get('Target', ''))
                        try:
                            with Image.open(BytesIO(archive.read(layer_target))) as layer_image:
                                if layer_image.format not in {'PNG', 'JPEG'}:
                                    supported_layers = False
                                layer_image.verify()
                        except (KeyError, UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                            supported_layers = False
                    if supported_layers:
                        continue
                    blip = next((p for p in node.iterancestors() if p.tag == '{http://schemas.openxmlformats.org/drawingml/2006/main}blip'), None)
                    fallback = by_id.get(blip.get('{' + R + '}embed')) if blip is not None else None
                    if fallback is None or fallback.get('TargetMode', '').casefold() == 'external' or not fallback.get('Type', '').endswith('/image'):
                        raise ImportError('A native HD Photo editing layer has no local rendered fallback.')
                    target = _resolve(name, fallback.get('Target', ''))
                    if target not in names:
                        raise ImportError('A native HD Photo editing layer has no local rendered fallback.')
                    try:
                        with Image.open(BytesIO(archive.read(target))) as image:
                            if image.format not in {'PNG', 'JPEG'} or min(image.size) < 256:
                                raise ImportError('A native HD Photo editing layer has no usable rendered fallback.')
                            image.verify()
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                        raise ImportError('A native HD Photo editing layer has no usable rendered fallback.') from exc
                    node.getparent().remove(node)
                seen = set()
                used = {v for n in root.iter() for k, v in n.attrib.items() if v and (k.startswith('{' + R + '}') or k == 'relId')}
                kept = XML.Element('{' + REL + '}Relationships', nsmap={None: REL})
                for rel in relationships:
                    rid, reltype = rel.get('Id', ''), rel.get('Type', '')
                    if not rid or rid in seen:
                        raise ImportError('Duplicate or missing relationship identity in native DOCX.')
                    seen.add(rid)
                    short = reltype.rsplit('/', 1)[-1]
                    relevant = rid in used or short in IMPLICIT or (short in NOTE_KINDS and bool(note_ids[short]))
                    if not relevant:
                        continue
                    target = '' if rel.get('TargetMode', '').casefold() == 'external' else _resolve(name, rel.get('Target', ''))
                    if short == 'hyperlink':
                        for node in root.iter():
                            for attr, value in list(node.attrib.items()):
                                if attr.startswith('{' + R + '}') and value == rid:
                                    del node.attrib[attr]
                        continue
                    if not target or short not in XML_KINDS | {'image', 'hdphoto', 'font'}:
                        raise ImportError(f'This report uses an unsupported or external {short} dependency; its visible layout cannot be preserved.')
                    copy(target, short)
                    kept.append(rel)
                missing = used - seen
                # SmartArt dataModelExt's unqualified relId is scoped to the
                # containing document, not its diagramData XML part.
                extension_ids = {n.get('relId') for n in root.iter() if n.get('relId')}
                for rid in missing & extension_ids:
                    rel = doc_relations.get(rid)
                    if rel is not None and rel.get('Type', '').endswith('/diagramDrawing') and rel.get('TargetMode', '').casefold() != 'external':
                        target = _resolve('word/document.xml', rel.get('Target', ''))
                        copy(target, 'diagramDrawing')
                        borrowed_diagrams.add(rid)
                        missing.remove(rid)
                if missing:
                    raise ImportError(f'A native drawing references a missing relationship in {name}: {", ".join(sorted(missing))}.')
                if name == 'word/document.xml':
                    retained = {rel.get('Id') for rel in kept}
                    for rid in sorted(borrowed_diagrams - retained):
                        kept.append(doc_relations[rid])
                output[name] = raw if XML.tostring(root) == original_xml else XML.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
                if len(kept):
                    output[relname] = XML.tostring(kept, encoding='UTF-8', xml_declaration=True)
            visiting.remove(name)

        copy('word/document.xml', 'officeDocument')
        # LibreOffice selects Word drawing compatibility using the originating
        # application/version properties. Omitting these can silently hide native
        # grouped shapes and text boxes even when document.xml is unchanged.
        app_properties = 'docProps/app.xml'
        if app_properties in names:
            app_raw = archive.read(app_properties)
            app_root = _xml(app_raw)
            app_xml = XML.tostring(app_root)
            # Extended properties may contain a full heading/title index, names,
            # company details and even contact addresses from removed content.
            # Only the originating application identity is compatibility data.
            for child in list(app_root):
                if _local(child) not in {'Application', 'AppVersion'}:
                    app_root.remove(child)
                else:
                    child.attrib.clear()
                    for nested in list(child):
                        child.remove(nested)
                    child.tail = None
            app_root.attrib.clear()
            app_root.text = None
            _passive_markup(app_root)
            output[app_properties] = app_raw if XML.tostring(app_root) == app_xml else XML.tostring(app_root, encoding='UTF-8', xml_declaration=True, standalone=True)
        content = XML.Element('{' + CT + '}Types', nsmap={None: CT})
        XML.SubElement(content, '{' + CT + '}Default', Extension='rels', ContentType='application/vnd.openxmlformats-package.relationships+xml')
        for extension, content_type in sorted(defaults.items()):
            if extension != 'rels' and any(name.casefold().endswith('.' + extension) for name in output):
                XML.SubElement(content, '{' + CT + '}Default', Extension=extension, ContentType=content_type)
        for name in sorted(output):
            if name.endswith('.rels'):
                continue
            content_type = overrides.get(name) or defaults.get(name.rsplit('.', 1)[-1].casefold())
            if not content_type or 'macroEnabled' in content_type:
                raise ImportError('The native report has an unsupported content type.')
            XML.SubElement(content, '{' + CT + '}Override', PartName='/' + name, ContentType=content_type)
        output['[Content_Types].xml'] = XML.tostring(content, encoding='UTF-8', xml_declaration=True)
        rootrels = XML.Element('{' + REL + '}Relationships', nsmap={None: REL})
        XML.SubElement(rootrels, '{' + REL + '}Relationship', Id='rId1', Type=R + '/officeDocument', Target='word/document.xml')
        if app_properties in output:
            XML.SubElement(rootrels, '{' + REL + '}Relationship', Id='rIdApp', Type=R + '/extended-properties', Target=app_properties)
        output['_rels/.rels'] = XML.tostring(rootrels, encoding='UTF-8', xml_declaration=True)
        buffer = BytesIO()
        with ZipFile(buffer, 'w', ZIP_DEFLATED) as result:
            # Keep the source member order/metadata for retained parts. Changed
            # XML and rebuilt relationships are the only rewritten payloads.
            retained_names = tuple(output)
            for name in archive.namelist():
                if name.endswith('/') and any(part.startswith(name) for part in retained_names):
                    result.writestr(archive.getinfo(name), b'')
                if name in output:
                    result.writestr(archive.getinfo(name), output.pop(name))
            for name, data in sorted(output.items()):
                result.writestr(name, data)
        return buffer.getvalue()
