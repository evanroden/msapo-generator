"""Independent synthetic static siblings; no authentic source XML/artwork."""
from copy import deepcopy
import base64
import hashlib

from lxml import etree as E
import pytest

from app import monthly_report_static_siblings as static
from app.monthly_report_compatibility_view import CompatibilityError

W, A, WP, WPS = static.W, static.A, static.WP, static.WPS
V, O, W14, WP14, MC = static.V, static.O, static.W14, static.WP14, static.MC
KINDS = ('horizontal-textframe', 'vertical-outlined-textframe', 'closed-5point-polygon')
CACHE = base64.b64encode(b'independently constructed synthetic opaque data').decode()


def child(parent, tag, **attrs):
    return E.SubElement(parent, tag, attrs)


def props(parent, vertical):
    p = child(parent, W+'rPr')
    child(p, W+'rFonts', **{W+'ascii': 'Arial Narrow'})
    child(p, W+'b')
    if vertical:
        child(p, W+'bCs'); child(p, W+'outline')
    child(p, W+'color', **{W+'val': '223344', W+'themeColor': 'background2'})
    child(p, W+'spacing', **{W+'val': '3'})
    child(p, W+'sz', **{W+'val': '30'})
    child(p, W+'szCs', **{W+'val': '30'})
    if vertical:
        line = child(p, W14+'textOutline', **{W14+'w': '9525', W14+'cap': 'rnd', W14+'cmpd': 'sng', W14+'algn': 'ctr'})
        child(child(line, W14+'solidFill'), W14+'schemeClr', **{W14+'val': 'bg2'})
        child(line, W14+'prstDash', **{W14+'val': 'solid'}); child(line, W14+'bevel')
        child(child(p, W14+'textFill'), W14+'noFill')
    return p


def text_content(parent, vertical=False, paragraphs=None):
    box = child(parent, W+'txbxContent')
    if paragraphs is None:
        paragraphs = (('TEST',),) if vertical else (('Synthetic line A',), ('Synthetic ', 'line B'))
    for values in paragraphs:
        p = child(box, W+'p', **{W14+'paraId': '1234ABCD'})
        pp = child(p, W+'pPr')
        if vertical: child(pp, W+'jc', **{W+'val': 'center'})
        else:
            child(pp, W+'spacing', **{W+'before': '12', W+'line': '300', W+'lineRule': 'auto'})
            child(pp, W+'ind', **{W+'left': '8'})
        props(pp, vertical)
        for value in values:
            r = child(p, W+'r'); props(r, vertical)
            child(r, W+'t', **{static.XML+'space': 'preserve'}).text = value
    return box


def body(parent, kind):
    attrs = dict(wrap='square', lIns='0', tIns='0', rIns='0', bIns='0', rtlCol='0')
    if kind == 'vertical-outlined-textframe':
        attrs.update(rot='0', spcFirstLastPara='0', vertOverflow='overflow', horzOverflow='overflow',
                     vert='vert270', numCol='1', spcCol='0', fromWordArt='0', anchor='t',
                     anchorCtr='0', forceAA='0', compatLnSpc='1')
    b = child(parent, WPS+'bodyPr', **attrs)
    if kind != 'horizontal-textframe':
        child(child(b, A+'prstTxWarp', prst='textNoShape'), A+'avLst')
    child(b, A+'noAutofit')


