"""Synthetic expense AppTest isolation gate, independent of Monthly QA routing.

The real expense renderer runs in two separate Streamlit sessions. Original
invented image bytes and known analyses are seeded as retained uploads; external
reading is forbidden, not simulated as a successful extraction. Only the final
document builder is replaced in the explicit generation test. This is not a
public-browser, authentic-document, renderer, or native-share acceptance claim.
"""
from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal
import hashlib
import io
from pathlib import Path
import socket
import sqlite3
import subprocess

import fitz
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import expense_ui, memory, receipt_analyzer, receipt_jobs
from app.expense_report import ExpensePackage
from app.monthly_report_testing import scope
from app.receipt_analyzer import ReceiptAnalysis


ACCOUNT = "Rochester Regional Health"
ACCOUNT_TOKEN = hashlib.sha256(ACCOUNT.encode()).hexdigest()[:10]


@pytest.fixture
def isolated_expenses(monkeypatch, tmp_path):
    """Use real temporary SQLite, with fail-closed I/O and reader sentinels."""
    assert scope() is None, "this test does not rely on the Monthly QA namespace"
    root = tmp_path.resolve()
    monkeypatch.setenv("EPC_DATA_DIR", str(root))
    monkeypatch.setattr(expense_ui, "account_director", lambda _account:
                        ("Synthetic Director", "director@example.invalid"))
    monkeypatch.setattr(expense_ui, "director_config_problems", lambda _accounts: [])
    script = root / "expense_test_app.py"
    script.write_text(
        "import streamlit as st\n"
        "from app.expense_ui import render_expense_workflow, preserve_expense_draft_state\n"
        "render_expense_workflow(st.session_state['test_browser_token'], 'America/New_York')\n"
        "preserve_expense_draft_state()\n",
        encoding="utf-8",
    )
    attempts = []
    database_paths = []
    file_writes = []
    business_writes = []

    def forbidden(name):
        def reject(*_args, **_kwargs):
            attempts.append(name)
            raise AssertionError(f"Unexpected external action in isolated expense test: {name}")
        return reject

    monkeypatch.setattr(socket.socket, "connect", forbidden("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket.create_connection"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("subprocess"))
    for module, name in (
        (expense_ui, "start_receipt"), (receipt_jobs, "start_receipt"),
        (expense_ui, "prepare_receipt_content"), (receipt_analyzer, "prepare_receipt_content"),
        (expense_ui, "analyze_prepared_receipt"), (receipt_analyzer, "analyze_prepared_receipt"),
        (expense_ui, "_render_ios_mail_share"), (expense_ui, "_IOS_MAIL_SHARE_COMPONENT"),
    ):
        monkeypatch.setattr(module, name, forbidden(f"{module.__name__}.{name}"))

    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        path = Path(database).resolve()
        assert path.is_relative_to(root), f"SQLite escaped temporary storage: {path}"
        database_paths.append(path)
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)

    def guarded_open(original):
        def open_file(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, bytes, Path)) and any(flag in mode for flag in "wax+"):
                path = Path(file).resolve()
                assert path.is_relative_to(root), f"File write escaped temporary storage: {path}"
                file_writes.append(path)
            return original(file, mode, *args, **kwargs)
        return open_file

    monkeypatch.setattr(builtins, "open", guarded_open(builtins.open))
    monkeypatch.setattr(io, "open", guarded_open(io.open))
    for name in ("record_expense_profile", "record_expense_approver"):
        original = getattr(expense_ui, name)

        def record(*args, _original=original, _name=name, **kwargs):
            business_writes.append((_name, kwargs))
            return _original(*args, **kwargs)

        monkeypatch.setattr(expense_ui, name, record)

    assert memory._data_dir().resolve() == root
    yield {"root": root, "script": script, "attempts": attempts,
           "database_paths": database_paths, "file_writes": file_writes,
           "business_writes": business_writes}
    assert attempts == [], "a swallowed external failure is still a failed isolation gate"
    assert all(path.is_relative_to(root) for path in database_paths + file_writes)
    assert scope() is None


def _receipt(color):
    output = io.BytesIO()
    Image.new("RGB", (80, 140), color).save(output, format="PNG")
    data = output.getvalue()
    return hashlib.sha256(data).hexdigest(), data


