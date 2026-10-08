from io import BytesIO

from app import monthly_report_upload_ui as ui
from test_monthly_report_editor import app_with_library
from test_monthly_report_sources import pdf_bytes


def button(app, label):
    return next(w for w in app.button if w.label == label)


def select(app, label):
    return next(w for w in app.selectbox if w.label == label)


def upload(monkeypatch, name, data):
    stream = BytesIO(data)
    stream.name = name
    original = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *args, **kwargs:
                        [stream] if label == "Monthly source files" else original(label, *args, **kwargs))


def test_upload_selection_invalidation_and_workflow_retention(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    upload(monkeypatch, "synthetic.pdf", pdf_bytes(3))
    app.run()
    button(app, "Read monthly files").click().run()
    assert not app.exception
    assert next(w for w in app.multiselect if w.label == "Included pages / extracted items").value == [1, 2, 3]
    select(app, "Classification").set_value("Vendor service").run()
    for page in (1, 2, 3):
        select(app, "Preview page / item").set_value(page).run()
        next(w for w in app.checkbox if w.label.startswith("I checked this page:")).check().run()
    button(app, "Prepare selected pages").click().run()
    assert not app.exception
    next(w for w in app.selectbox if w.key.endswith("_vendor_reports_source")).set_value("This month").run()
    assert any(w.label == "This month's content" for w in app.radio)
    next(w for w in app.multiselect if w.label == "Included pages / extracted items").set_value([1, 3]).run()
    assert not any(w.label == "This month's content" for w in app.radio)
    button(app, "Prepare selected pages").click().run()
    assert not app.exception
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert not app.exception
    assert next(w for w in app.multiselect if w.label == "Included pages / extracted items").value == [1, 3]
    assert any(w.label == "This month's content" for w in app.radio)
    button(app, "Remove source from this draft").click().run()
    assert not app.exception
    assert not any(w.label == "Review source" for w in app.selectbox)


def test_cmms_mapping_applies_real_schema_and_invalidates_on_change(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    upload(monkeypatch, "synthetic.csv", b"Work order,Finished,Facility,Type\n001,2026-09-02,Demo North,PM\n")
    app.run()
    button(app, "Read monthly files").click().run()
    assert not app.exception
    assert select(app, "Classification").value == "CMMS export"
    for label, value in (("Finish date column", "Finished"), ("Work-order identity column", "Work order"),
                         ("Facility column", "Facility"), ("PM/CM category column", "Type")):
        select(app, label).set_value(value).run()
    next(w for w in app.multiselect if w.label == "Category values that mean PM").set_value(["PM"]).run()
    next(w for w in app.checkbox if w.label == "I confirm this CMMS mapping and coverage").check().run()
    button(app, "Apply CMMS mapping").click().run()
    assert not app.exception
    next(w for w in app.selectbox if w.key.endswith("_service_calls_source")).set_value("This month").run()
    assert any(w.label == "This month's content" for w in app.radio)
    select(app, "Finish date column").set_value("").run()
    assert not app.exception
    assert not any(w.label == "This month's content" for w in app.radio)


def test_guided_page_review_keeps_omits_and_invalidates_caption(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    upload(monkeypatch, "synthetic.pdf", pdf_bytes(3))
    app.run()
    button(app, "Read monthly files").click().run()
    assert button(app, "Include page and continue").disabled
    next(w for w in app.checkbox if w.label.startswith("I checked this page:")).check().run()
    button(app, "Include page and continue").click().run()
    assert not app.exception
    assert select(app, "Preview page / item").value == 2
    button(app, "Leave page out and continue").click().run()
    assert select(app, "Preview page / item").value == 3
    assert next(w for w in app.multiselect if w.label == "Included pages / extracted items").value == [1, 3]
    next(w for w in app.checkbox if w.label.startswith("I checked this page:")).check().run()
    button(app, "Include page and continue").click().run()
    assert button(app, "Next page needing review").disabled
    select(app, "Preview page / item").set_value(1).run()
    next(w for w in app.text_input if w.label == "Page caption").set_value("Changed caption").run()
    assert button(app, "Include page and continue").disabled
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert not app.exception
    assert next(w for w in app.multiselect if w.label == "Included pages / extracted items").value == [1, 3]
    assert button(app, "Include page and continue").disabled
    select(app, "Preview page / item").set_value(2).run()
    next(w for w in app.checkbox if w.label.startswith("I checked this page:")).check().run()
    button(app, "Include page and continue").click().run()
    assert select(app, "Preview page / item").value == 1
    assert next(w for w in app.multiselect if w.label == "Included pages / extracted items").value == [1, 2, 3]


def test_priced_page_cannot_be_included_by_guided_action(monkeypatch, tmp_path):
    import fitz
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Inspected equipment. Invoice amount: $500")
        raw = pdf.tobytes()
    app, _ = app_with_library(monkeypatch, tmp_path)
    upload(monkeypatch, "synthetic-price.pdf", raw)
    app.run()
    button(app, "Read monthly files").click().run()
    assert not app.exception
    assert button(app, "Include page and continue").disabled
    assert next(w for w in app.checkbox if w.label.startswith("I checked this page:")).disabled
    button(app, "Leave page out and continue").click().run()
    assert not app.exception
    assert next(w for w in app.multiselect if w.label == "Included pages / extracted items").value == []