def modern(kind, paragraphs=None):
    branch = E.Element(MC+'Choice', Requires='shape', nsmap={'shape': WPS[1:-1]})
    anchor = child(child(branch, W+'drawing'), WP+'anchor', distT='0', distB='0', distL='0', distR='0',
                   simplePos='0', relativeHeight='2', behindDoc='0', locked='0', layoutInCell='1', allowOverlap='1')
    child(anchor, WP+'simplePos', x='0', y='0')
    child(child(anchor, WP+'positionH', relativeFrom='page'), WP+'posOffset').text = '12000'
    child(child(anchor, WP+'positionV', relativeFrom='page'), WP+'posOffset').text = '24000'
    child(anchor, WP+'extent', cx='720000', cy='360000')
    child(anchor, WP+'effectExtent', l='0', t='0', r='0', b='0')
    child(anchor, WP+'wrapNone'); child(anchor, WP+'docPr', id='1', name='Synthetic static shape')
    child(anchor, WP+'cNvGraphicFramePr')
    shape = child(child(child(anchor, A+'graphic'), A+'graphicData', uri=WPS[1:-1]), WPS+'wsp')
    child(shape, WPS+'cNvSpPr', **({} if kind == 'closed-5point-polygon' else {'txBox':'1'}))
    sp = child(shape, WPS+'spPr')
    transform = child(sp, A+'xfrm'); child(transform, A+'off', x='0', y='0'); child(transform, A+'ext', cx='720000', cy='360000')
    if kind == 'closed-5point-polygon':
        geometry = child(sp, A+'custGeom')
        for name in ('avLst', 'gdLst', 'ahLst', 'cxnLst'): child(geometry, A+name)
        child(geometry, A+'rect', l='l', t='t', r='r', b='b')
        path = child(child(geometry, A+'pathLst'), A+'path', w='1000', h='600')
        for index, (x, y) in enumerate(((900,0),(0,0),(0,500),(700,500),(900,0))):
            child(child(path, A+('moveTo' if index == 0 else 'lnTo')), A+'pt', x=str(x), y=str(y))
        child(path, A+'close')
        child(child(sp, A+'solidFill'), A+'srgbClr', val='227799')
    else:
        child(child(sp, A+'prstGeom', prst='rect'), A+'avLst')
        if kind == 'vertical-outlined-textframe':
            child(child(sp, A+'solidFill'), A+'schemeClr', val='lt1')
            child(child(sp, A+'ln', w='6350'), A+'noFill')
        text_content(child(shape, WPS+'txbx'), kind == 'vertical-outlined-textframe', paragraphs)
    body(shape, kind)
    child(child(anchor, WP14+'sizeRelV', relativeFrom='margin'), WP14+'pctHeight').text = '0'
    return branch


def style(kind):
    relative = 'page' if kind == 'horizontal-textframe' else 'text'
    data = dict(position='absolute', **{'margin-left':'12pt', 'margin-top':'24pt', 'width':'56pt', 'height':'28pt',
        'z-index':'-2' if kind == 'horizontal-textframe' else '2', 'visibility':'visible', 'mso-wrap-style':'square',
        'mso-height-percent':'0', 'mso-wrap-distance-left':'0', 'mso-wrap-distance-top':'0',
        'mso-wrap-distance-right':'0', 'mso-wrap-distance-bottom':'0', 'mso-position-horizontal':'absolute',
        'mso-position-horizontal-relative':relative, 'mso-position-vertical':'absolute',
        'mso-position-vertical-relative':relative, 'mso-height-relative':'margin', 'v-text-anchor':'top'})
    if kind == 'horizontal-textframe': data.update({'mso-width-percent':'0','mso-width-relative':'margin'})
    return ';'.join(key+':'+value for key,value in data.items())


def legacy(kind, *, declaration=False, cache=True, paragraphs=None):
    branch = E.Element(MC+'Fallback')
    pict = child(branch, W+'pict')
    if declaration:
        definition = child(pict, V+'shapetype', id='_x0000_t202', coordsize='21600,21600',
                           **{O+'spt':'202', 'path':'m,l,21600r21600,l21600,xe'})
        child(definition, V+'stroke', joinstyle='miter')
        child(definition, V+'path', gradientshapeok='t', **{O+'connecttype':'rect'})
    attributes = dict(id='SyntheticStaticShape', style=style(kind), stroked='f')
    if cache: attributes[O+'gfxdata'] = CACHE
    if kind == 'closed-5point-polygon': attributes.update(coordsize='1000,600', path='m900,l,,,500r700,l900,xe', fillcolor='#227799')
    else:
        attributes['type'] = '#_x0000_t202'
        if kind == 'horizontal-textframe': attributes['filled'] = 'f'
        else: attributes.update(fillcolor='white [3201]', strokeweight='.5pt')
    shape = child(pict, V+'shape', **attributes)
    if kind == 'closed-5point-polygon': child(shape, V+'path', arrowok='t')
    else:
        box = child(shape, V+'textbox', **({'inset':'0,0,0,0'} if kind == 'horizontal-textframe' else {'style':'layout-flow:vertical;mso-layout-flow-alt:bottom-to-top'}))
        text_content(box, kind == 'vertical-outlined-textframe', paragraphs)
        if kind == 'horizontal-textframe': child(shape, static.W10+'wrap', anchorx='page', anchory='page')
    return branch


