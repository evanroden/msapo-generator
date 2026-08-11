import inspect
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
from app.receipt_analyzer import ReceiptAnalysis, ReceiptLineItem


ROOT = Path(__file__).parents[1]


def _configure_smartsheet(monkeypatch):
    values = dotenv_values(ROOT / ".env.example")
    for key, value in values.items():
        if value is not None:
            monkeypatch.setenv(key, value)
    # app.config is imported during test collection, before this per-test
    # environment is installed. Mirror the deployment values into the UI
    # module so AppTest exercises the configured default instead of a blank.
    monkeypatch.setattr(
        expense_ui,
        "RRH_APPROVER_NAME",
        values["RRH_APPROVER_NAME"],
    )
    monkeypatch.setattr(
        expense_ui,
        "RRH_APPROVER_EMAIL",
        values["RRH_APPROVER_EMAIL"],
    )


def test_synthetic_rrh_quick_path_generates_two_files_and_native_new_tab_link(
    monkeypatch,
):
    _configure_smartsheet(monkeypatch)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    assert not app.exception
    assert app.button[0].label == "Built by Evan Roden"
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


def test_scope_draft_is_an_editable_text_field(monkeypatch):
    _configure_smartsheet(monkeypatch)
    captured = {}

    def fake_scope_pdf(**kwargs):
        captured.update(kwargs)
        return b"%PDF-1.7\nsynthetic edited scope"

    monkeypatch.setattr(web_ui, "build_scope_pdf", fake_scope_pdf)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    app.button[0].click().run()

    assert not app.exception
    scope_fields = [
        field
        for field in app.expander[0].text_area
        if field.label == "Scope of Work"
    ]
    assert len(scope_fields) == 1
    assert "Isolate and drain absorption chiller CH-1" in scope_fields[0].value

    scope_fields[0].set_value(
        "Edited scope: replace the failed chiller component and recommission."
    ).run()

    assert not app.exception
    edited = [
        field
        for field in app.expander[0].text_area
        if field.label == "Scope of Work"
    ]
    assert edited[0].value.startswith("Edited scope:")
    next(
        field for field in app.text_input
        if field.label == "Your name (Requester / Asset Manager) *"
    ).set_value("Synthetic Asset Manager").run()
    generate = next(
        button for button in app.button
        if button.label == "Generate both files and Smartsheet link"
    )
    assert not generate.disabled
    generate.click().run()

    assert captured["scope"].startswith("Edited scope:")


