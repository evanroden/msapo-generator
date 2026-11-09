"""A secondary Starting Report must not silently drop an undecided cover photo.

Synthetic cover marks, two plausible photo occurrences, and later section art.
No client originals, branding assets, or private screenshots are used.
"""

from io import BytesIO

from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.shared import Inches
from PIL import Image, ImageDraw
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_sections import section_reviews
from app.monthly_report_start_import import (
    analyze_starting_report, automatic_section_plans, build_starting_import,
    cover_photo_candidates, cover_photo_choice_pending, suggested_cover_photo,
)
from app.monthly_report_setup import new_month_draft
from test_monthly_report_start_import import PERIOD, save_start, start_app


def raster(size, *, color, circle=False, transparent=False):
    image = Image.new("RGBA" if transparent else "RGB", size,
                      (0, 0, 0, 0) if transparent else color)
    if circle:
        ImageDraw.Draw(image).ellipse((310, 140, 510, 340), fill=(23, 63, 73))
    elif transparent:
        ImageDraw.Draw(image).rectangle((35, 20, 210, 110), fill=color)
    data = BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


def source(tmp_path):
    profile = synthetic_profiles()[0]
    doc = Document()
    doc.add_paragraph(profile.facilities[0].title)
    doc.add_paragraph("September 2026")
    for role, color in (("ENFRA company logo", (40, 90, 160, 255)),
                        ("Synthetic client logo", (140, 65, 110, 255))):
        mark = doc.add_picture(BytesIO(raster((420, 140), color=color, transparent=True)),
                               width=Inches(2))
        mark._inline.docPr.set("descr", role)
    # The alternate page is a cover-photo panel, not a maintenance illustration.
    doc.add_section(WD_SECTION.NEW_PAGE)
    photograph = raster((720, 480), color=(218, 231, 237), circle=True)
    selected = doc.add_picture(BytesIO(photograph), width=Inches(6), height=Inches(3))
    crop = OxmlElement("a:srcRect")
    crop.attrib.update({"t": "10000", "b": "15000"})
    selected._inline.graphic.graphicData.pic.blipFill.blip.addnext(crop)
    # Same-sized plausible artwork makes a size-only automatic choice unsafe.
    doc.add_picture(BytesIO(raster((720, 480), color=(175, 66, 105))),
                    width=Inches(6), height=Inches(3))
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_heading("5 Maintenance Schedule / In-House Maintenance", 1)
    table = doc.add_table(rows=2, cols=5)
    for row, values in zip(table.rows, (
            ("WO #", "Finish Date", "Area", "Task Code-Description", "Tag #"),
            ("SYN-17", "09/15/2026", "Synthetic plant", "Scheduled inspection", "SYN-PUMP"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    doc.add_picture(BytesIO(raster((500, 300), color=(100, 130, 210))),
                    width=Inches(3))
    doc.add_heading("7 Equipment Performance Issues", 1)
    doc.add_paragraph("September 2026 synthetic equipment concern.")
    path = tmp_path / "synthetic-alternate-cover.docx"
    doc.save(path)
    return path, photograph


def inspected(path):
    inspection = inspect_docx(path)
    cover = next(s for s in section_reviews(inspection) if s.key == "cover")
    candidates = cover_photo_candidates(cover.items)
    # Both photographs are eligible; company/client marks and the later
    # maintenance illustration must never be presented as a cover choice.
    assert len(candidates) == 2
    assert suggested_cover_photo(cover.items) is None
    assert all(item.suggested_slot not in ("brand_logo", "client_logo") for item in candidates)
    analysis = analyze_starting_report(inspection, synthetic_profiles()[0], PERIOD)
    assert analysis.site_relation == "same"
    plans = automatic_section_plans(inspection, analysis)
    return inspection, cover, candidates, plans


def test_undecided_cover_blocks_even_when_other_sections_are_importable(tmp_path):
    path, _ = source(tmp_path)
    original = path.read_bytes()
    inspection, cover, candidates, plans = inspected(path)
    assert cover_photo_choice_pending(cover.items, plans["cover"])
    assert not any(plans["cover"]["destinations"].get(i.id) == "cover_photo" for i in candidates)
    with pytest.raises(ValueError, match="Choose a cover photograph"):
        build_starting_import(path, inspection, tuple(plans.values()))
    assert path.read_bytes() == original


def test_selected_occurrence_preserves_photo_role_and_original(tmp_path):
    path, photograph = source(tmp_path)
    original = path.read_bytes()
    inspection, cover, candidates, plans = inspected(path)
    chosen = candidates[0]
    plan = plans["cover"]
    plan["selected"].append(chosen.id)
    plan["destinations"][chosen.id] = "cover_photo"
    plan["cover_picture_id"] = chosen.id
    plan["cover_photo_source_ids"] = tuple(i.id for i in candidates)
    assert not cover_photo_choice_pending(cover.items, plan)
    mapped, mappings = build_starting_import(path, inspection, tuple(plans.values()))
    block = next(b for b in mapped.blocks if b.key == "cover_photo")
    assert len(block.asset_hashes) == 1
    assert f"docx:{inspection.sha256}:{chosen.id}" in block.references
    assert chosen.id in {m.item_id for m in mappings if m.slot == "cover_photo"}
    assert candidates[1].id not in {m.item_id for m in mappings if m.slot == "cover_photo"}
    assert any(table.rows for block in mapped.blocks if block.key == "service_calls"
               for table in block.extra_tables)
    assert path.read_bytes() == original


def test_explicit_no_photo_is_not_silently_resurrected(tmp_path):
    path, _ = source(tmp_path)
    inspection, cover, candidates, plans = inspected(path)
    plan = plans["cover"]
    plan.update(cover_photo_omitted=True,
                cover_photo_source_ids=tuple(i.id for i in candidates),
                cover_picture_id="")
    assert not cover_photo_choice_pending(cover.items, plan)
    mapped, _ = build_starting_import(path, inspection, tuple(plans.values()))
    photo = next(b for b in mapped.blocks if b.key == "cover_photo")
    assert photo.source == "Omit" and not photo.asset_hashes


def setup_app(monkeypatch, tmp_path, path, *, alternate):
    if not alternate:
        return start_app(monkeypatch, tmp_path, path)
    from app import monthly_report_section_ui as ui
    profile = synthetic_profiles()[0]
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    library.save_profile(profile, expected_revision=0,
                         actor="Synthetic Editor", confirmed=True)
    upload = BytesIO(path.read_bytes())
    upload.name, upload.size = path.name, len(upload.getvalue())
    native = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw:
                        upload if label == "Starting report" else native(label, *a, **kw))
    app = AppTest.from_string("""
from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
profile = synthetic_profiles()[0]
state = library.load_profile(profile.contract, profile.key)
render_section_setup(profile.contract, ReportPeriod(2026, 9), "Synthetic Editor",
                     _field, state=state, identity=profile)
""", default_timeout=45).run()
    assert not app.exception
    return app


@pytest.mark.parametrize("alternate", [False, True], ids=("primary", "alternate"))
def test_first_photo_choice_survives_continue_reopen_and_next_month(monkeypatch, tmp_path, alternate):
    path, photograph = source(tmp_path)
    original = path.read_bytes()
    app = setup_app(monkeypatch, tmp_path, path, alternate=alternate)
    button = lambda: next(b for b in app.button if b.label == "Continue to this month’s updates")
    assert button().disabled
    assert any("Choose a cover photograph" in x.value for x in app.info)
    next(b for b in app.button if b.label == "Choose picture 1").click().run()
    assert not app.exception
    assert not button().disabled
    draft = save_start(app)
    photo = next(b for b in draft.blocks if b.key == "cover_photo")
    assert len(photo.asset_hashes) == 1 and photo.source != "Omit"
    assert library.read_asset(draft.profile.contract, draft.profile.key, photo.asset_hashes[0])
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original
    reloaded = library.load_imported_draft(draft.profile.contract, draft.profile.key)
    assert next(b for b in reloaded.blocks if b.key == "cover_photo") == photo
    next_month = new_month_draft(reloaded, ReportPeriod(2026, 10))
    assert next(b for b in next_month.blocks if b.key == "cover_photo").asset_hashes == photo.asset_hashes
    assert path.read_bytes() == original


from tests.conftest import requires_libreoffice


@requires_libreoffice
def test_selected_alternate_photo_has_matching_preview_word_and_actual_pdf_crop(monkeypatch, tmp_path):
    import fitz
    from app import pdf_converter
    from app.monthly_report_native_layout import build_native_docx
    from app.monthly_report_preview import section_preview_docx
    from app.monthly_report_render_compat import rendering_docx
    from test_cover_unchanged_photo_geometry import photo_geometry

    path, photograph = source(tmp_path)
    original = path.read_bytes()
    app = setup_app(monkeypatch, tmp_path, path, alternate=True)
    next(b for b in app.button if b.label == "Choose picture 1").click().run()
    draft = save_start(app)
    photo = next(b for b in draft.blocks if b.key == "cover_photo")
    loader = lambda ref: library.read_asset(draft.profile.contract, draft.profile.key, ref)
    selected = loader(photo.asset_hashes[0])
    word = build_native_docx(draft, path, asset_loader=loader)
    preview = section_preview_docx(draft, "cover", loader)
    crop, frame = photo_geometry(word, selected)
    preview_crop, preview_frame = photo_geometry(preview, selected)
    assert crop == preview_crop
    assert frame == preview_frame
    assert crop["t"] == pytest.approx(.10, abs=.00001)
    assert crop["b"] == pytest.approx(.15, abs=.00001)
    assert 720 * (1 - crop["l"] - crop["r"]) / (480 * (1 - crop["t"] - crop["b"])) == pytest.approx(frame[0] / frame[1], rel=.001)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    output = tmp_path / "synthetic-preview.docx"
    output.write_bytes(rendering_docx(word))
    pdf_path = pdf_converter.convert_to_pdf(output)
    found = False
    with fitz.open(pdf_path) as pdf:
        for page in pdf:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            pixels = [(x, y) for y in range(image.height) for x in range(image.width)
                      if all(abs(channel - target) < 5 for channel, target
                             in zip(image.getpixel((x, y)), (23, 63, 73)))]
            if pixels:
                found = True
                width = max(x for x, _ in pixels) - min(x for x, _ in pixels) + 1
                height = max(y for _, y in pixels) - min(y for _, y in pixels) + 1
                assert abs(width - height) <= 4
    assert found, "Selected synthetic cover photograph must appear in the real PDF"
    assert path.read_bytes() == original