@pytest.mark.parametrize('kind', KINDS)
def test_three_closed_classes_exact_text_and_cache_receipts_without_mutation(kind, monkeypatch):
    monkeypatch.setattr(base64, 'b64decode', lambda *a,**kw: (_ for _ in ()).throw(AssertionError('opaque cache decoded')))
    branches = modern(kind), legacy(kind)
    before = tuple(E.tostring(branch) for branch in branches)
    records = [static.validate_static_branch(branch) for branch in branches]
    assert records[0]['class'] == records[1]['class'] == kind
    assert records[0]['paragraph_runs'] == records[1]['paragraph_runs']
    assert records[0]['text'] == records[1]['text']
    assert not records[0]['opaque_caches']
    cache = records[1]['opaque_caches'][0]
    assert cache['attribute'] == O+'gfxdata' and cache['encoded_size'] == len(CACHE)
    assert cache['sha256'] == hashlib.sha256(CACHE.encode()).hexdigest()
    node = branches[1]
    for step in cache['path']: node = node[step]
    assert node.get(O+'gfxdata') == CACHE
    assert tuple(E.tostring(branch) for branch in branches) == before
    assert all(r['node_count'] == len(list(b.iter())) and len(r['branch_sha256']) == 64 for r,b in zip(records,branches))


def test_standard_rectangular_shape_declaration_is_finite():
    static.validate_static_branch(legacy(KINDS[0], declaration=True))
    bad = legacy(KINDS[0], declaration=True)
    next(bad.iter(V+'shapetype')).set('path', 'm0,0l1,1xe')
    with pytest.raises(CompatibilityError): static.validate_static_branch(bad)


def test_exact_paragraphs_runs_empty_paragraph_and_whitespace_are_not_collapsed():
    texts = ((' A ', 'B'), (), ('C',))
    record = static.validate_static_branch(modern(KINDS[0], paragraphs=texts))
    assert record['paragraph_runs'] == texts and record['text'] == ' A BC'
    regrouped = static.validate_static_branch(modern(KINDS[0], paragraphs=((' A B',),(),('C',))))
    assert record['text'] == regrouped['text'] and record['paragraph_runs'] != regrouped['paragraph_runs']


@pytest.mark.parametrize('factory', [modern, legacy])
@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('mutation', ['unknown_attribute','foreign_attribute','relationship','unknown_element','structural_text','tail','duplicate_root_child','command','image','revision'])
def test_unknown_content_is_rejected_in_every_branch_class(factory, kind, mutation):
    branch = factory(kind)
    if mutation == 'unknown_attribute': branch.set('hidden', 'synthetic')
    elif mutation == 'foreign_attribute': branch[0].set('{urn:unknown}payload', 'synthetic')
    elif mutation == 'relationship': branch[0].set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id', 'synthetic')
    elif mutation == 'unknown_element': child(branch[0], '{urn:unknown}data')
    elif mutation == 'structural_text': branch[0].text = 'unaccounted synthetic text'
    elif mutation == 'tail': branch[0].tail = 'unaccounted synthetic tail'
    elif mutation == 'duplicate_root_child': branch.append(deepcopy(branch[0]))
    elif mutation == 'command': child(branch[0], W+'instrText').text = 'DDEAUTO synthetic'
    elif mutation == 'image': child(branch[0], A+'blip')
    elif mutation == 'revision': child(branch[0], W+'del')
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


@pytest.mark.parametrize('mutation', ['duplicate_property','misparented_property','hidden_text','nested_frame','extra_picture','zero_font','missing_font','unordered_property','line_spacing','blank_frame'])
def test_text_property_and_scaffold_negatives(mutation):
    branch = modern(KINDS[0])
    properties = next(branch.iter(W+'rPr'))
    if mutation == 'duplicate_property': properties.append(deepcopy(properties[-1]))
    elif mutation == 'misparented_property': child(next(branch.iter(A+'graphic')), W+'spacing', **{W+'val':'1'})
    elif mutation == 'hidden_text': child(properties, W+'vanish')
    elif mutation == 'nested_frame': child(next(branch.iter(W+'txbxContent')), WPS+'wsp')
    elif mutation == 'extra_picture': child(next(branch.iter(W+'r')), W+'drawing')
    elif mutation == 'zero_font': next(branch.iter(W+'sz')).set(W+'val','0')
    elif mutation == 'missing_font': properties.remove(properties[-1])
    elif mutation == 'unordered_property': properties.insert(0,properties[-1])
    elif mutation == 'line_spacing': next(branch.iter(W+'spacing')).set(W+'lineRule','unsupported')
    else:
        for node in branch.iter(W+'t'): node.text = ' '
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


