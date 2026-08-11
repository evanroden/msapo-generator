import sqlite3

from app.memory import record_expense_profile, remembered_expense_profile


def _profile(name: str = "Evan Roden") -> dict[str, str]:
    return {
        "employee_name": name,
        "employee_number": "00133509",
        "employee_home_bu": "02037",
        "approver_name": "David Siegal",
        "approver_email": "david.siegal@enfrasolutions.com",
        "mail_destination": "home",
        "satellite_office": "",
        "allocation_kind": "job",
        "job_number": "RRH-695400022-O&M",
        "service_center": "",
        "account_cost_type": "05490",
        "cost_code_or_wo_type": "01ASTART",
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
    assert result["employee_name"] == "Evan Roden"
    assert result["employee_number"] == "00133509"
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

