"""Read only closed, text-only SmartArt drawing packages; never infer image content."""
from collections import Counter
from io import BytesIO
import posixpath

from defusedxml import ElementTree as ET

A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
DGM = '{http://schemas.openxmlformats.org/drawingml/2006/diagram}'
ROOTS = {
    'diagramData': DGM + 'dataModel', 'diagramLayout': DGM + 'layoutDef',
    'diagramQuickStyle': DGM + 'styleDef', 'diagramColors': DGM + 'colorsDef',
    'diagramDrawing': '{http://schemas.microsoft.com/office/drawing/2008/diagram}drawing',
}
MAX_PART_BYTES = 2 * 1024 * 1024


def closed_smartart_text(archive, graphics, document_relations):
    """Return the complete visible drawing text, or None for any unproved graphic.

    Aggregating all diagrams lets the importer replace its existing single
    unsupported record without shifting stable downstream import item IDs.
    """
    from app.monthly_report_import import _relations
    names = set(archive.namelist())
    pending, visited, rendered, model_texts = [], {}, [], []
    if not graphics:
        return None
    for graphic in graphics:
        if graphic.get('uri') != 'http://schemas.openxmlformats.org/drawingml/2006/diagram':
            return None
        ids = list(graphic.iter(DGM + 'relIds'))
        if not ids:
            return None
        for node in ids:
            for key in ('dm', 'lo', 'qs', 'cs'):
                rid = node.get(R + key)
                if not rid or rid not in document_relations:
                    return None
                pending.append(document_relations[rid])
    try:
        while pending:
            target, relation_type = pending.pop(0)
            kind = relation_type.rsplit('/', 1)[-1]
            allowed_type = ('http://schemas.microsoft.com/office/2007/relationships/diagramDrawing'
                            if kind == 'diagramDrawing' else R[1:-1] + '/' + kind)
            if (relation_type != allowed_type or kind not in ROOTS or not target.startswith('word/diagrams/')
                    or not target.endswith('.xml') or target not in names):
                return None
            if target in visited:
                if visited[target] != kind:
                    return None
                continue
            visited[target] = kind
            if len(visited) > 20 or archive.getinfo(target).file_size > MAX_PART_BYTES:
                return None
            events = ET.iterparse(BytesIO(archive.read(target)), events=('start', 'end'), forbid_dtd=True)
            depth = count = 0
            root = None
            for event, node in events:
                if event == 'start':
                    root = node if root is None else root
                    depth += 1
                    count += 1
                    if depth > 64 or count > 20000:
                        return None
                else:
                    depth -= 1
            if root is None or root.tag != ROOTS[kind]:
                return None
            relfile = posixpath.join(posixpath.dirname(target), '_rels', posixpath.basename(target) + '.rels')
            if relfile in names and archive.getinfo(relfile).file_size > 128 * 1024:
                return None
            relations = _relations(archive, target)
            if len(relations) > 32:
                return None
            # Even unused external/active relationships make this graph unproved.
            pending.extend(relations.values())
            for node in root.iter():
                local = node.tag.rsplit('}', 1)[-1]
                if local in {'blip', 'imagedata', 'oleObj', 'oleObject', 'object', 'binData', 'altChunk',
                             'videoFile', 'audioFile', 'hlinkClick', 'hlinkHover'}:
                    return None
                if any(key.rsplit('}', 1)[-1] == 'gfxdata' for key in node.attrib):
                    return None
                for key, rid in node.attrib.items():
                    if key.startswith(R) and rid:
                        if rid not in relations:
                            return None
                        pending.append(relations[rid])
                # Word scopes this one compatibility relation to document.xml.
                if local == 'dataModelExt' and node.get('relId'):
                    relation = document_relations.get(node.get('relId'))
                    if not relation or not relation[1].endswith('/diagramDrawing'):
                        return None
                    pending.append(relation)
            if kind in {'diagramData', 'diagramDrawing'}:
                text = '\n'.join(node.text.strip() for node in root.iter(A + 't') if node.text and node.text.strip())
                if not text or len(text) > 20000:
                    return None
                (rendered if kind == 'diagramDrawing' else model_texts).append(text)
        # The editable model alone does not prove what the cached drawing shows.
        if Counter(' '.join(model_texts).split()) != Counter(' '.join(rendered).split()):
            return None
        return '\n'.join(rendered) if rendered and sum(map(len, rendered)) <= 40000 else None
    except (ValueError, KeyError, OSError, ET.ParseError):
        return None
