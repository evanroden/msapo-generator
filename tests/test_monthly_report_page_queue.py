"""Every scanned page needs a visible decision, including initially omitted pages."""
from dataclasses import asdict, replace
from io import BytesIO

import fitz
from PIL import Image, ImageDraw

from app import monthly_report_library as library, monthly_report_upload_ui as ui
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportSource
from app.monthly_report_sources import SourceContent
from test_monthly_report_upload_ui import app_with_library
from test_monthly_report_upload_ui import upload, button, select


def scanned_pdf():
    with fitz.open() as pdf:
        for n in range(3):
            image = Image.new("RGB", (500, 700), "white")
            ImageDraw.Draw(image).text((20, 20), f"Synthetic service page {n+1}. Inspected pump.", fill="black")
            output = BytesIO()
            image.save(output, "PNG")
            page = pdf.new_page()
            page.insert_image(page.rect, stream=output.getvalue())
        return pdf.tobytes()


def test_scanned_pages_advance_through_initially_unselected_pages(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    upload(monkeypatch, "synthetic-scanned.pdf", scanned_pdf())
    app.run()
    button(app, "Read monthly files").click().run()
    assert not app.exception
    assert next(x for x in app.multiselect if x.label == "Included pages / extracted items").value == []
    assert not button(app, "Next page needing review").disabled
    assert not any(x.label in ("Review source", "File to review", "Classification confidence") for x in app.selectbox)
    destination = next(x for x in app.selectbox if x.label == "Add synthetic-scanned.pdf to")
    assert "Maintenance — vendor service pages" in destination.options
    assert "vendor_reports" not in destination.options
    button(app, "Include page and continue").click().run()
    assert select(app, "Preview page / item").value == 2
    assert not any("Every page has been checked" in x.value for x in app.success)
    button(app, "Leave page out and continue").click().run()
    assert select(app, "Preview page / item").value == 3
    button(app, "Include page and continue").click().run()
    assert button(app, "Next page needing review").disabled
    assert any("Every page has been checked" in x.value for x in app.success)
    assert next(x for x in app.multiselect if x.label == "Included pages / extracted items").value == [1, 3]
    # Explicit omissions survive a rerun and invalidate when reviewed content changes.
    select(app, "Preview page / item").set_value(2).run()
    next(x for x in app.text_input if x.label == "Page caption").set_value("Changed information").run()
    assert not any("Every page has been checked" in x.value for x in app.success)
    assert not app.exception


def test_exclusion_serialization_and_fingerprint_invalidation():
    source = ReportSource("synthetic", "synthetic.png", "a" * 64, ".png", page_texts=("",), needs_vision=(1,))
    source = replace(source, client_page_exclusions=((1, page_fingerprint(source, 1)),))
    restored = library.source_from_dict(asdict(source))
    assert restored == source
    content = SourceContent(restored)
    assert ui._undecided_pages(content, restored) == []
    changed = replace(restored, captions=((1, "New caption"),))
    assert ui._undecided_pages(content, changed) == [1]
    legacy = asdict(source)
    del legacy["client_page_exclusions"]
    assert library.source_from_dict(legacy).client_page_exclusions == ()