@pytest.mark.parametrize('mutation', ['open','extra_point','curve','formula','out_of_box','different_closure','second_path','gradient','inconsistent_extent'])
def test_modern_polygon_is_only_one_closed_fixed_topology(mutation):
    branch = modern(KINDS[2]); path = next(branch.iter(A+'path'))
    if mutation == 'open': path.remove(path[-1])
    elif mutation == 'extra_point': path.insert(1,deepcopy(path[1]))
    elif mutation == 'curve': path[1].tag = A+'arcTo'
    elif mutation == 'formula': child(next(branch.iter(A+'gdLst')), A+'gd', name='synthetic', fmla='val 1')
    elif mutation == 'out_of_box': path[0][0].set('x','1001')
    elif mutation == 'different_closure': path[-2][0].set('x','800')
    elif mutation == 'second_path': path.getparent().append(deepcopy(path))
    elif mutation == 'gradient': next(branch.iter(A+'solidFill')).tag = A+'gradFill'
    else: next(branch.iter(WP+'extent')).set('cx','800000')
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


@pytest.mark.parametrize('path', ['m900,l,,,500r700,l900,xeSECRET', 'm900,l,,,500r700,l800,xe',
    'm1001,l,,,500r700,l1001,xe', 'm900,l,,,601r700,l900,xe', 'm900,l,,,500r950,l900,xe',
    'm900,l,,,500r700,l900,x', 'm900,l,,,500q700,l900,xe', 'm-900,l,,,500r700,l-900,xe'])
def test_vml_polygon_rejects_any_other_topology_or_trailing_token(path):
    branch = legacy(KINDS[2]); next(branch.iter(V+'shape')).set('path',path)
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


@pytest.mark.parametrize('mutation', ['no_outline','zero_outline','invisible_without_outline','wrong_direction','unknown_effect','bad_vertical_style'])
def test_visible_outline_exception_is_not_a_general_effect_or_hidden_text_path(mutation):
    branch = legacy(KINDS[1]) if mutation == 'bad_vertical_style' else modern(KINDS[1])
    outline = next(branch.iter(W14+'textOutline'))
    if mutation == 'no_outline': outline.getparent().remove(outline)
    elif mutation == 'zero_outline': outline.set(W14+'w','0')
    elif mutation == 'invisible_without_outline': outline.tag = W14+'textShadow'
    elif mutation == 'wrong_direction': next(branch.iter(WPS+'bodyPr')).set('vert','vert')
    elif mutation == 'unknown_effect': child(outline, W14+'glow')
    else: next(branch.iter(V+'textbox')).set('style','layout-flow:vertical;display:none')
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


@pytest.mark.parametrize('suffix', [';background:url(https://invalid.example)', ';margin-left:12pt', ';mso-height-percent:1',
    ';onclick:synthetic', ';visibility:hidden', ';width:0', ';z-index:99999999999999999'])
def test_closed_style_rejects_unknown_or_conflicting_data(suffix):
    branch = legacy(KINDS[0]); shape = next(branch.iter(V+'shape'))
    shape.set('style',shape.get('style')+suffix)
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


def test_only_identical_named_zero_percent_repetition_is_accepted():
    branch = legacy(KINDS[0]); shape = next(branch.iter(V+'shape'))
    shape.set('style',shape.get('style')+';mso-height-percent:0;mso-width-percent:0')
    static.validate_static_branch(branch)


@pytest.mark.parametrize('value', ['', '  ', 'not base64!', 'A', '====', 'A===', 'AAAA='])
def test_opaque_cache_has_bounded_encoded_syntax(value):
    branch = legacy(KINDS[0]); next(branch.iter(V+'shape')).set(O+'gfxdata',value)
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


@pytest.mark.parametrize('budget', ['MAX_NODES','MAX_DEPTH','MAX_BRANCH_CHARS','MAX_TEXT','MAX_CACHE'])
def test_resource_limits_fail_closed_before_return(monkeypatch,budget):
    monkeypatch.setattr(static,budget,1)
    with pytest.raises(CompatibilityError): static.validate_static_branch(legacy(KINDS[0]))


@pytest.mark.parametrize('mutation', ['wrong_namespace','unbound_requires','extra_requires','wrong_root'])
def test_standalone_branch_capability_is_not_inferred_from_prefix_spelling(mutation):
    branch = modern(KINDS[0])
    if mutation == 'wrong_namespace':
        changed=E.Element(MC+'Choice',Requires='shape',nsmap={'shape':'urn:unknown'})
        changed.append(branch[0]);branch=changed
    elif mutation == 'unbound_requires': branch.set('Requires','missing')
    elif mutation == 'extra_requires': branch.set('Requires','shape shape')
    else: branch.tag=W+'drawing'
    with pytest.raises(CompatibilityError): static.validate_static_branch(branch)


