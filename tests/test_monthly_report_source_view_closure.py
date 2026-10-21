"""Synthetic closure and occurrence-reference regressions; no real report data."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.oxml.ns import qn
from lxml import etree as ET
import pytest

from app import monthly_report_compatibility_view as compatibility
from app.monthly_report_import import DocxInspection, ImportItem
from test_monthly_report_source_frame_logo_role import source, MC, A


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def parts(raw):
    with ZipFile(BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def package(values):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, raw in values.items():
            archive.writestr(name, raw)
    return output.getvalue()


def add_chrome(path, definitions, *, inherited=False, ambient_reference=False):
    """Each definition is (header/footer, part suffix, aliases, live alias/type)."""
    if inherited:
        document = Document(path)
        document.add_section()
        document.save(path)
    values = parts(path.read_bytes())
    root = ET.fromstring(values["word/document.xml"])
    relations = ET.fromstring(values["word/_rels/document.xml.rels"])
    types = ET.fromstring(values["[Content_Types].xml"])
    sections = list(root.iter(W + "sectPr"))
    if inherited:
        assert len(sections) == 2
    for kind, suffix, aliases, live in definitions:
        name = f"word/{kind}{suffix}.xml"
        chrome = ET.Element(W + ("hdr" if kind == "header" else "ftr"), nsmap={"w": W[1:-1]})
        ET.SubElement(ET.SubElement(ET.SubElement(chrome, W + "p"), W + "r"), W + "t").text = (
            "Synthetic retained running artwork caption")
        values[name] = ET.tostring(chrome, xml_declaration=True, encoding="UTF-8")
        ET.SubElement(types, CT + "Override", PartName="/" + name,
                      ContentType=f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml")
        for alias in aliases:
            ET.SubElement(relations, REL + "Relationship", Id=alias,
                          Type=R[1:-1] + "/" + kind, Target=name.removeprefix("word/"))
        if live is not None:
            alias, mode = live
            if ambient_reference:
                # Any original r:* attribute is a live reference, not only r:id.
                root.set(R + "embed", alias)
            else:
                ET.SubElement(sections[0] if inherited else sections[-1], W + kind + "Reference",
                              {W + "type": mode, R + "id": alias})
            if mode == "first":
                ET.SubElement(sections[0] if inherited else sections[-1], W + "titlePg")
            if mode == "even":
                settings = ET.fromstring(values["word/settings.xml"])
                ET.SubElement(settings, W + "evenAndOddHeaders")
                values["word/settings.xml"] = ET.tostring(settings)
    values["word/document.xml"] = ET.tostring(root)
    values["word/_rels/document.xml.rels"] = ET.tostring(relations)
    values["[Content_Types].xml"] = ET.tostring(types)
    path.write_bytes(package(values))
    return tuple(f"word/{kind}{suffix}.xml" for kind, suffix, _, _ in definitions)


def chrome_bindings(view, name):
    original = {item.id: item for item in view.original_inspection.items if item.part == name}
    assert original, "Fixture must expose the original chrome occurrence to inspection."
    return tuple(binding for binding in view.bindings if binding.original_id in original)


@pytest.mark.parametrize("kind", ["header", "footer"])
@pytest.mark.parametrize("aliases", [("rChromeUnused",), ("rChromeAliasA", "rChromeAliasB")])
def test_zero_live_aliases_archive_only_unreferenced_chrome(tmp_path, kind, aliases):
    path = source(tmp_path, divergent=True, shared_outside=False)
    (name,) = add_chrome(path, ((kind, "41", aliases, None),))
    before = path.read_bytes()
    view = compatibility.derive_compatibility_view(before)
    receipt = json.loads(view.receipt_bytes)
    assert receipt["archived_unreferenced_chrome"] == [name]
    assert name in parts(before) and name not in parts(view.rendition_bytes)
    assert all(binding.status == "archived-only" and binding.rendition_id is None
               for binding in chrome_bindings(view, name))
    assert [b.original_id for b in view.bindings] == [i.id for i in view.original_inspection.items]
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["header", "footer"])
@pytest.mark.parametrize("mode", ["default", "first", "even", "inherited"])
def test_live_default_first_even_and_inherited_chrome_are_retained(tmp_path, kind, mode):
    path = source(tmp_path, divergent=True, shared_outside=False)
    (name,) = add_chrome(path, ((kind, "41", ("rChromeLive",),
                                ("rChromeLive", "default" if mode == "inherited" else mode)),),
                        inherited=mode == "inherited")
    before = parts(path.read_bytes())
    view = compatibility.derive_compatibility_view(path.read_bytes())
    after = parts(view.rendition_bytes)
    assert json.loads(view.receipt_bytes)["archived_unreferenced_chrome"] == []
    assert after[name] == before[name]
    assert all(b.status == "retained" and b.rendition_id for b in chrome_bindings(view, name))
    original_sections = list(ET.fromstring(before["word/document.xml"]).iter(W + "sectPr"))
    output_sections = list(ET.fromstring(after["word/document.xml"]).iter(W + "sectPr"))
    assert [tuple((n.tag, sorted(n.attrib.items())) for n in section if n.tag.endswith("Reference"))
            for section in output_sections] == [
                tuple((n.tag, sorted(n.attrib.items())) for n in section if n.tag.endswith("Reference"))
                for section in original_sections]
    if mode == "inherited":
        assert not output_sections[-1].findall(W + kind + "Reference")
        assert output_sections[0].find(W + kind + "Reference") is not None


@pytest.mark.parametrize("kind", ["header", "footer"])
@pytest.mark.parametrize("live_alias", ["rChromeAliasA", "rChromeAliasB"])
def test_any_live_alias_prevents_archiving_shared_target(tmp_path, kind, live_alias):
    path = source(tmp_path, divergent=True, shared_outside=False)
    (name,) = add_chrome(path, ((kind, "41", ("rChromeAliasA", "rChromeAliasB"),
                                (live_alias, "default")),))
    view = compatibility.derive_compatibility_view(path.read_bytes())
    assert name not in json.loads(view.receipt_bytes)["archived_unreferenced_chrome"]
    assert name in parts(view.rendition_bytes)
    assert all(b.status == "retained" for b in chrome_bindings(view, name))
    relationships = ET.fromstring(parts(view.rendition_bytes)["word/_rels/document.xml.rels"])
    aliases = {node.get("Id") for node in relationships if node.get("Target") == name.removeprefix("word/")}
    assert aliases == {live_alias}


def test_original_non_id_relationship_attribute_is_still_live(tmp_path):
    path = source(tmp_path, divergent=True, shared_outside=False)
    (name,) = add_chrome(path, (("header", "41", ("rChromeLive",), ("rChromeLive", "default")),),
                        ambient_reference=True)
    view = compatibility.derive_compatibility_view(path.read_bytes())
    assert name not in json.loads(view.receipt_bytes)["archived_unreferenced_chrome"]
    assert all(b.status == "retained" for b in chrome_bindings(view, name))


def test_equal_byte_distinct_header_parts_are_not_coalesced(tmp_path):
    path = source(tmp_path, divergent=True, shared_outside=False)
    names = add_chrome(path, (
        ("header", "41", ("rHeaderDefault",), ("rHeaderDefault", "default")),
        ("header", "42", ("rHeaderFirst",), ("rHeaderFirst", "first")),
    ))
    before = parts(path.read_bytes())
    assert before[names[0]] == before[names[1]]
    view = compatibility.derive_compatibility_view(path.read_bytes())
    after = parts(view.rendition_bytes)
    assert all(after[name] == before[name] for name in names)
    original = {item.id: item for item in view.original_inspection.items}
    rendered = {item.id: item for item in view.rendition_inspection.items}
    bindings = tuple(b for name in names for b in chrome_bindings(view, name))
    assert len(bindings) == 2 and len({b.rendition_id for b in bindings}) == 2
    assert all(original[b.original_id].part == rendered[b.rendition_id].part for b in bindings)


def inspections(*extra):
    candidate = ImportItem("cover-diagnostic", "unsupported", "word/document.xml", 1, 1,
                           section="cover", text="INSERT CLIENT LOGO", note="Alternate Word representations differ")
    rendered = replace(candidate, id="cover-native", kind="native_layout", note="Native cover title and artwork")
    original = DocxInspection("a" * 64, (candidate, *extra), (), (), 1)
    rendition = replace(original, sha256="b" * 64, items=(rendered, *extra))
    return original, rendition, {candidate.id}


def test_retained_chrome_can_change_only_ambient_section_annotation():
    header = ImportItem("header", "text", "word/header41.xml", 1, 1,
                        section="activity", text="Synthetic retained caption", suggested_slot="header_text")
    original, rendition, candidates = inspections(header)
    rendition = replace(rendition, items=(rendition.items[0], replace(header, section="cover")))
    binding = compatibility._bind(original, rendition, candidates)[1]
    assert binding.status == "retained" and binding.original_section == "activity"
    assert binding.rendition_section == "cover"


@pytest.mark.parametrize("changed", [
    {"text": "Changed chrome text"}, {"note": "Changed chrome note"},
    {"part": "word/header42.xml"}, {"position": 2}, {"word_section": 2},
    {"suggested_slot": "client_logo"}, {"image_role": "client_logo"},
    {"image_digest": "c" * 64},
])
def test_retained_chrome_other_mismatch_fails_binding(changed):
    header = ImportItem("header", "text", "word/header41.xml", 1, 1,
                        section="activity", text="Synthetic retained caption")
    original, rendition, candidates = inspections(header)
    rendition = replace(rendition, items=(rendition.items[0], replace(header, section="cover", **changed)))
    with pytest.raises(compatibility.CompatibilityError, match="visible original occurrence"):
        compatibility._bind(original, rendition, candidates)


def test_unrelated_native_note_mismatch_is_not_normalized():
    unrelated = ImportItem("other-native", "native_layout", "word/document.xml", 5, 1,
                           section="activity", text="Synthetic unrelated frame", note="Editable native text frames")
    original, rendition, candidates = inspections(unrelated)
    rendition = replace(rendition, items=(rendition.items[0], replace(unrelated, note="Different native classification")))
    with pytest.raises(compatibility.CompatibilityError, match="visible original occurrence"):
        compatibility._bind(original, rendition, candidates)


def test_multiple_wrapper_paths_are_original_and_selected_occurrences_survive_closure(tmp_path):
    def duplicate(document, slot, wrapper, fallback):
        second = deepcopy(wrapper)
        for branch in second:
            next(branch.iter(qn("wp:extent"))).set("cx", "2100000")
        wrapper.addnext(second)

    path = source(tmp_path, divergent=True, shared_outside=False, mutation=duplicate)
    before = path.read_bytes()
    original_root = ET.fromstring(parts(before)["word/document.xml"])
    original_wrappers = list(original_root.iter(MC + "AlternateContent"))
    expected = [(original_root.getroottree().getpath(wrapper), hashlib.sha256(ET.tostring(wrapper)).hexdigest())
                for wrapper in original_wrappers]
    assert len(expected) == 2 and expected[0][0] != expected[1][0]
    view = compatibility.derive_compatibility_view(before)
    records = json.loads(view.receipt_bytes)["resolutions"]
    assert [(record["wrapper_path"], record["wrapper_sha256"]) for record in records] == expected
    assert [record["wrapper_index"] for record in records] == [0, 1]
    selected_root = ET.fromstring(parts(view.rendition_bytes)["word/document.xml"])
    assert not list(selected_root.iter(MC + "AlternateContent"))
    drawing_paths, picture_paths = set(), set()
    for record, wrapper in zip(records, original_wrappers):
        drawing = selected_root
        for index in record["selected_drawing_path"]:
            drawing = drawing[index]
        picture = selected_root
        for index in record["selected_picture_path"]:
            picture = picture[index]
        assert drawing.tag == W + "drawing"
        assert picture.tag == A + "blip" and picture in tuple(drawing.iter())
        original_drawing = wrapper[0][0]
        for node in (drawing, original_drawing):
            payload = [(n.tag, len(n), sorted(n.attrib.items()), n.text or "", n.tail or "") for n in node.iter()]
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True,
                                              separators=(",", ":")).encode()).hexdigest()
            assert digest == record["selected_drawing_sha256"]
        drawing_paths.add(tuple(record["selected_drawing_path"]))
        picture_paths.add(tuple(record["selected_picture_path"]))
    assert len(drawing_paths) == len(picture_paths) == 2
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["geometry", "remove_picture"])
def test_passive_closure_cannot_silently_change_selected_occurrence(tmp_path, monkeypatch, change):
    path = source(tmp_path, divergent=True, shared_outside=False)
    passive = compatibility.passive_docx

    def changed_passive(selected):
        values = parts(passive(selected))
        root = ET.fromstring(values["word/document.xml"])
        picture = next(root.iter(A + "blip"))
        if change == "remove_picture":
            picture.getparent().remove(picture)
        else:
            drawing = picture
            while drawing.tag != W + "drawing":
                drawing = drawing.getparent()
            next(drawing.iter(qn("wp:extent"))).set("cx", "2100000")
        values["word/document.xml"] = ET.tostring(root)
        return package(values)

    monkeypatch.setattr(compatibility, "passive_docx", changed_passive)
    with pytest.raises(compatibility.CompatibilityError, match="geometry/markup changed"):
        compatibility.derive_compatibility_view(path.read_bytes())


@pytest.mark.parametrize('payload', ['del', 'ins', 'moveFrom', 'moveTo', 'fldSimple', 'instrText', 'foreign', 'attribute'])
def test_raw_candidate_outer_payload_is_rejected_before_current_view(tmp_path, monkeypatch, payload):
    path = source(tmp_path, divergent=True, shared_outside=False)
    values = parts(path.read_bytes()); root = ET.fromstring(values['word/document.xml'])
    unit = root.find(W+'body')[0]
    if payload == 'attribute': unit.set('unknown', 'synthetic')
    elif payload == 'foreign': ET.SubElement(unit, '{urn:synthetic}payload')
    else:
        node = ET.SubElement(unit, W+payload)
        ET.SubElement(ET.SubElement(node, W+'r'), W+'t').text = 'Synthetic hidden payload'
    values['word/document.xml'] = ET.tostring(root)
    monkeypatch.setattr(compatibility, 'inspect_docx', lambda *_: pytest.fail('Inspector ran before raw closure rejection'))
    with pytest.raises(compatibility.CompatibilityError): compatibility.derive_compatibility_view(package(values))


@pytest.mark.parametrize('mode', ['deleted-text', 'moved-text', 'deleted-paragraph', 'moved-paragraph', 'deleted-section'])
def test_preceding_revision_cannot_shift_candidate_occurrence_binding(tmp_path, mode):
    path = source(tmp_path, divergent=True, shared_outside=False)
    values = parts(path.read_bytes()); root = ET.fromstring(values['word/document.xml']); body=root.find(W+'body')
    candidate = body[0]
    if mode in ('deleted-paragraph', 'moved-paragraph'):
        previous = ET.Element(W+('del' if mode == 'deleted-paragraph' else 'moveFrom'))
        ET.SubElement(previous,W+'p')
    else:
        previous = ET.Element(W+'p')
        change = ET.SubElement(previous,W+('moveFrom' if mode == 'moved-text' else 'del'))
        if mode == 'deleted-section': ET.SubElement(change,W+'sectPr')
        else: ET.SubElement(ET.SubElement(change,W+'r'),W+'delText').text = 'Synthetic previous revision'
    body.insert(0,previous); values['word/document.xml']=ET.tostring(root); before=package(values)
    if mode in ('deleted-paragraph','moved-paragraph','deleted-section'):
        with pytest.raises(ValueError): compatibility.derive_compatibility_view(before)
    else:
        view=compatibility.derive_compatibility_view(before)
        receipt=json.loads(view.receipt_bytes)
        assert receipt['resolutions'][0]['position']==2
        assert receipt['raw_units'][0]['position']==2
        assert receipt['raw_units'][0]['raw_subtree_sha256']==compatibility._subtree_digest(candidate)
        assert next(i for i in view.original_inspection.items if i.id==receipt['resolutions'][0]['original_item_id']).position==2


@pytest.mark.parametrize('crop', [{'l':'50000','r':'50000'}, {'t':'60000','b':'50000'}])
def test_wrapped_picture_crop_must_remain_nonempty(tmp_path,crop):
    def crop_picture(document,slot,wrapper,fallback):
        fill=next(wrapper[0].iter(qn('pic:blipFill')))
        fill.insert(1,ET.Element(A+'srcRect',crop))
    path=source(tmp_path,divergent=True,mutation=crop_picture)
    with pytest.raises(compatibility.CompatibilityError,match='crop'):
        compatibility.derive_compatibility_view(path.read_bytes())


def static_source(tmp_path, *, shared_outside=False):
    from test_monthly_report_static_siblings import modern, legacy, V
    path=source(tmp_path,divergent=True,shared_outside=shared_outside)
    values=parts(path.read_bytes()); root=ET.fromstring(values['word/document.xml']); unit=root.find(W+'body')[0]
    ordinary=[child for run in unit for child in run if child.tag==W+'drawing']
    assert len(ordinary)==3
    for index,drawing in enumerate(ordinary):
        paragraphs=tuple(tuple(t.text or '' for t in paragraph.iter(W+'t')) for paragraph in drawing.iter(W+'p'))
        wrapper=ET.Element(MC+'AlternateContent',nsmap={'wps':compatibility.WPS[1:-1]})
        selected=modern('horizontal-textframe',paragraphs);selected.set('Requires','wps')
        wrapper.append(selected);wrapper.append(legacy('horizontal-textframe',declaration=index==0,paragraphs=paragraphs))
        drawing.getparent().replace(drawing,wrapper)
    wrapper=ET.SubElement(ET.SubElement(unit,W+'r'),MC+'AlternateContent',nsmap={'wps':compatibility.WPS[1:-1]})
    selected=modern('closed-5point-polygon');selected.set('Requires','wps')
    wrapper.append(selected);wrapper.append(legacy('closed-5point-polygon'))
    next(wrapper[0].iter(A+'srgbClr')).set('val','547e7e')
    next(wrapper[1].iter(V+'shape')).set('fillcolor','#547e7e')
    values['word/document.xml']=ET.tostring(root);path.write_bytes(package(values));return path


def test_integrated_static_siblings_have_separate_audit_no_image_role_authority(tmp_path):
    path=static_source(tmp_path);before=path.read_bytes();view=compatibility.derive_compatibility_view(before)
    receipt=json.loads(view.receipt_bytes)
    assert len(receipt['static_resolutions'])==4 and len(receipt['resolutions'])==1
    assert receipt['static_definitions']['original']['reference_count']==3
    assert len(receipt['static_definitions']['original']['definitions'])==1
    assert receipt['static_definitions']['rendition']['reference_count']==0
    assert receipt['static_definitions']['rendition']['definitions']==[]
    output=parts(view.rendition_bytes)['word/document.xml']
    assert b'gfxdata' not in output and b'AlternateContent' not in output
    for record in receipt['static_resolutions']:
        assert 'selected_picture_path' not in record
        assert all('media_part' not in branch and 'branch_sha256' in branch and 'node_count' in branch for branch in record['branches'])
    assert len([i for i in view.rendition_inspection.items if i.kind=='image'])==1
    assert any(i.note=='Native cover title and artwork' for i in view.rendition_inspection.items)
    assert path.read_bytes()==before


@pytest.mark.parametrize('change',['unknown','text','extra-paragraph','definition-conflict','missing-derivative-definition'])
def test_integrated_static_whole_unit_and_dependency_negatives(tmp_path,change,monkeypatch):
    from test_monthly_report_static_siblings import V
    path=static_source(tmp_path);values=parts(path.read_bytes());root=ET.fromstring(values['word/document.xml'])
    wrapper=next(root.iter(MC+'AlternateContent'))
    if change=='unknown': wrapper[1][0].set('unknown','synthetic')
    elif change=='text': next(wrapper[1].iter(W+'t')).text='Unrelated synthetic content'
    elif change=='extra-paragraph': next(wrapper[1].iter(W+'txbxContent')).append(ET.Element(W+'p'))
    elif change=='definition-conflict': next(root.iter(V+'shapetype')).set('path','m0,0l1,1xe')
    else:
        # A non-candidate retained VML reference loses its only declaration
        # when candidate Fallback is removed. Never invent/move a declaration.
        outside=ET.SubElement(root.find(W+'body'),W+'p')
        shape=ET.SubElement(ET.SubElement(ET.SubElement(outside,W+'r'),W+'pict'),V+'shape',type='#_x0000_t202')
        shape.set('id','Synthetic retained reference')
    values['word/document.xml']=ET.tostring(root)
    with pytest.raises(ValueError): compatibility.derive_compatibility_view(package(values))
