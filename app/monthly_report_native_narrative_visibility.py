"""Keep rewritten author prose visible without changing proved native typography."""
from copy import deepcopy
import re
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_native_notes import plain_visible, _PPR


def _visibility_probe(paragraph, styles):
    """Ignore only structurally proved benign layout in the visibility probe.

    Nothing is removed from the actual paragraph or styles. Numbering/tabs/borders
    affect presentation, not hidden-style inheritance; unknown grammar is refused.
    """
    if not _hidden_inheritance_clear(paragraph, styles):
        return None
    paragraph, styles = deepcopy(paragraph), deepcopy(styles)
    for root in (paragraph, styles):
        for props in root.iter(qn('w:rPr')):
            # Complex-script weight/slant do not establish text visibility.
            # Some source writers append these benign toggles after size or
            # underline. Ignore only unique, well-formed toggles in this copy;
            # preserve the actual typography and the stricter deletion proof.
            for name in ('bCs', 'iCs'):
                nodes = props.findall(qn('w:' + name))
                if (len(nodes) == 1 and not len(nodes[0]) and not (nodes[0].text or '').strip()
                        and set(nodes[0].attrib) <= {qn('w:val')}
                        and nodes[0].get(qn('w:val'), '1') in
                        ('1', 'true', 'on', '0', 'false', 'off')):
                    props.remove(nodes[0])
        for node in list(root.iter()):
            if (node.tag in {qn('w:' + name) for name in ('vanish', 'webHidden', 'specVanish')}
                    and node.getparent() is not None and node.getparent().tag == qn('w:rPr')):
                node.getparent().remove(node)
            elif node.tag == qn('w:color') and set(node.attrib) == {qn('w:val')}:
                value = node.get(qn('w:val'), '')
                # Preserve ordinary dark explicit text colors. Light/theme
                # colors remain unproved, rather than flattening all color.
                if _dark_rgb(value):
                    node.set(qn('w:val'), '000000')
    for root in (paragraph, styles):
        for props in root.iter(qn('w:pPr')):
            tags = [child.tag for child in props]
            if (len(tags) != len(set(tags)) or any(tag not in _PPR for tag in tags)
                    or [_PPR.index(tag) for tag in tags] != sorted(_PPR.index(tag) for tag in tags)):
                continue  # Leave malformed selected properties for strict refusal.
            for node in list(props):
                if node.tag == qn('w:numPr'):
                    children = list(node)
                    tags = [child.tag for child in children]
                    allowed = [qn('w:ilvl'), qn('w:numId')]
                    if (len(tags) != len(set(tags)) or any(t not in allowed for t in tags)
                            or [allowed.index(t) for t in tags] != sorted(allowed.index(t) for t in tags)
                            or any(len(c) or not c.get(qn('w:val'), '').isdigit() for c in children)):
                        continue
                    props.remove(node)
                elif node.tag == qn('w:tabs'):
                    if any(child.tag != qn('w:tab') or len(child) for child in node):
                        continue
                    node[:] = []
                elif node.tag == qn('w:pBdr'):
                    if any(child.tag not in {qn('w:' + x) for x in ('top', 'left', 'bottom', 'right', 'between', 'bar')}
                           or len(child) for child in node):
                        continue
                    node[:] = []
    return paragraph, styles


def _dark_rgb(value):
    if not re.fullmatch('[0-9a-fA-F]{6}', value):
        return False
    rgb = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return (1.05 / (luminance + 0.05)) >= 4.5


