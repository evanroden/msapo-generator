import sqlite3

from app.memory import (
    record_expense_profile,
    remembered_expense_employee_number,
    remembered_expense_profile,
)


def _profile(name: str = "Synthetic Employee") -> dict[str, str]:
    return {
        "employee_name": name,
        "employee_number": "TEST-1001",
        "employee_home_bu": "695",
        "approver_name": "RRH Test Administrator",
        "approver_email": "rrh.approver@example.invalid",
        "mail_destination": "home",
        "satellite_office": "",
        "allocation_kind": "job",
        "job_number": "RRH-695400022-O&M",
        "service_center": "",
        "account_cost_type": "01AMA",
        "cost_code_or_wo_type": "5490",
        "work_order_number": "",
        "company_number": "",
        "department_number": "",
        "ou_number": "",
        "gl_account_number": "",
    }


def test_expense_profile_is_remembered_only_for_same_browser_and_account(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    assert record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=_profile(),
    )

    result = remembered_expense_profile(
        "browser-a", "Rochester Regional Health"
    )
    assert result["employee_name"] == "Synthetic Employee"
    assert result["employee_number"] == "TEST-1001"
    assert result["job_number"] == "RRH-695400022-O&M"
    assert remembered_expense_profile("browser-b", "Rochester Regional Health") == {}
    assert remembered_expense_profile("browser-a", "Tulane") == {}

    with sqlite3.connect(tmp_path / "epc_memory.db") as connection:
        device_hash = connection.execute(
            "SELECT device_hash FROM device_expense_profiles"
        ).fetchone()[0]
    assert device_hash != "browser-a"
    assert len(device_hash) == 64


def test_latest_verified_expense_profile_replaces_old_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=_profile("First Name"),
    )

    assert record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=_profile("Correct Name"),
    )

    result = remembered_expense_profile(
        "browser-a", "Rochester Regional Health"
    )
    assert result["employee_name"] == "Correct Name"
    with sqlite3.connect(tmp_path / "epc_memory.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_expense_profiles"
        ).fetchone()[0] == 1


def test_expense_profile_rejects_invalid_identity_or_email(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    invalid = _profile()
    invalid["approver_email"] = "invalid"

    assert not record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=invalid,
    )
    assert not record_expense_profile(
        device_token="",
        account="Rochester Regional Health",
        values=_profile(),
    )
    assert not (tmp_path / "epc_memory.db").exists()


def test_employee_number_is_recalled_by_name_not_just_latest_profile(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    first = _profile("First Employee")
    first["employee_number"] = "TEST-1001"
    second = _profile("Second Employee")
    second["employee_number"] = "TEST-2002"

    assert record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=first,
    )
    assert record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=second,
    )

    assert remembered_expense_employee_number(
        "browser-a", "Rochester Regional Health", "  FIRST employee "
    ) == "TEST-1001"
    assert remembered_expense_employee_number(
        "browser-a", "Rochester Regional Health", "Second Employee"
    ) == "TEST-2002"
    assert remembered_expense_employee_number(
        "browser-b", "Rochester Regional Health", "First Employee"
    ) == ""
    assert remembered_expense_employee_number(
        "browser-a", "Tulane", "First Employee"
    ) == ""


def test_employee_number_mapping_is_corrected_after_confirmed_regeneration(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = _profile("Synthetic Employee")
    corrected = dict(original, employee_number="TEST-9999")

    record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=original,
    )
    record_expense_profile(
        device_token="browser-a",
        account="Rochester Regional Health",
        values=corrected,
    )

    assert remembered_expense_employee_number(
        "browser-a", "Rochester Regional Health", "Synthetic Employee"
    ) == "TEST-9999"
