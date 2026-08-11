from pathlib import Path
from datetime import date
from decimal import Decimal
from io import BytesIO

from dotenv import dotenv_values
from PIL import Image
from streamlit.testing.v1 import AppTest

import app.expense_ui as expense_ui
import app.web_ui as web_ui
from app.expense_report import ExpensePackage
from app.quote_analyzer import QuoteAnalysis
from app.receipt_analyzer import ReceiptAnalysis


ROOT = Path(__file__).parents[1]


def _configure_smartsheet(monkeypatch):
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)


def test_synthetic_rrh_quick_path_generates_two_files_and_native_new_tab_link(
    monkeypatch,
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_ENABLE_SYNTHETIC_SAMPLE", "true")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert [item.label for item in app.expander] == [
        "Review scope, inclusions, and exclusions",
        "Change a value the tool already filled",
    ]
    assert app.button[1].disabled

    app.text_input[0].set_value("Synthetic Asset Manager").run()
    assert not app.button[1].disabled
    app.button[1].click().run()

    assert not app.exception
    assert len(app.get("download_button")) == 2
    links = app.get("link_button")
    assert len(links) == 1
    assert links[0].label == "Open Smartsheet in a new tab ↗"
    assert "REQUESTER=Synthetic%20Asset%20Manager" in links[0].url
    assert "DESCRIPTION%20OF%20WORK=Chiller%20Repair" in links[0].url
    assert "ASSET%20ID=EEA-CH-1-CSHC" in links[0].url
    assert "DISPATCH%20WO%20TO%20SERVICE%20CENTER%3F=NA" in links[0].url


def test_synthetic_sample_control_is_absent_from_the_production_path(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_ENABLE_SYNTHETIC_SAMPLE", "false")

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    assert not app.exception
    assert "Load synthetic sample (testing)" not in {
        item.label for item in app.button
    }


def test_unresolved_fields_are_visible_stable_and_not_in_correction_panel(
    monkeypatch,
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setattr(
        web_ui,
        "analyze_quote",
        lambda _text: QuoteAnalysis(
            scope_of_work="Repair unidentified equipment.",
            purchase_route_guess="materials_purchase",
            request_type_guess="PO",
            tax_status="unclear",
        ),
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    app.radio[0].set_value("Paste text").run()
    app.text_area[0].set_value("Quote without usable routing fields").run()

    assert not app.exception
    assert any(
        'class="tax-alert" role="alert"' in item.value
        and "No tax was found" in item.value
        for item in app.markdown
    )
    unresolved_labels = {
        "PO/CO amount — final total including every fee and tax *",
        "Vendor name *",
        "Vendor representative name *",
        "Vendor representative email *",
        "Short description (20 characters maximum) *",
    }
    assert unresolved_labels <= {item.label for item in app.text_input}
    assert not unresolved_labels & {
        item.label for item in app.expander[1].text_input
    }

    app.text_input[0].set_value("123.45").run()

    assert unresolved_labels <= {item.label for item in app.text_input}
    assert not unresolved_labels & {
        item.label for item in app.expander[1].text_input
    }
    warnings = [item.value for item in app.warning]
    assert not any("all-in PO/CO amount" in message for message in warnings)
    assert not any(".." in message for message in warnings)


def test_vendor_representative_is_filled_from_account_vendor_memory(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setattr(
        web_ui,
        "analyze_quote",
        lambda _text: QuoteAnalysis(
            vendor_name="Trane",
            project_description="Repair steam boiler B-1.",
            facility_name="St. Mary's Medical Campus",
            facility_address="89 Genesee St, Rochester, NY 14611",
            scope_of_work="Repair steam boiler B-1.",
            inclusions=["Labor"],
            exclusions=["Unquoted work"],
            contact_name=None,
            contact_email=None,
            total_amount="$1,819.80",
            short_description="Boiler Repair",
            work_category="repairs",
            asset_reference="B-1",
            purchase_route_guess="onsite_labor",
            request_type_guess="PO",
            tax_status="included",
        ),
    )
    monkeypatch.setattr(
        web_ui,
        "remembered_vendor_contact",
        lambda contract, vendor, **_kwargs: (
            "Ashley Representative",
            "ashley@example.com",
        ),
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    app.radio[0].set_value("Paste text").run()
    app.text_area[0].set_value("Trane boiler B-1 quote for St. Mary's").run()

    assert not app.exception
    correction_values = {
        item.label: item.value for item in app.expander[1].text_input
    }
    assert correction_values["Vendor representative name *"] == (
        "Ashley Representative"
    )
    assert correction_values["Vendor representative email *"] == (
        "ashley@example.com"
    )
    assert any(
        "filled from prior requests" in item.value for item in app.caption
    )


def test_expense_workflow_generates_excel_pdf_and_attached_email_draft(
    monkeypatch, tmp_path
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        expense_ui,
        "analyze_receipt",
        lambda *_args: ReceiptAnalysis(
            merchant_name="Test Parking",
            transaction_date=date(2026, 8, 10),
            total_amount="31.25",
            suggested_description="Business parking",
            confidence="high",
        ),
    )
    monkeypatch.setattr(
        expense_ui,
        "build_expense_package",
        lambda _details, _items: ExpensePackage(
            basename="expense-test",
            workbook_bytes=b"xlsx-test",
            pdf_bytes=b"%PDF-test",
            total=Decimal("31.25"),
            receipt_count=1,
        ),
    )
    image = Image.new("RGB", (120, 220), "white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload(
        "parking.jpg", buffer.getvalue(), "image/jpeg"
    ).run()

    def text_field(label):
        return next(field for field in app.text_input if field.label == label)

    text_field("Employee name *").set_value("Evan Roden").run()
    text_field("Employee number *").set_value("133509").run()
    text_field("Employee Home Business Unit *").set_value("1234").run()

    # Switching workflows hides every expense widget for one rerun. The plain
    # draft mirror must retain both the uploads and typed fields.
    app.segmented_control[0].set_value("Purchase order").run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    assert not app.exception
    assert text_field("Employee name *").value == "Evan Roden"
    assert text_field("Merchant").value == "Test Parking"

    next(
        field for field in app.selectbox if field.label == "Job number *"
    ).set_value("RRH-695400022-O&M").run()
    text_field("Account / cost type *").set_value("5490").run()
    text_field("Cost code *").set_value("01ASTART").run()

    generate = next(
        button
        for button in app.button
        if button.label == "Generate expense report and email draft"
    )
    assert not generate.disabled
    generate.click().run()

    assert not app.exception
    assert [button.label for button in app.get("download_button")] == [
        "Download completed Excel report",
        "Download combined PDF packet",
        "Download Outlook email draft with attachments",
    ]
    mail_links = app.get("link_button")
    assert len(mail_links) == 1
    assert mail_links[0].url.startswith(
        "mailto:david.siegal@enfrasolutions.com?"
    )
