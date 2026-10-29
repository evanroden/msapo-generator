"""Mixed-size MBCx attachment geometry with synthetic corner sentinels.

No client documents or real inspection data are used. These checks verify
PDF rasterization separately from the actual Word-derived PDF renderer.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest
from docx import Document
from PIL import Image

from conftest import requires_libreoffice
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import pdf_converter
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import generate_report
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles,
)
from app.monthly_report_section_uploads import prepare_section_pages
from app.monthly_report_source_scope import correct_scope


# Page 3 and 4 have rotated page dictionaries, not just landscape artwork.
GEOMETRIES = (
    (612, 792, 0),
    (792, 612, 0),
    (612, 792, 90),
    (612, 792, 270),
    (760, 330, 0),
)
CORNER_COLORS = (
    (0.94, 0.06, 0.06),  # red
    (0.06, 0.90, 0.06),  # green
    (0.06, 0.12, 0.94),  # blue
    (0.95, 0.83, 0.05),  # yellow
)
MARKERS = {"red", "green", "blue", "yellow"}


def synthetic_mixed_pdf():
    with fitz.open() as document:
        for number, (width, height, rotation) in enumerate(GEOMETRIES, 1):
            page = document.new_page(width=width, height=height)
            corners = (
                fitz.Rect(10, 10, 44, 44),
                fitz.Rect(width - 44, 10, width - 10, 44),
                fitz.Rect(10, height - 44, 44, height - 10),
                fitz.Rect(width - 44, height - 44, width - 10, height - 10),
            )
            for rectangle, rgb in zip(corners, CORNER_COLORS):
                page.draw_rect(rectangle, color=None, fill=rgb, overlay=True)
            page.insert_text(
                (70, 80),
                f"Synthetic equipment inspection page {number}. "
                "Demonstration unit checked and recorded.",
                fontsize=11,
            )
            if rotation:
                page.set_rotation(rotation)
        return document.tobytes()


def visible_markers(image):
    """Find large unambiguous corner squares despite PDF print antialiasing."""
    picture = image.convert("RGB")
    pixels = picture.load()
    found = set()
    stride = max(1, min(picture.size) // 450)
    for y in range(0, picture.height, stride):
        for x in range(0, picture.width, stride):
            red, green, blue = pixels[x, y]
            if red > 170 and green < 100 and blue < 100:
                found.add("red")
            elif green > 140 and red < 100 and blue < 110:
                found.add("green")
            elif blue > 150 and red < 100 and green < 125:
                found.add("blue")
            elif red > 170 and green > 150 and blue < 100:
                found.add("yellow")
            if found == MARKERS:
                return found
    return found


def fixture_source(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "report-store"))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    original = synthetic_mixed_pdf()
    content, _ = sources.ingest(profile, "synthetic-geometry-mbcx.pdf", original)
    assert len(content.source.page_texts) == len(GEOMETRIES)
    captions = tuple((n, f"Geometry attachment {n}") for n in range(1, len(GEOMETRIES) + 1))
    source = replace(content.source, captions=captions)
    source = replace(source, client_page_reviews=tuple(
        (n, page_fingerprint(source, n)) for n in range(1, len(GEOMETRIES) + 1)
    ))
    # Per-page visual approval is not approval of the source's exact site.
    # The fixture covers only this actual synthetic profile facility.
    source = correct_scope(source, profile, (profile.facilities[0].key,))
    content = replace(content, source=source)
    return profile, content, original


def test_mixed_pdf_rotations_and_edge_sentinels_survive_preparation(tmp_path, monkeypatch):
    profile, content, original = fixture_source(tmp_path, monkeypatch)
    before = sha256(original).hexdigest()
    with fitz.open(stream=original, filetype="pdf") as pdf:
        for number in range(1, len(GEOMETRIES) + 1):
            page = pdf[number - 1]
            assert page.rotation == GEOMETRIES[number - 1][2]
            image = sources.page_image(profile, content, number)
            assert image.width > 0 and image.height > 0
            assert abs(image.width / image.height - page.rect.width / page.rect.height) < 0.015
            assert visible_markers(Image.open(BytesIO(image.data))) == MARKERS
            cached = sources.page_image(profile, content, number)
            assert cached.data == image.data
    assert sha256(sources.source_bytes(profile, content.source)).hexdigest() == before


def test_giant_page_refuses_rasterization_without_touching_original(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "report-store"))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    with fitz.open() as doc:
        page = doc.new_page(width=8000, height=8000)
        page.insert_text((90, 90), "Synthetic equipment inspection for oversized media.")
        raw = doc.tobytes()
    content, _ = sources.ingest(profile, "synthetic-oversize.pdf", raw)
    with pytest.raises(ValueError, match="too large to rasterize safely"):
        sources.page_image(profile, content, 1)
    assert sources.source_bytes(profile, content.source) == raw


@requires_libreoffice
def test_mixed_mbcx_pages_keep_all_corners_and_order_in_final_word_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    profile, content, original = fixture_source(tmp_path, monkeypatch)
    source_sha = sha256(original).hexdigest()
    prepared = prepare_section_pages(profile, (content,), "mbcx_report", {})
    assert set(prepared) == {"mbcx_report"}
    page_block = prepared["mbcx_report"]
    assert len(page_block.asset_hashes) == len(GEOMETRIES)
    assert tuple(page_block.asset_captions) == tuple(
        f"Geometry attachment {n}" for n in range(1, len(GEOMETRIES) + 1))
    report_sections = tuple(
        s for s in default_sections() if s.key in ("mbcx", "issues")
    )
    following = "Synthetic following-section issue record for geometry validation."
    draft = ReportDraft(
        profile, ReportPeriod(2026, 10), "Synthetic Reviewer",
        report_sections,
        (page_block, ResolvedBlock("equipment_issues", "This month", text=following)),
        synthetic=True, sources=(content.source,),
    )

    def loader(reference):
        return library.read_asset(profile.contract, profile.key, reference)

    package = generate_report(
        draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader,
    )
    assert package.docx and package.pdf, package.pdf_error
    assert package.docx.startswith(b"PK") and package.pdf.startswith(b"%PDF-")
    assert sha256(sources.source_bytes(profile, content.source)).hexdigest() == source_sha

    # Every DOCX picture has its own full-width/height scaling, with no crop.
    shapes = list(Document(BytesIO(package.docx)).inline_shapes)
    assert len(shapes) >= len(GEOMETRIES)
    for shape, reference in zip(shapes[-len(GEOMETRIES):], page_block.asset_hashes):
        with Image.open(BytesIO(loader(reference))) as raster:
            assert abs(shape.width / shape.height - raster.width / raster.height) < 0.02

    with fitz.open(stream=package.pdf, filetype="pdf") as output:
        captions = []
        for number in range(1, len(GEOMETRIES) + 1):
            label = f"Geometry attachment {number}"
            matches = [
                index for index, page in enumerate(output)
                if label in page.get_text()
            ]
            assert len(matches) == 1, f"{label} must appear on one page: {matches}"
            index = matches[0]
            captions.append(index)
            pixmap = output[index].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
            printed = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            assert visible_markers(printed) == MARKERS, (
                f"Missing edge/corner markers on {label}; page {index + 1}"
            )
        # Five complete attachment pages; no orphaned caption or inserted blank
        # page between one approved page and the next.
        assert captions == list(range(captions[0], captions[0] + len(GEOMETRIES)))
        following_pages = [
            index for index, page in enumerate(output)
            if following in page.get_text()
        ]
        assert following_pages and following_pages[0] > captions[-1]
