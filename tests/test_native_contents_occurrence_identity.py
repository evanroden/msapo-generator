"""Contents furniture retains one proved occurrence; editable prose stays editable."""
from dataclasses import replace

import pytest

from app.monthly_report_compatibility_view import derive_compatibility_view, CompatibilityError, _bind
from app.monthly_report_import import ImportItem
from test_monthly_report_source_frame_logo_role import source
from test_monthly_report_source_view_lifecycle import _add_contents


@pytest.mark.parametrize('static', [False, True])
def test_resolved_contents_stays_native_furniture_without_duplicate_editable_text(tmp_path, static):
    if static:
        from test_monthly_report_source_view_closure import static_source
        path = static_source(tmp_path, shared_outside=True)
    else:
        path = source(tmp_path, divergent=True)
    _add_contents(path)
    original = path.read_bytes()
    view = derive_compatibility_view(original)
    furniture = [i for i in view.rendition_inspection.items
                 if i.kind == 'native_layout' and i.note in
                 ('Native contents text frames', 'Native contents notice and artwork')]
    assert len(furniture) == 1
    item = furniture[0]
    assert 'ENFRA' in item.text and 'Section 1: Work Summary' in item.text
    assert not any(i.kind == 'text' and i.part == item.part and i.position == item.position
                   and i.word_section == item.word_section and i.text == item.text
                   for i in view.rendition_inspection.items)
    assert any(i.kind == 'image' and i.position == item.position
               for i in view.rendition_inspection.items)
    assert len([b for b in view.bindings if b.status == 'resolved']) == 2
    assert len({b.rendition_id for b in view.bindings if b.rendition_id}) == len(view.rendition_inspection.items)
    assert path.read_bytes() == original


def test_strict_binding_still_refuses_arbitrary_extra_rendition_text(tmp_path):
    view = derive_compatibility_view(source(tmp_path, divergent=True).read_bytes())
    extra = ImportItem('injected-unbound-text', 'text', 'word/document.xml', 999, 1,
                       text='Unproved additional report prose')
    changed = replace(view.rendition_inspection, items=(*view.rendition_inspection.items, extra))
    candidates = {b.original_id for b in view.bindings if b.status == 'resolved'}
    with pytest.raises(CompatibilityError, match='unbound new rendition occurrence'):
        _bind(view.original_inspection, changed, candidates)
