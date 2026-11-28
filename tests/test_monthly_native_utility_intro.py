"""Utility decoration removal needs positive source identity and ownership."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from docx import Document
from docx.oxml import OxmlElement
from lxml import etree

from app.monthly_report_compatibility_view import derive_compatibility_view
from app.monthly_report_native_art_scope import expected_header_scope, NativeEmissionProof, W
from app.monthly_report_native_utility_intro import UtilityDecorationReceipt, _decoration_plain
from app.monthly_report_native_utility_prune import plan_utility_section_prune
from app.monthly_report_model import ResolvedBlock, DraftParagraph
from test_monthly_native_utility_prune import fixture as plain_fixture


def fixture(tmp_path):
    path, _, _ = plain_fixture(tmp_path)
    doc = Document(path)
    old = next(p for p in doc.paragraphs if p.text.startswith('Rate-trend'))
    for text in ('Client Utility Rate Analysis Author: Synthetic', 'October 2026'):
        para = doc.add_paragraph(text)
        old._p.addprevious(para._p)
        if text.startswith('Client'):
            para._p.get_or_add_pPr().append(OxmlElement('w:pageBreakBefore'))
            para.runs[0]._r.insert(0, OxmlElement('w:lastRenderedPageBreak'))
    spacing = OxmlElement('w:spacing'); spacing.set(W+'val', '-4')
    old.runs[0]._r.get_or_add_rPr().append(spacing)
    para = doc.add_paragraph('RATE TREND'); old._p.addnext(para._p)
    doc.save(path)
    return refreshed(path)


def refreshed(path):
    view = derive_compatibility_view(path.read_bytes())
    return path, view, expected_header_scope(view)


def plan(f, blocks=()):
    return plan_utility_section_prune(*f[:2], SimpleNamespace(
        blocks=blocks, period=SimpleNamespace(label='November 2026')), f[2])


def output(f):
    """Independent simulation of production's known source-normalizing writes."""
    from app.monthly_report_native_layout import _set_text
    from app.monthly_report_import import _text
    path, view, scope = f
    with ZipFile(BytesIO(view.rendition_bytes)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = etree.fromstring(parts['word/document.xml']); body = root.find(W+'body')
    owners, records, section = [], [], 1
    for pos, node in enumerate(body, 1):
        owners.append(section)
        boundary = node.tag == W+'sectPr' or node.find('.//'+W+'sectPr') is not None
        support = False; text = _text(node)
        if section == 3:
            if text.startswith('Client Utility Rate Analysis'):
                _set_text(node, 'Client Utility Rate Analysis'); support = True
            elif text == 'October 2026':
                _set_text(node, 'November 2026'); support = True
            elif text == 'RATE TREND':
                for n in node.iter(W+'t'): n.text = ''
            elif text:
                _set_text(node, '')
                pr = node.find(W+'pPr')
                if pr is not None:
                    num = OxmlElement('w:numPr'); ident = OxmlElement('w:numId')
                    ident.set(W+'val', '0'); num.append(ident); pr.append(num)
        records.append((pos, False, support, False))
        if boundary: section += 1
    parts['word/document.xml'] = etree.tostring(root)
    return pack(parts), NativeEmissionProof(scope.sha256, tuple(owners)), UtilityDecorationReceipt(scope.sha256, tuple(records), tuple((owner, *record) for owner, record in zip(owners, records) if record[1] or record[2] or record[3]))


def pack(parts):
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as z:
        for n, b in parts.items(): z.writestr(n, b)
    return stream.getvalue()


def test_exact_source_envelope_and_receipt(tmp_path):
    f = fixture(tmp_path); candidate = plan(f)
    assert candidate is not None and candidate.source_sections == (3,)
    assert len(candidate.decoration_sources) == 1
    raw, proof, receipt = output(f)
    result, scope, final = candidate.apply(raw, proof, {3}, decoration_receipt=receipt)
    assert result != raw and scope.source_word_sections == (1, 2, 4, 5)
    assert len(Document(BytesIO(result)).sections) == 4
    with ZipFile(BytesIO(raw)) as a, ZipFile(BytesIO(result)) as b:
        assert [n for n in a.namelist() if a.read(n) != b.read(n)] == ['word/document.xml']


@pytest.mark.parametrize('case', ['missing', 'scope', 'length', 'position', 'live', 'heading', 'missing-support', 'extra-support', 'unknown-position'])
def test_wrong_or_active_ownership_never_borrows_decoration_permission(tmp_path, case):
    f = fixture(tmp_path); c = plan(f); raw, proof, r = output(f)
    records = list(r.roots); start = f[2].source_section_ends[1]
    if case == 'missing': r = None
    elif case == 'scope': r = replace(r, scope_sha256='wrong')
    elif case == 'length': r = replace(r, roots=r.roots[:-1])
    else:
        index = start + (2 if case == 'extra-support' else 0)
        pos, live, support, heading = records[index]
        if case == 'position': pos += 1
        elif case == 'unknown-position': pos = None
        elif case == 'live': live = True
        elif case == 'heading': heading = True
        elif case == 'missing-support': support = False
        else: support = True
        records[index] = (pos, live, support, heading)
        r = replace(r, roots=tuple(records))
    assert c.apply(raw, proof, {3}, decoration_receipt=r) == (raw, f[2], proof)


@pytest.mark.parametrize('tag', ['drawing', 'bookmarkStart', 'hyperlink', 'fldSimple', 'sdt', 'ins', 'pStyle', 'numPr'])
def test_unknown_intro_markup_refuses_planning(tmp_path, tag):
    path, _, _ = fixture(tmp_path); d = Document(path)
    old = next(p for p in d.paragraphs if p.text.startswith('Client'))
    old._p.append(OxmlElement('w:'+tag)); d.save(path)
    assert plan(refreshed(path)) is None


@pytest.mark.parametrize('case', ['duplicate-label', 'duplicate-month', 'missing-label', 'missing-month', 'break-on-narrative', 'break-attributes', 'cache-attributes', 'duplicate-break', 'hidden-break-text', 'nested-spacing', 'spacing-text', 'spacing-tail', 'spacing-attributes', 'spacing-invalid', 'duplicate-spacing'])
def test_decoration_grammar_is_closed(tmp_path, case):
    path, _, _ = fixture(tmp_path); d = Document(path)
    label = next(p for p in d.paragraphs if p.text.startswith('Client'))
    month = next(p for p in d.paragraphs if p.text == 'October 2026')
    narrative = next(p for p in d.paragraphs if p.text.startswith('Rate-trend'))
    spacing = narrative._p.find('.//'+W+'rPr/'+W+'spacing')
    marker = label._p.find('./'+W+'pPr/'+W+'pageBreakBefore')
    if case == 'duplicate-label': label._p.addnext(deepcopy(label._p))
    elif case == 'duplicate-month': month._p.addnext(deepcopy(month._p))
    elif case == 'missing-label': label.text = ''
    elif case == 'missing-month': month.text = ''
    elif case == 'break-on-narrative': narrative._p.get_or_add_pPr().append(OxmlElement('w:pageBreakBefore'))
    elif case == 'break-attributes': marker.set(W+'val', 'false')
    elif case == 'cache-attributes': label._p.find('.//'+W+'lastRenderedPageBreak').set(W+'val', '1')
    elif case == 'duplicate-break': marker.addnext(deepcopy(marker))
    elif case == 'hidden-break-text': marker.text = 'Hidden'
    elif case == 'nested-spacing': spacing.append(OxmlElement('w:spacing'))
    elif case == 'spacing-text': spacing.text = 'Hidden'
    elif case == 'spacing-tail': spacing.tail = 'Hidden'
    elif case == 'spacing-attributes': spacing.set(W+'unknown', '1')
    elif case == 'spacing-invalid': spacing.set(W+'val', '1.5')
    else: spacing.addnext(deepcopy(spacing))
    d.save(path)
    assert plan(refreshed(path)) is None


@pytest.mark.parametrize('field,value', [('text', 'Current'), ('rows', (('Current',),)), ('extra_tables', ('table',)), ('asset_hashes', ('asset',)), ('asset_instances', ('instance',)), ('org_nodes', ('node',)), ('ai_paragraphs', (DraftParagraph('', (), ()),)), ('references', ('source:synthetic',))])
def test_current_payload_blocks_decoration_scope(tmp_path, field, value):
    assert plan(fixture(tmp_path), (replace(ResolvedBlock('utility_analysis', 'This month'), **{field:value}),)) is None


@pytest.mark.parametrize('target', ['label', 'month', 'narrative', 'rate'])
def test_modified_final_root_is_retained(tmp_path, target):
    f = fixture(tmp_path); c = plan(f); raw, proof, receipt = output(f)
    with ZipFile(BytesIO(raw)) as z: parts = {n:z.read(n) for n in z.namelist()}
    root = etree.fromstring(parts['word/document.xml']); body = root.find(W+'body')
    index = f[2].source_section_ends[1] + ('label', 'month', 'narrative', 'rate').index(target)
    body[index].find('.//'+W+'t').text = 'Unexpected'
    parts['word/document.xml'] = etree.tostring(root); changed = pack(parts)
    assert c.apply(changed, proof, {3}, decoration_receipt=receipt) == (changed, f[2], proof)


def test_reserved_intro_is_not_disposable(tmp_path):
    f = fixture(tmp_path); c = plan(f); raw, proof, receipt = output(f)
    proof = replace(proof, reserved_source_sections=(3,))
    assert c.apply(raw, proof, {3}, decoration_receipt=receipt) == (raw, f[2], proof)


def test_public_saved_reopened_builder_uses_actual_ownership(tmp_path, monkeypatch):
    from app import monthly_report_library as library
    from app.monthly_report_native_layout import build_native_docx
    from app.monthly_report_native_art_review import verify_native_art_output, verify_native_art_review
    from test_monthly_report_native_art_review import setup
    from test_monthly_report_native_art_lifecycle import save_sample
    from unittest.mock import patch
    from app import monthly_report_native_utility_prune as cleanup
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path/'store'))
    path, _, _ = fixture(tmp_path)
    from test_monthly_report_source_frame_logo_role import raster
    from docx.shared import Inches
    doc = Document(path)
    for index in (2, 3): doc.sections[index].header.is_linked_to_previous = False
    doc.sections[2].header.paragraphs[0].add_run().add_picture(BytesIO(raster('orange')), width=Inches(1))
    doc.save(path)
    sample = setup(path); path, view, profile, period, inventory, review = sample
    saved, loader = save_sample(sample)
    loaded = library.load_imported_draft(profile.contract, profile.key, source_view=view)
    assert loaded == saved
    draft = replace(loaded, blocks=tuple(b for b in loaded.blocks if b.key != 'utility_analysis'))
    before, fingerprint = path.read_bytes(), draft.fingerprint
    with patch.object(cleanup.UtilitySectionPrune, 'apply', lambda self, raw, proof, active, **kw: (raw, self.full_scope, proof)):
        base = build_native_docx(draft, path, asset_loader=loader, source_view=view)
    fixed = build_native_docx(draft, path, asset_loader=loader, source_view=view)
    assert len(Document(BytesIO(base)).sections) == 5
    assert len(Document(BytesIO(fixed)).sections) == 4
    context = verify_native_art_review(path, view, profile, period, review)
    with pytest.raises(ValueError):
        verify_native_art_output(fixed, context, source_scope=expected_header_scope(view))
    assert path.read_bytes() == before and draft.fingerprint == fingerprint
    for field, value in [('text', 'Current utility analysis.'), ('ai_paragraphs', (DraftParagraph('Current AI analysis.', (), ()),)), ('references', ('source:synthetic',))]:
        live = replace(draft, blocks=(*draft.blocks, replace(ResolvedBlock('utility_analysis', 'This month'), **{field:value})))
        raw = build_native_docx(live, path, asset_loader=loader, source_view=view)
        assert len(Document(BytesIO(raw)).sections) == 5
    preview = build_native_docx(draft, path, asset_loader=loader, section_key='scorecards', source_view=view)
    assert 'Client Utility Rate Analysis' in '\n'.join(p.text for p in Document(BytesIO(preview)).paragraphs)


