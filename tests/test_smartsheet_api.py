import json

import pytest
import requests

from app import smartsheet
from app.smartsheet import load_config, submit_po
from app.smartsheet_store import SubmissionStore


def _config():
    specs = {
        "site": {"id": 1, "title": "Site", "type": "TEXT_NUMBER"},
        "total": {"id": 2, "title": "Amount", "type": "TEXT_NUMBER"},
        "estimated_start_date": {"id": 3, "title": "Start", "type": "DATE"},
        "related_to_om": {"id": 4, "title": "O&M", "type": "CHECKBOX"},
        "contact_email": {"id": 5, "title": "Contact", "type": "CONTACT_LIST"},
        "submission_key": {
            "id": 6,
            "title": "Email Process Control Submission Key",
            "type": "TEXT_NUMBER",
        },
    }
    return load_config(
        {
            "SMARTSHEET_API_MODE": "live",
            "SMARTSHEET_API_TOKEN": "token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_SPECS_JSON": json.dumps(specs),
            "SMARTSHEET_REQUIRED_FIELDS": "site,total",
        }
    )


def _columns():
    return [
        {"id": 1, "title": "Site", "type": "TEXT_NUMBER"},
        {"id": 2, "title": "Amount", "type": "TEXT_NUMBER"},
        {"id": 3, "title": "Start", "type": "DATE"},
        {"id": 4, "title": "O&M", "type": "CHECKBOX"},
        {"id": 5, "title": "Contact", "type": "CONTACT_LIST"},
        {
            "id": 6,
            "title": "Email Process Control Submission Key",
            "type": "TEXT_NUMBER",
        },
    ]


def test_build_cells_uses_strict_typed_values():
    config = _config()
    cells, problems = smartsheet._build_cells(
        {
            "site": "UMMC",
            "total": "$1,234.56",
            "estimated_start_date": "07/28/2026",
            "related_to_om": "Yes",
            "contact_email": "person@example.com",
            "submission_key": "key",
        },
        config,
        {column["id"]: column for column in _columns()},
    )
    assert not problems
    by_id = {cell["columnId"]: cell for cell in cells}
    assert by_id[2]["value"] == 1234.56
    assert by_id[3]["value"] == "2026-07-28"
    assert by_id[4]["value"] is True
    assert by_id[5]["value"] == "person@example.com"
    assert all(cell["strict"] is True for cell in cells)


def test_ambiguous_row_create_is_not_retried(monkeypatch, tmp_path):
    config = _config()
    store = SubmissionStore(tmp_path / "submissions.db")
    monkeypatch.setattr(smartsheet, "get_columns", lambda config: _columns())
    calls = {"create": 0}

    def ambiguous_create(config, cells):
        calls["create"] += 1
        raise requests.Timeout("response lost")

    monkeypatch.setattr(smartsheet, "_create_row", ambiguous_create)
    fields = {"site": "UMMC", "total": "$100.00"}
    first = submit_po(fields, [], config=config, store=store)
    second = submit_po(fields, [], config=config, store=store)

    assert calls["create"] == 1
    assert first["uncertain"] is True
    assert second["uncertain"] is True


def test_lost_attachment_response_is_reconciled_by_remote_name(monkeypatch, tmp_path):
    config = _config()
    store = SubmissionStore(tmp_path / "submissions.db")
    monkeypatch.setattr(smartsheet, "get_columns", lambda config: _columns())
    monkeypatch.setattr(smartsheet, "_create_row", lambda config, cells: {"id": 77})
    attachment = ("quote.pdf", b"quote bytes")
    remote_name = smartsheet._api_attachment_name(*attachment)
    calls = {"attach": 0, "list": 0}

    def lost_response(config, row_id, filename, data):
        calls["attach"] += 1
        raise requests.Timeout("lost after upload")

    def list_remote(config, row_id):
        calls["list"] += 1
        return {remote_name} if calls["list"] >= 2 else set()

    monkeypatch.setattr(smartsheet, "_attach_file", lost_response)
    monkeypatch.setattr(smartsheet, "_row_attachment_names", list_remote)

    result = submit_po(
        {"site": "UMMC", "total": "$100.00"},
        [attachment],
        config=config,
        store=store,
    )

    assert result["ok"] is True
    assert result["partial"] is False
    assert result["attached"] == 1
    assert calls["attach"] == 1


def test_live_schema_drift_blocks_before_row_write(monkeypatch, tmp_path):
    config = _config()
    store = SubmissionStore(tmp_path / "submissions.db")
    drifted = _columns()
    drifted[1] = {"id": 2, "title": "Approved Amount", "type": "TEXT_NUMBER"}
    monkeypatch.setattr(smartsheet, "get_columns", lambda config: drifted)
    monkeypatch.setattr(
        smartsheet,
        "_create_row",
        lambda *args, **kwargs: pytest.fail("row write should be blocked"),
    )

    result = submit_po(
        {"site": "UMMC", "total": "$100.00"},
        [],
        config=config,
        store=store,
    )

    assert result["ok"] is False
    assert result["error"] == "Live sheet mapping changed."
    assert any("expected title" in problem for problem in result["problems"])
