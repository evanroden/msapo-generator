"""Synthetic MR-003 complex-cover boundary and existing recovery controls.

No client documents, named accounts or external assets enter this fixture.
"""
from io import BytesIO
from hashlib import sha256

from docx import Document
from docx.oxml import parse_xml
from docx.shared import Inches
from PIL import Image
import pytest

from app.monthly_report_import import ImportMapping, inspect_docx, map_items
from app.monthly_report_sections import build_section_import, section_reviews
from app.monthly_report_start_import import cover_photo_candidates
from test_monthly_report_floating_paragraph_review import _frame


def _png(size, color):
    data = BytesIO()
    Image.new("RGB", size, color).save(data, format="PNG")
    return data.getvalue()


def _grouped_legacy_cover():
    return parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml">'
        '<w:pict><v:group id="synthetic-cover-group" style="width:220pt;height:60pt">'
        '<v:rect id="synthetic-decorative-band" style="width:220pt;height:22pt" '
        'fillcolor="#082b23" stroked="f"/>'
        '<v:shape id="synthetic-floating-owner" style="width:180pt;height:35pt">'
        '<v:textbox><w:txbxContent><w:p><w:r>'
        '<w:t>Synthetic floating preparer line</w:t>'
        '</w:r></w:p></w:txbxContent></v:textbox>'
        '</v:shape></v:group></w:pict></w:r>'
    )


def _source(tmp_path, *, complex_cover):
    document = Document()
    document.add_paragraph("Synthetic Regional Community Health Hospital")
    document.add_paragraph("November 2026")
    document.add_paragraph("Prepared by: Synthetic Operator")
    if complex_cover:
        # One unambiguous ordinary cover line alongside independently placed
        # text and geometry; no drawing should be mistaken for that line.
        paragraph = document.add_paragraph("Synthetic outside cover context.")
        paragraph._p.append(_frame("Synthetic floating Word title", "modern"))
        paragraph = document.add_paragraph()
        paragraph._p.append(_grouped_legacy_cover())
        # The marks have identical source bytes but distinct positions.
        logo = _png((70, 35), "green")
        document.add_picture(BytesIO(logo), width=Inches(0.8))
        document.add_picture(BytesIO(logo), width=Inches(0.8))
    # A separate, substantial photograph is never the unsupported object
    # and must retain its photo/mark distinction through a failed inspection.
    photo = _png((720, 480), "blue")
    document.add_picture(BytesIO(photo), width=Inches(4))
    document.add_heading("Monthly Activity Summary", level=1)
    document.add_paragraph("Synthetic validated body inspection completed.")
    path = tmp_path / ("complex-cover.docx" if complex_cover else "plain-cover.docx")
    document.save(path)
    return path


@pytest.mark.parametrize("complex_cover", [False, True], ids=["control", "floating-objects"])
def test_synthetic_cover_inventory_and_unchanged_body(tmp_path, complex_cover):
    path = _source(tmp_path, complex_cover=complex_cover)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    sections = {s.key: s for s in section_reviews(inspection)}
    body = next(i for i in sections["activity"].items
                if i.kind == "text" and i.text == "Synthetic validated body inspection completed.")
    assert body.section == "activity"
    assert inspection.sha256 == sha256(original).hexdigest()
    assert path.read_bytes() == original

    cover = sections["cover"]
    blockers = [i for i in cover.items if i.kind == "unsupported"]
    assert bool(blockers) is complex_cover
    images = [i for i in cover.items if i.kind == "image"]
    assert len(images) == (3 if complex_cover else 1)
    photo = cover_photo_candidates(inspection.items)
    assert len(photo) == 1 and photo[0].image_width == 720
    assert photo[0].image_height == 480
    if complex_cover:
        small = [i for i in images if i.image_width == 70]
        assert len(small) == 2 and small[0].image_digest == small[1].image_digest
        assert small[0].id != small[1].id
        assert any("floating Word text box" in item.note and
                   "DrawingML shape/group" in item.note for item in blockers)
        assert any("grouped VML drawing" in item.note for item in blockers)
        assert all("Word section 1" in item.note and "body element" in item.note
                   and "PNG/JPEG" in item.note for item in blockers)
        assert all(item.position > 0 for item in blockers)
    else:
        # The no-floating-content control keeps the same native source
        # classification and ordinary editable body destination.
        mapped = map_items(path, inspection, (ImportMapping(body.id, "activity_summary"),))
        assert mapped.blocks[0].text == body.text


def test_unsupported_cover_cannot_erase_corrections_on_failure_then_explicit_omit(tmp_path):
    path = _source(tmp_path, complex_cover=True)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    sections = {s.key: s for s in section_reviews(inspection)}
    body = next(i for i in sections["activity"].items
                if i.kind == "text" and i.text == "Synthetic validated body inspection completed.")
    corrected = "Synthetic manual correction to valid body inspection."
    cover_plan = {"key": "cover", "target": "cover", "approved": True,
                  "omit": False, "selected": [], "unsupported_reviewed": True}
    body_plan = {"key": "activity", "target": "activity", "approved": True,
                 "selected": [body.id], "texts": {body.id: corrected}}
    with pytest.raises(ValueError, match="Unread cover artwork"):
        build_section_import(path, inspection, (cover_plan, body_plan))
    assert body_plan["texts"][body.id] == corrected
    assert path.read_bytes() == original

    # Explicitly retaining a saved/independent cover is an existing recovery
    # action, not an assertion that the failed source drawing was extracted.
    cover_plan["omit"] = True
    mapped, mappings = build_section_import(path, inspection, (cover_plan, body_plan))
    assert any(block.key == "activity_summary" and block.text == corrected
               for block in mapped.blocks)
    assert any(mapping.item_id == body.id for mapping in mappings)
    assert path.read_bytes() == original
    assert inspect_docx(path) == inspection