def test_scope_preview_and_omission_refuse_intro(tmp_path):
    path, view, scope = fixture(tmp_path)
    assert plan((path, view, replace(scope, section_key='scorecards'))) is None
    assert plan((path, view, replace(scope, omitted_sections=('water',)))) is None


@pytest.mark.parametrize('activity', [(3, 9999, True, False, False), (3, 9999, False, False, True), (3, 9999, False, True, False), (3, None, False, True, False), (None, None, True, False, False)])
def test_detached_or_unknown_activity_blocks_intro(tmp_path, activity):
    f = fixture(tmp_path); c = plan(f); raw, proof, receipt = output(f)
    receipt = replace(receipt, activities=(*receipt.activities, activity))
    assert c.apply(raw, proof, {3}, decoration_receipt=receipt) == (raw, f[2], proof)


@pytest.mark.parametrize('case', ['root-text', 'run-text', 'property-text', 'text-tail', 'root-tail'])
def test_hidden_final_xml_values_are_not_ignored(tmp_path, case):
    f = fixture(tmp_path); c = plan(f); raw, proof, receipt = output(f)
    with ZipFile(BytesIO(raw)) as z: parts = {n:z.read(n) for n in z.namelist()}
    root = etree.fromstring(parts['word/document.xml']); body = root.find(W+'body')
    label = body[f[2].source_section_ends[1]]
    if case == 'root-text': label.text = 'Hidden'
    elif case == 'run-text': label.find(W+'r').text = 'Hidden'
    elif case == 'property-text': label.find(W+'pPr').text = 'Hidden'
    elif case == 'text-tail': label.find('.//'+W+'t').tail = 'Hidden'
    else: label.tail = 'Hidden'
    parts['word/document.xml'] = etree.tostring(root); changed = pack(parts)
    assert c.apply(changed, proof, {3}, decoration_receipt=receipt) == (changed, f[2], proof)