def _session(gate, browser, receipts):
    app = AppTest.from_file(gate["script"], default_timeout=30)
    app.session_state["test_browser_token"] = browser
    app.session_state["expense_account"] = ACCOUNT
    app.session_state["expense_receipt_files"] = [
        (name, payload, "image/png") for _receipt_id, name, payload in receipts
    ]
    for receipt_id, _name, _payload in receipts:
        app.session_state[f"expense_receipt_analysis_{receipt_id}"] = ReceiptAnalysis(
            merchant_name="Synthetic Merchant", transaction_date=date(2026, 8, 10),
            total_amount="30.00", suggested_description="Synthetic business supplies", confidence="high",
        )
    app.session_state["expense_draft_snapshot"] = {
        f"expense_employee_name_{ACCOUNT_TOKEN}": f"Synthetic Employee {browser}",
        f"expense_employee_number_{ACCOUNT_TOKEN}": f"TEST-{browser}",
        f"expense_manager_name_{ACCOUNT_TOKEN}": "Synthetic Manager",
        f"expense_manager_email_{ACCOUNT_TOKEN}": "manager@example.invalid",
        f"expense_report_date_{ACCOUNT_TOKEN}": date(2026, 8, 10),
    }
    app.run()
    assert not app.exception
    return app


def _field(app, key):
    return next(field for field in app.text_input if field.key == key)


def test_two_expense_sessions_keep_shared_source_keys_splits_and_removals_isolated(isolated_expenses):
    gate = isolated_expenses
    shared_id, shared = _receipt("white")
    first_id, first = _receipt("red")
    second_id, second = _receipt("blue")
    a = _session(gate, "A", [(shared_id, "shared.png", shared), (first_id, "a.png", first)])
    b = _session(gate, "B", [(shared_id, "shared.png", shared), (second_id, "b.png", second)])
    token = shared_id[:12]
    next(toggle for toggle in a.toggle if toggle.key == f"expense_split_{token}").set_value(True).run()
    _field(a, f"expense_amount_{token}").set_value("11.00").run()
    _field(a, f"expense_amount_{token}_line_2").set_value("7.00").run()
    _field(a, f"expense_description_{token}_line_2").set_value("Synthetic split supplies").run()
    _field(b, f"expense_amount_{token}").set_value("23.00").run()
    a.run()
    b.run()
    assert not a.exception and not b.exception
    assert _field(a, f"expense_amount_{token}").value == "11.00"
    assert _field(a, f"expense_amount_{token}_line_2").value == "7.00"
    assert _field(b, f"expense_amount_{token}").value == "23.00"
    assert not next(toggle for toggle in b.toggle if toggle.key == f"expense_split_{token}").value
    assert [hashlib.sha256(item[1]).hexdigest() for item in a.session_state["expense_receipt_files"]] == [shared_id, first_id]
    assert [hashlib.sha256(item[1]).hexdigest() for item in b.session_state["expense_receipt_files"]] == [shared_id, second_id]

    next(button for button in a.button if button.key == f"expense_remove_receipt_{token}").click().run()
    b.run()
    assert [item[0] for item in a.session_state["expense_receipt_files"]] == ["a.png"]
    assert [item[0] for item in b.session_state["expense_receipt_files"]] == ["shared.png", "b.png"]
    assert _field(b, f"expense_amount_{token}").value == "23.00"
    assert gate["business_writes"] == []
    assert gate["database_paths"], "real temporary memory reads must exercise the guarded storage boundary"


def test_expense_generation_is_explicit_and_remembers_only_in_temporary_storage(isolated_expenses, monkeypatch):
    gate = isolated_expenses
    receipt_id, receipt = _receipt("green")
    generated = []
    document = fitz.open()
    document.new_page(width=240, height=320).insert_text((20, 40), "SYNTHETIC EXPENSE PACKET")
    pdf = document.tobytes()
    document.close()

    def build(details, items, *, mileage_items):
        generated.append((details, items, mileage_items))
        return ExpensePackage(basename="synthetic-isolation", workbook_bytes=b"synthetic-workbook",
                              pdf_bytes=pdf, total=Decimal("30.00"), receipt_count=1)

    monkeypatch.setattr(expense_ui, "build_expense_package", build)
    app = _session(gate, "A", [(receipt_id, "synthetic.png", receipt)])
    app.run()
    assert generated == [] and gate["business_writes"] == []
    next(box for box in app.checkbox if box.label.startswith("I confirm this generated")).set_value(True).run()
    generate = next(button for button in app.button if button.key == "generate_expense_package")
    assert not generate.disabled
    generate.click().run()
    assert not app.exception
    assert len(generated) == 1
    assert [name for name, _kwargs in gate["business_writes"]] == ["record_expense_profile", "record_expense_approver"]
    assert (gate["root"] / "epc_memory.db").is_file()
    assert memory.remembered_expense_profile("A", ACCOUNT)["employee_number"] == "TEST-A"
    assert memory.remembered_expense_profile("B", ACCOUNT) == {}
    assert any(button.label == "Download combined PDF packet" for button in app.get("download_button"))
    app.run()
    assert len(generated) == 1 and len(gate["business_writes"]) == 2
    _field(app, f"expense_amount_{receipt_id[:12]}").set_value("29.00").run()
    assert not app.exception
    assert not any(button.label == "Download combined PDF packet" for button in app.get("download_button"))
    assert len(generated) == 1 and len(gate["business_writes"]) == 2
