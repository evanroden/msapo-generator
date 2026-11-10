"""A secondary Starting Report must not silently drop an undecided cover photo.

Synthetic cover marks, two plausible photo occurrences, and later section art.
No client originals, branding assets, or private screenshots are used.
"""

from dataclasses import replace
from io import BytesIO

from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
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
from tests.conftest import requires_libreoffice


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


def _near(value, target, tolerance=15):
    return all(abs(a - b) <= tolerance for a, b in zip(value, target))


def _cover_photo_counts(raw):
    """Inspect decoded pixels, not media hashes (template preview re-encodes)."""
    document = Document(BytesIO(raw))
    chosen = competing = 0
    for picture in document.element.iter(qn("pic:pic")):
        blip = next((node for node in picture.iter(qn("a:blip"))
                     if node.get(qn("r:embed"))), None)
        if blip is None:
            continue
        media = document.part.related_parts[blip.get(qn("r:embed"))].blob
        with Image.open(BytesIO(media)) as opened:
            pixels = opened.convert("RGB")
            center = pixels.getpixel((int(pixels.width * .57), int(pixels.height * .5)))
            corner = pixels.getpixel((int(pixels.width * .05), int(pixels.height * .05)))
        chosen += _near(center, (23, 63, 73)) and _near(corner, (218, 231, 237))
        competing += _near(center, (175, 66, 105)) and _near(corner, (175, 66, 105))
    return chosen, competing


def _assert_selected_only(raw):
    assert _cover_photo_counts(raw) == (1, 0), (
        "The chosen circle photograph must appear once and the magenta "
        "alternate must not appear.")


def _assert_real_pdf_photo(raw):
    import pymupdf as fitz

    circles = []
    alternate_found = False
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        # Both the generated report and the live cover preview place the
        # photograph on the cover; later maintenance pages are irrelevant.
        for page in list(pdf)[:3]:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixels = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            points = []
            for y in range(0, pixels.height, 2):
                for x in range(0, pixels.width, 2):
                    value = pixels.getpixel((x, y))
                    if _near(value, (23, 63, 73), 12):
                        points.append((x, y))
                    if _near(value, (175, 66, 105), 10):
                        alternate_found = True
            if points:
                circles.append(points)
    assert circles, "The chosen photograph must be visible in the rendered PDF."
    assert not alternate_found, "The unselected magenta photograph reached the PDF."
    for points in circles:
        width = max(x for x, _ in points) - min(x for x, _ in points) + 1
        height = max(y for _, y in points) - min(y for _, y in points) + 1
        assert abs(width - height) <= 4, "The selected circle is stretched in the PDF."


@requires_libreoffice
def test_selected_alternate_photo_reaches_live_preview_and_generated_word_pdf(monkeypatch, tmp_path):
    from app import pdf_converter
    from app.monthly_report_asset_review import approve_all_assets
    from app.monthly_report_docx import generate_report
    from app.monthly_report_preview import preview_section, section_preview_docx

    path, _ = source(tmp_path)
    original = path.read_bytes()
    app = setup_app(monkeypatch, tmp_path, path, alternate=True)
    next(b for b in app.button if b.label == "Choose picture 1").click().run()
    draft = save_start(app)
    loader = lambda ref: library.read_asset(draft.profile.contract, draft.profile.key, ref)
    # The Generate action requires explicit picture review and completed
    # sections. Keep the imported maintenance section; leave unfinished
    # sections out, as an editor would before publishing.
    reviewed = replace(
        draft,
        sections=tuple(replace(section, included=section.key == "maintenance")
                       for section in draft.sections),
        blocks=tuple(approve_all_assets(block) if block.asset_hashes else block
                     for block in draft.blocks),
    )
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    preview_docx = section_preview_docx(reviewed, "cover", loader)
    _assert_selected_only(preview_docx)
    preview_pdf = preview_section(reviewed, "cover", loader)
    _assert_real_pdf_photo(preview_pdf.pdf)

    package = generate_report(reviewed, acknowledged_fingerprint=reviewed.fingerprint,
                              asset_loader=loader)
    assert package.pdf and not package.pdf_error
    _assert_selected_only(package.docx)
    _assert_real_pdf_photo(package.pdf)
    assert path.read_bytes() == original


def test_pinned_starting_report_native_design_uses_exact_selected_photo(monkeypatch, tmp_path):
    """Installing this source as a site design makes the native path reachable."""
    from app import monthly_report_designs as designs
    from app.monthly_report_docx import _build_docx
    from app.monthly_report_preview import section_preview_docx
    from test_cover_unchanged_photo_geometry import photo_geometry

    path, photograph = source(tmp_path)
    original = path.read_bytes()
    app = setup_app(monkeypatch, tmp_path, path, alternate=True)
    next(b for b in app.button if b.label == "Choose picture 1").click().run()
    draft = save_start(app)
    loader = lambda ref: library.read_asset(draft.profile.contract, draft.profile.key, ref)
    assert designs.source_for(draft.profile) is None
    pinned = designs.install(path, draft.profile, actor="Synthetic Editor", expected_revision=0)
    assert designs.source_for(pinned).read_bytes() == original
    native_draft = replace(draft, profile=pinned)

    preview = section_preview_docx(native_draft, "cover", loader)
    word = _build_docx(native_draft, asset_loader=loader)
    for output in (preview, word):
        # A pinned native design keeps the Starting Report's other photograph
        # as fixed artwork: choosing the cover photo does not authorize editing
        # an independent sibling (tests/test_cover_photo_occurrence_and_extent.py).
        # The chosen photograph appears exactly once and is not re-emitted.
        assert _cover_photo_counts(output) == (1, 1)
        crop, frame = photo_geometry(output, photograph)
        assert crop["t"] == pytest.approx(.10, abs=.00001)
        assert crop["b"] == pytest.approx(.15, abs=.00001)
        assert frame == (Inches(6), Inches(3))
    assert path.read_bytes() == original