def test_no_shared_picture_grammar_is_mutated():
    from app import monthly_report_compatibility_view as compatibility
    attributes = {key:dict(value) for key,value in compatibility.ATTRS.items()}
    children = {key:set(value) for key,value in compatibility.CHILDREN.items()}
    for kind in KINDS: static.validate_static_branch(modern(kind))
    assert compatibility.ATTRS == attributes and compatibility.CHILDREN == children


def definition_document(*, reference=True, declaration=True):
    """Independent standard template outside the candidate's paragraph."""
    root = E.Element(W+'document')
    body = child(root, W+'body')
    candidate = child(child(body, W+'p'), W+'r')
    candidate.append(legacy(KINDS[0]) if reference else modern(KINDS[2]))
    if declaration:
        definition = next(legacy(KINDS[0], declaration=True).iter(V+'shapetype'))
        child(child(child(body, W+'p'), W+'r'), W+'pict').append(definition)
    return root


def test_document_scope_definition_is_validated_outside_candidate_without_mutation():
    from app.monthly_report_compatibility_view import _subtree_digest
    root = definition_document()
    before = E.tostring(root)
    result = static.validate_static_definitions(root)
    definition = next(root.iter(V+'shapetype'))
    assert result == {'reference_count': 1, 'node_count': sum(1 for _ in root.iter()),
                      'definitions': ({'path': (0, 1, 0, 0, 0),
                                       'sha256': _subtree_digest(definition), 'node_count': 3},)}
    assert E.tostring(root) == before
    assert next(root.iter(MC+'Fallback')).find('.//'+V+'shapetype') is None


def test_standard_shape_is_not_assumed_to_have_an_implicit_declaration():
    with pytest.raises(CompatibilityError, match='not declared'):
        static.validate_static_definitions(definition_document(declaration=False))


@pytest.mark.parametrize('declaration', [False, True])
def test_unreferenced_standard_template_is_still_validated_when_present(declaration):
    result = static.validate_static_definitions(definition_document(reference=False, declaration=declaration))
    assert result['reference_count'] == 0
    assert len(result['definitions']) == int(declaration)


@pytest.mark.parametrize('mutation', [
    'path', 'coordsize', 'spt', 'fill', 'stroke', 'child_path', 'command',
    'relationship', 'extra_child', 'hidden_text', 'tail', 'reordered', 'duplicate_child',
])
def test_conflicting_outside_candidate_template_fails_closed(mutation):
    root = definition_document()
    definition = next(root.iter(V+'shapetype'))
    if mutation == 'path': definition.set('path', 'm0,0l1,1xe')
    elif mutation == 'coordsize': definition.set('coordsize', '100,100')
    elif mutation == 'spt': definition.set(O+'spt', '203')
    elif mutation == 'fill': definition.set('fillcolor', '#000000')
    elif mutation == 'stroke': definition[0].set('joinstyle', 'round')
    elif mutation == 'child_path': definition[1].set(O+'connecttype', 'none')
    elif mutation == 'command': child(definition, W+'instrText').text = 'SYNTHETIC FIELD'
    elif mutation == 'relationship':
        definition.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id', 'synthetic')
    elif mutation == 'extra_child': child(definition, V+'formulas')
    elif mutation == 'hidden_text': definition.text = 'synthetic hidden content'
    elif mutation == 'tail': definition.tail = 'synthetic hidden tail'
    elif mutation == 'reordered': definition.insert(0, definition[1])
    else: definition.append(deepcopy(definition[0]))
    with pytest.raises(CompatibilityError): static.validate_static_definitions(root)


@pytest.mark.parametrize('inside_group', [False, True])
@pytest.mark.parametrize('anchor_metadata', [False, True])
def test_repeated_standard_definitions_individually_validate_and_remain_audited(inside_group, anchor_metadata):
    root = definition_document()
    definition = next(root.iter(V+'shapetype'))
    duplicate = deepcopy(definition)
    if anchor_metadata:
        definition.set(W14+'anchorId', '1234ABCD')
        duplicate.set(W14+'anchorId', '5678EFAB')
    container = child(root[0], V+'group') if inside_group else root[0]
    container.append(duplicate)
    before = E.tostring(root)
    result = static.validate_static_definitions(root)
    assert result['reference_count'] == 1
    first, second = result['definitions']
    assert first['path'] != second['path']
    assert (first['sha256'] != second['sha256']) == anchor_metadata
    assert first['node_count'] == second['node_count'] == 3
    assert E.tostring(root) == before