def _hidden_inheritance_clear(paragraph, styles):
    """Resolve explicit visibility overrides without relaxing note deletion.

    Style-on toggles are treated conservatively: a later style-off is not
    assumed to undo an earlier style-on. A direct run-off can override inherited
    hidden formatting. A style-off may override document defaults when no
    selected style turns the property on.
    """
    by_id = {style.get(qn('w:styleId')): style for style in styles.findall(qn('w:style'))}
    defaults = styles.find(qn('w:docDefaults'))
    default_run = defaults.find('./' + qn('w:rPrDefault') + '/' + qn('w:rPr')) if defaults is not None else None
    default_mark = defaults.find('./' + qn('w:pPrDefault') + '/' + qn('w:pPr') + '/' + qn('w:rPr')) if defaults is not None else None
    implicit = {kind: next((s.get(qn('w:styleId')) for s in by_id.values()
                if s.get(qn('w:type')) == kind and s.get(qn('w:default')) in ('1', 'true', 'on')), None)
                for kind in ('paragraph', 'character')}

    def chain(identity):
        result, seen = [], set()
        while identity is not None:
            if identity in seen or identity not in by_id:
                return None
            seen.add(identity); style = by_id[identity]; result.append(style)
            bases = style.findall(qn('w:basedOn'))
            if len(bases) > 1:
                return None
            identity = bases[0].get(qn('w:val')) if bases else None
        return result

    def values(properties, name):
        if properties is None:
            return []
        nodes = properties.findall(qn('w:' + name))
        if len(nodes) > 1:
            raise ValueError('duplicate visibility property')
        result = []
        for node in nodes:
            value = node.get(qn('w:val'), '1')
            if len(node) or any(k != qn('w:val') for k in node.attrib):
                raise ValueError('malformed visibility property')
            if value not in ('1', 'true', 'on', '0', 'false', 'off'):
                raise ValueError('unknown visibility property')
            result.append(value in ('1', 'true', 'on'))
        return result

    ppr = paragraph.find(qn('w:pPr'))
    selected = ppr.find(qn('w:pStyle')) if ppr is not None else None
    paragraph_chain = chain(selected.get(qn('w:val')) if selected is not None else implicit['paragraph'])
    default_character = chain(implicit['character'])
    if paragraph_chain is None or default_character is None:
        return False
    try:
        # With no text node the writer creates a new run; an unrelated empty
        # run's explicit visibility cannot protect that future run.
        runs = paragraph.findall(qn('w:r'))
        if not any(True for _ in paragraph.iter(qn('w:t'))):
            runs.append(OxmlElement('w:r'))
        if default_run is not None and default_run.find(qn('w:rStyle')) is not None:
            return False
        for run in runs:
            rpr = run.find(qn('w:rPr'))
            selected = rpr.find(qn('w:rStyle')) if rpr is not None else None
            character_chain = chain(selected.get(qn('w:val'))) if selected is not None else []
            if character_chain is None:
                return False
            for flag in ('vanish', 'webHidden', 'specVanish'):
                inherited = values(default_run, flag)
                if any(values(default_mark, flag)):
                    inherited.append(True)
                style_values = []
                for style in paragraph_chain + default_character + character_chain:
                    if style.get(qn('w:type')) == 'character' and style.find(qn('w:pPr')) is not None:
                        return False
                    style_values.extend(values(style.find(qn('w:rPr')), flag))
                    mark = style.find('./' + qn('w:pPr') + '/' + qn('w:rPr'))
                    if mark is not None and mark.find(qn('w:rStyle')) is not None:
                        return False
                    # Mark formatting cannot establish that body text is
                    # visible. Treat on as unproved; never use mark-off to
                    # cancel hidden body defaults.
                    if any(values(mark, flag)):
                        style_values.append(True)
                # Any selected style-on is unproved unless the actual run has
                # an explicit off. Style-off alone can clear document defaults.
                hidden = any(style_values) if style_values else any(inherited)
                mark = ppr.find(qn('w:rPr')) if ppr is not None else None
                if any(properties is not None and properties.find(qn('w:rStyle')) is not None
                       for properties in (mark, default_mark)):
                    return False
                if any(values(mark, flag)):
                    hidden = True
                direct = values(rpr, flag)
                if direct:
                    hidden = direct[0]
                if hidden:
                    return False
    except ValueError:
        return False
    return True