def test_expense_employee_number_is_recalled_when_employee_name_changes(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setattr(
        expense_ui,
        "remembered_expense_employee_number",
        lambda _device, account, name: (
            "TEST-4242"
            if account == "Rochester Regional Health"
            and " ".join(name.split()).casefold() == "dane example"
            else ""
        ),
    )

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    employee_name = next(
        field for field in app.text_input if field.label == "Employee name *"
    )
    employee_name.set_value("Dane Example").run()

    employee_number = next(
        field for field in app.text_input if field.label == "Employee number *"
    )
    assert employee_number.value == "TEST-4242"
    assert any(
        "recalled from this employee's last confirmed report" in caption.value
        for caption in app.caption
    )

    employee_name = next(
        field for field in app.text_input if field.label == "Employee name *"
    )
    employee_name.set_value("Unknown Employee").run()
    employee_number = next(
        field for field in app.text_input if field.label == "Employee number *"
    )
    assert employee_number.value == ""


def test_expense_approver_name_suggestions_fill_the_paired_email(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setattr(
        expense_ui,
        "expense_approvers",
        lambda account: (
            [
                ("Remembered Administrator", "remembered@example.invalid"),
                ("Second Administrator", "second@example.invalid"),
            ]
            if account == "Rochester Regional Health"
            else []
        ),
    )

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    approver = next(
        field
        for field in app.selectbox
        if field.label == "Contract administrator / approver name *"
    )
    assert "Remembered Administrator" in approver.options
    assert "Second Administrator" in approver.options

    approver.set_value("Remembered Administrator").run()
    email = next(
        field
        for field in app.text_input
        if field.label == "Contract administrator / approver email *"
    )
    assert email.value == "remembered@example.invalid"
    assert any(
        "Approver email recalled from this account's confirmed history"
        in caption.value
        for caption in app.caption
    )


def test_expense_approver_control_supports_typeahead_and_new_names():
    source = inspect.getsource(expense_ui.render_expense_workflow)

    assert 'placeholder="Type or select an approver"' in source
    assert "accept_new_options=True" in source
    assert 'filter_mode="fuzzy"' in source


def test_workflow_selector_css_uses_high_contrast_active_and_idle_states():
    css = web_ui.CUSTOM_CSS
    active = css.split(
        '.st-key-workflow_mode button[role="radio"][aria-checked="true"] {', 1
    )[1].split("}", 1)[0]
    idle = css.split(
        '.st-key-workflow_mode button[role="radio"][aria-checked="false"] {', 1
    )[1].split("}", 1)[0]

    assert "background: var(--enfra-ocean) !important" in active
    assert "color: #FFFFFF !important" in active
    assert "background: #FFFFFF !important" in idle
    assert "color: var(--enfra-ocean) !important" in idle
    assert 'button[kind="segmented_controlActive"]' not in css


def test_workflow_selector_css_has_ipad_safe_touch_and_layout_rules():
    css = web_ui.CUSTOM_CSS
    group = css.split(
        '.st-key-workflow_mode div[role="radiogroup"] {', 1
    )[1].split("}", 1)[0]
    button = css.split(
        '.st-key-workflow_mode button[role="radio"] {', 1
    )[1].split("}", 1)[0]

    assert "grid-template-columns: repeat(2, minmax(0, 1fr)) !important" in group
    assert "width: 100% !important" in group
    assert "box-sizing: border-box !important" in group
    assert "min-height: 52px !important" in button
    assert "box-sizing: border-box !important" in button
    assert "touch-action: manipulation" in button
    assert "-webkit-tap-highlight-color: transparent" in button
    assert "@media (hover: hover) and (pointer: fine)" in css
    assert 'div[data-testid="stCheckbox"] label { min-height: 44px; }' in css


def test_primary_email_actions_use_brand_contrast_for_links_and_downloads():
    css = web_ui.CUSTOM_CSS

    assert '[data-testid="stDownloadButton"] button[kind="primary"]' in css
    assert '[data-testid="stLinkButton"] a[kind="primary"]' in css
    assert "color: var(--enfra-ocean)" in css


def test_expense_email_destination_defaults_are_platform_appropriate():
    assert expense_ui._preferred_email_destination(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140"
    ) == "Outlook for Windows (PDF attached)"
    assert expense_ui._preferred_email_destination(
        "Mozilla/5.0 (iPad; CPU OS 18_6 like Mac OS X) Mobile/15E148"
    ) == "Default mail app (iPhone / iPad)"
    # iPadOS desktop-site mode commonly identifies itself as Macintosh while
    # retaining the Mobile token.
    assert expense_ui._preferred_email_destination(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Mobile/15E148"
    ) == "Default mail app (iPhone / iPad)"


def test_nondescript_synthetic_trigger_is_available_without_an_env_flag(monkeypatch):
    _configure_smartsheet(monkeypatch)

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    assert not app.exception
    assert "Built by Evan Roden" in {item.label for item in app.button}


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
            "Test Representative",
            "representative@example.invalid",
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
        "Test Representative"
    )
    assert correction_values["Vendor representative email *"] == (
        "representative@example.invalid"
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
        lambda _details, _items, **_kwargs: ExpensePackage(
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

    text_field("Employee name *").set_value("Synthetic Employee").run()
    text_field("Employee number *").set_value("TEST-1001").run()
    assert text_field("Employee Home Business Unit").value == "695"
    assert text_field("Employee Home Business Unit").disabled

    # Switching workflows hides every expense widget for one rerun. The plain
    # draft mirror must retain both the uploads and typed fields.
    app.segmented_control[0].set_value("Purchase order").run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    assert not app.exception
    assert text_field("Employee name *").value == "Synthetic Employee"
    assert text_field("Merchant").value == "Test Parking"

    assert next(
        field for field in app.selectbox if field.label == "Job number *"
    ).value == "RRH-695400022-O&M"
    assert text_field("Account / cost type *").value == "01AMA"
    assert text_field("Cost code *").value == "5490"
    next(
        box for box in app.checkbox if box.label.startswith("I confirm this generated")
    ).set_value(True).run()

    generate = next(
        button
        for button in app.button
        if button.label == "Generate expense report and email draft"
    )
    assert not generate.disabled
    generate.click().run()

    assert not app.exception
    email_destination = next(
        field for field in app.selectbox if field.label == "Open approval email in"
    )
    assert email_destination.value == "Outlook for Windows (PDF attached)"
    assert [button.label for button in app.get("download_button")] == [
        "Open approval email in Outlook",
        "Download completed Excel report",
        "Download combined PDF packet",
    ]
    other_options = next(
        expander
        for expander in app.expander
        if expander.label == "Other file and email options"
    )
    assert not other_options.proto.expanded
    assert [button.label for button in other_options.download_button] == [
        "Download completed Excel report",
        "Download combined PDF packet",
    ]
    assert [button.label for button in other_options.get("link_button")] == [
        "Open a new email without attachments ↗"
    ]

    email_destination.set_value("Outlook on the web").run()
    web_link = next(
        link
        for link in app.get("link_button")
        if link.label == "Open approval email in Outlook on the web ↗"
    )
    assert web_link.url.startswith(
        "https://outlook.office.com/mail/deeplink/compose?"
    )
    assert "rrh.approver%40example.invalid" in web_link.url

    email_destination = next(
        field for field in app.selectbox if field.label == "Open approval email in"
    )
    email_destination.set_value("Default mail app (iPhone / iPad)").run()
    local_link = next(
        link
        for link in app.get("link_button")
        if link.label == "Open approval email in the default mail app ↗"
    )
    assert local_link.url.startswith("mailto:rrh.approver@example.invalid?")


def test_primary_workflows_do_not_use_blue_information_callouts():
    assert "st.info(" not in inspect.getsource(expense_ui.render_expense_workflow)
    assert "st.info(" not in inspect.getsource(expense_ui._render_generated_package)
    assert "st.info(" not in inspect.getsource(web_ui.main)


def test_itemized_receipt_selection_recalculates_reimbursable_amount(
    monkeypatch, tmp_path
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        expense_ui,
        "analyze_receipt",
        lambda *_args: ReceiptAnalysis(
            merchant_name="Synthetic Store",
            transaction_date=date(2026, 8, 10),
            total_amount="33.00",
            tax_amount="3.00",
            suggested_description="Business supplies",
            confidence="high",
            line_items=(
                ReceiptLineItem("Business notebook", "20.00"),
                ReceiptLineItem("Personal snack", "10.00"),
            ),
        ),
    )
    image = Image.new("RGB", (180, 280), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload(
        "itemized.png", buffer.getvalue(), "image/png"
    ).run()

    def amount_field():
        return next(
            field
            for field in app.text_input
            if field.label == "Reimbursable amount *"
        )

    assert amount_field().value == "33.00"
    personal_item = next(
        box for box in app.checkbox if "Personal snack — $10.00" in box.label
    )
    personal_item.set_value(False).run()

    # The $3 final-total adjustment is allocated in proportion to selected
    # purchased items: $20 / $30 × $33 = $22.
    assert amount_field().value == "22.00"
    assert any(
        "Selected 1 of 2 items; reimbursable amount $22.00" in caption.value
        for caption in app.caption
    )

    amount_field().set_value("21.50").run()
    next(
        field for field in app.text_input if field.label == "Merchant"
    ).set_value("Synthetic Store corrected").run()
    assert amount_field().value == "21.50"

    personal_item = next(
        box for box in app.checkbox if "Personal snack — $10.00" in box.label
    )
    personal_item.set_value(True).run()
    assert amount_field().value == "33.00"


def test_selected_receipt_item_amount_handles_missing_total_and_empty_selection():
    analysis = ReceiptAnalysis(
        line_items=(
            ReceiptLineItem("Parking", "12.00"),
            ReceiptLineItem("Toll", "4.25"),
        )
    )

    assert expense_ui._selected_receipt_item_amount(analysis, {1}) == "4.25"
    assert expense_ui._selected_receipt_item_amount(analysis, set()) == ""

    taxed = ReceiptAnalysis(
        total_amount="10.00",
        line_items=(
            ReceiptLineItem("Item A", "3.00"),
            ReceiptLineItem("Item B", "3.00"),
            ReceiptLineItem("Item C", "3.00"),
        ),
    )
    assert expense_ui._selected_receipt_item_amount(taxed, {0}) == "3.33"
    assert expense_ui._selected_receipt_item_amount(taxed, {0, 1, 2}) == "10.00"


def test_expense_receipt_can_split_into_independently_editable_lines(
    monkeypatch, tmp_path
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    captured = {}
    monkeypatch.setattr(
        expense_ui,
        "analyze_receipt",
        lambda *_args: ReceiptAnalysis(
            merchant_name="Synthetic Market",
            transaction_date=date(2026, 8, 10),
            total_amount="68.99",
            suggested_description="Full receipt",
            confidence="high",
        ),
    )

    def fake_package(details, items, *, mileage_items):
        captured["details"] = details
        captured["items"] = items
        captured["mileage"] = mileage_items
        return ExpensePackage(
            basename="split-test",
            workbook_bytes=b"xlsx-test",
            pdf_bytes=b"%PDF-test",
            total=Decimal("35.00"),
            receipt_count=1,
        )

    monkeypatch.setattr(expense_ui, "build_expense_package", fake_package)
    image = Image.new("RGB", (240, 360), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload(
        "market.png", buffer.getvalue(), "image/png"
    ).run()

    def text_fields(label):
        return [field for field in app.text_input if field.label == label]

    text_fields("Employee name *")[0].set_value("Synthetic Employee").run()
    text_fields("Employee number *")[0].set_value("TEST-1001").run()
    next(
        toggle for toggle in app.toggle
        if toggle.label == "Split this receipt into multiple reimbursement lines"
    ).set_value(True).run()

    descriptions = text_fields("Description / business purpose *")
    amounts = text_fields("Reimbursable amount *")
    assert len(descriptions) == 2
    assert len(amounts) == 2
    amounts[0].set_value("20.00").run()
    text_fields("Description / business purpose *")[1].set_value(
        "Office supplies"
    ).run()
    text_fields("Reimbursable amount *")[1].set_value("15.00").run()
    assert [field.value for field in text_fields("Account / cost type *")] == [
        "01AMA",
        "01AMA",
    ]
    assert [field.value for field in text_fields("Cost code *")] == [
        "5490",
        "5490",
    ]

    next(
        box for box in app.checkbox if box.label.startswith("I confirm this generated")
    ).set_value(True).run()
    generate = next(
        button for button in app.button
        if button.label == "Generate expense report and email draft"
    )
    assert not generate.disabled
    generate.click().run()

    assert not app.exception
    assert len(captured["items"]) == 2
    assert captured["items"][0].receipt_id != captured["items"][1].receipt_id
    assert (
        captured["items"][0].source_receipt_id
        == captured["items"][1].source_receipt_id
    )
    assert [item.amount for item in captured["items"]] == ["20.00", "15.00"]


def test_restored_receipts_merge_new_uploads_and_remove_individually(
    monkeypatch, tmp_path
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        expense_ui,
        "analyze_receipt",
        lambda *_args: ReceiptAnalysis(
            merchant_name="Synthetic Merchant",
            transaction_date=date(2026, 8, 10),
            total_amount="31.25",
            suggested_description="Business purchase",
            confidence="high",
        ),
    )

    first = BytesIO()
    Image.new("RGB", (120, 220), "white").save(first, format="JPEG")
    second = BytesIO()
    Image.new("RGB", (121, 220), "ivory").save(second, format="JPEG")

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload(
        "first.jpg", first.getvalue(), "image/jpeg"
    ).run()

    app.segmented_control[0].set_value("Purchase order").run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload(
        "second.jpg", second.getvalue(), "image/jpeg"
    ).run()

    remove_buttons = [
        button for button in app.button if button.label == "Remove this receipt"
    ]
    assert len(remove_buttons) == 2

    next(
        field for field in app.text_input if field.label == "Employee name *"
    ).set_value("Synthetic Employee").run()
    assert len(
        [button for button in app.button if button.label == "Remove this receipt"]
    ) == 2

    next(
        button for button in app.button if button.label == "Remove this receipt"
    ).click().run()
    assert not app.exception
    assert len(
        [button for button in app.button if button.label == "Remove this receipt"]
    ) == 1


def test_rrh_mileage_only_flow_uses_service_year_defaults_and_job_columns(
    monkeypatch, tmp_path
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    captured = {}

    def fake_package(details, items, *, mileage_items):
        captured["details"] = details
        captured["items"] = items
        captured["mileage"] = mileage_items
        return ExpensePackage(
            basename="mileage-test",
            workbook_bytes=b"xlsx-test",
            pdf_bytes=b"%PDF-test",
            total=Decimal("22.80"),
            receipt_count=0,
            mileage_count=1,
        )

    monkeypatch.setattr(expense_ui, "build_expense_package", fake_package)

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()

    def text_field(label):
        return next(field for field in app.text_input if field.label == label)

    text_field("Employee name *").set_value("Synthetic Employee").run()
    text_field("Employee number *").set_value("TEST-1001").run()
    next(
        toggle for toggle in app.toggle
        if toggle.label == "Include reimbursable business mileage"
    ).set_value(True).run()
    next(
        field for field in app.number_input if field.label == "Business miles *"
    ).set_value(30.0).run()
    text_field("Mileage business purpose *").set_value("RRH site visit").run()
    text_field("Destination *").set_value("UMMC").run()

    service_year = next(
        field for field in app.selectbox if field.label == "RRH service year *"
    )
    service_year.set_value(2).run()
    assert text_field("Account / cost type *").value == "02AMA"
    assert text_field("Cost code *").value == "5490"
    assert next(
        field for field in app.selectbox if field.label == "Job number *"
    ).value == "RRH-695400022-O&M"
    assert not any(field.label == "Allocation type *" for field in app.selectbox)
    assert not any("Work-order" in field.label for field in app.text_input)
    assert not any(field.label == "Company number *" for field in app.text_input)

    next(
        box for box in app.checkbox if box.label.startswith("I confirm this generated")
    ).set_value(True).run()
    generate = next(
        button for button in app.button
        if button.label == "Generate expense report and email draft"
    )
    assert not generate.disabled
    generate.click().run()

    assert not app.exception
    assert captured["items"] == []
    assert captured["details"].employee_home_bu == "695"
    assert captured["details"].approver_email == "rrh.approver@example.invalid"
    assert len(captured["mileage"]) == 1
    assert captured["mileage"][0].allocation.account_cost_type == "02AMA"
    assert captured["mileage"][0].allocation.cost_code_or_wo_type == "5490"