@pytest.mark.parametrize('mutation', ['path', 'unknown_attribute', 'unknown_child', 'anchor_metadata',
                                    'anchor_on_child', 'whitespace_text', 'whitespace_tail'])
@pytest.mark.parametrize('context', ['group', 'discarded_fallback', 'revision'])
def test_every_repeated_declaration_is_validated_even_outside_retained_content(mutation, context):
    root = definition_document()
    duplicate = deepcopy(next(root.iter(V+'shapetype')))
    container = child(root[0], {'group': V+'group', 'discarded_fallback': MC+'Fallback', 'revision': W+'del'}[context])
    container.append(duplicate)
    if mutation == 'path': duplicate.set('path', 'm0,0l1,1xe')
    elif mutation == 'unknown_attribute': duplicate.set('synthetic', 'unknown')
    elif mutation == 'unknown_child': child(duplicate, V+'formulas')
    elif mutation == 'anchor_metadata': duplicate.set(W14+'anchorId', 'not-hex')
    elif mutation == 'anchor_on_child': duplicate[0].set(W14+'anchorId', '1234ABCD')
    elif mutation == 'whitespace_text': duplicate.text = ' '
    else: duplicate.tail = ' '
    with pytest.raises(CompatibilityError): static.validate_static_definitions(root)


def test_standard_declaration_count_is_bounded_without_coalescing():
    root = definition_document()
    definition = next(root.iter(V+'shapetype'))
    for _ in range(static.MAX_STANDARD_DEFINITIONS - 1):
        root[0].append(deepcopy(definition))
    assert len(static.validate_static_definitions(root)['definitions']) == static.MAX_STANDARD_DEFINITIONS
    root[0].append(deepcopy(definition))
    with pytest.raises(CompatibilityError, match='budget'): static.validate_static_definitions(root)


def test_remaining_references_fail_if_the_only_declaration_is_removed():
    root = definition_document()
    static.validate_static_definitions(root)
    definition = next(root.iter(V+'shapetype'))
    definition.getparent().remove(definition)
    with pytest.raises(CompatibilityError, match='not declared'): static.validate_static_definitions(root)


def test_removing_one_standard_declaration_keeps_other_reference_resolution_bound():
    root = definition_document()
    definition = next(root.iter(V+'shapetype'))
    root[0].append(deepcopy(definition))
    original = static.validate_static_definitions(root)
    definition.getparent().remove(definition)
    derivative = static.validate_static_definitions(root)
    assert derivative['reference_count'] == original['reference_count'] == 1
    assert len(original['definitions']) == 2 and len(derivative['definitions']) == 1
    assert derivative['definitions'][0]['sha256'] == original['definitions'][1]['sha256']


def test_non_template_vml_identifier_cannot_shadow_standard_template():
    root = definition_document()
    child(root[0], V+'shape', id='_x0000_t202')
    with pytest.raises(CompatibilityError, match='identifier'):
        static.validate_static_definitions(root)


def test_unrelated_template_id_does_not_resolve_a_standard_reference():
    root = definition_document()
    next(root.iter(V+'shapetype')).set('id', 'SyntheticOtherType')
    with pytest.raises(CompatibilityError, match='not declared'):
        static.validate_static_definitions(root)


@pytest.mark.parametrize('budget', ['MAX_DEFINITION_PART_NODES', 'MAX_DEFINITION_PART_DEPTH', 'MAX_DEFINITION_PART_CHARS'])
def test_document_scope_definition_scan_has_independent_budgets(monkeypatch, budget):
    monkeypatch.setattr(static, budget, 1)
    with pytest.raises(CompatibilityError, match='budget'):
        static.validate_static_definitions(definition_document())


@pytest.mark.parametrize('mutation', ['subtree', 'attached_root', 'comment'])
def test_definition_scope_cannot_be_a_selected_subtree_or_non_element(mutation):
    root = definition_document()
    if mutation == 'subtree': root = root[0]
    elif mutation == 'attached_root': E.Element('syntheticContainer').append(root)
    else: root[0].append(E.Comment('synthetic comment'))
    with pytest.raises(CompatibilityError): static.validate_static_definitions(root)