def _visible_run_properties():
    props = OxmlElement('w:rPr')
    fonts = OxmlElement('w:rFonts')
    for name in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        fonts.set(qn('w:' + name), 'Calibri')
    props.append(fonts)
    for name, value in (('vanish', '0'), ('webHidden', '0'), ('color', '000000'),
                        ('sz', '22'), ('szCs', '22'), ('highlight', 'none')):
        node = OxmlElement('w:' + name); node.set(qn('w:val'), value); props.append(node)
    # A fresh paragraph style still inherits run/document defaults. Neutral
    # black ink needs an explicit light background, not an inherited black
    # highlight or shading pattern. Keep these overrides fallback-only.
    props.append(_visible_background())
    hidden = OxmlElement('w:specVanish'); hidden.set(qn('w:val'), '0'); props.append(hidden)
    return props


def _visible_background():
    shade = OxmlElement('w:shd')
    for name, value in (('val', 'clear'), ('color', 'auto'), ('fill', 'FFFFFF')):
        shade.set(qn('w:' + name), value)
    return shade


def _visible_narrative_prototype(prototype, styles, *, reserved_ids):
    """Return original proved formatting, otherwise isolated visible body text.

    Called after final anchor selection and only for rewritten narrative. It
    never edits source paragraphs, replayed content, table cells or artwork.
    """
    probe = _visibility_probe(prototype, styles)
    if probe is not None and plain_visible(*probe):
        return prototype
    # No dependence on a potentially hidden/malformed Normal or default style.
    # The fresh paragraph style has no basedOn; explicit run overrides also
    # defeat hidden character/document defaults, including source color/size.
    ids = {style.get(qn('w:styleId')) for style in styles.findall(qn('w:style'))}
    ids.update(reserved_ids())
    stem = 'ENFRACurrentVisibleNarrative'
    identity, suffix = stem, 0
    while identity in ids:
        suffix += 1; identity = stem + str(suffix)
    style = OxmlElement('w:style'); style.set(qn('w:type'), 'paragraph'); style.set(qn('w:styleId'), identity)
    name = OxmlElement('w:name'); name.set(qn('w:val'), identity); style.append(name)
    style.append(_visible_run_properties()); styles.append(style)
    result = OxmlElement('w:p')
    props = OxmlElement('w:pPr'); result.append(props)
    selected = OxmlElement('w:pStyle'); selected.set(qn('w:val'), identity); props.append(selected)
    numbering = OxmlElement('w:numPr'); props.append(numbering)
    number = OxmlElement('w:numId'); number.set(qn('w:val'), '0'); numbering.append(number)
    props.append(_visible_background())
    spacing = OxmlElement('w:spacing')
    for key, value in (('before', '0'), ('after', '0'), ('line', '240'), ('lineRule', 'auto')):
        spacing.set(qn('w:' + key), value)
    props.append(spacing)
    indent = OxmlElement('w:ind')
    for key in ('left', 'right', 'firstLine'):
        indent.set(qn('w:' + key), '0')
    props.append(indent)
    props.append(_visible_run_properties())
    run = OxmlElement('w:r'); result.append(run)
    run.append(_visible_run_properties()); run.append(OxmlElement('w:t'))
    return result


def narrative_visibility_writer(document):
    """Bind one build's style namespace, including undefined source references."""
    reserved = None

    def identifiers():
        nonlocal reserved
        if reserved is None:
            from lxml import etree
            reserved = set()
            selectors = {qn('w:' + name) for name in
                         ('pStyle', 'rStyle', 'tblStyle', 'basedOn', 'next', 'link')}
            for part in document.part.package.parts:
                content_type = part.content_type.casefold()
                if not (content_type.endswith('+xml') or content_type in ('application/xml', 'text/xml')
                        or str(part.partname).casefold().endswith('.xml')):
                    continue
                root = etree.fromstring(part.blob, parser=etree.XMLParser(
                    resolve_entities=False, no_network=True))
                for node in root.iter():
                    if node.tag in selectors and node.get(qn('w:val')):
                        reserved.add(node.get(qn('w:val')))
                    if node.tag == qn('w:style') and node.get(qn('w:styleId')):
                        reserved.add(node.get(qn('w:styleId')))
        return reserved

    def choose(prototype):
        return _visible_narrative_prototype(prototype, document.styles.element,
                                           reserved_ids=identifiers)
    return choose
