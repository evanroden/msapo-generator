"""End-to-end Smartsheet retry/reconciliation using only local stores and fake I/O.

No Smartsheet endpoint, paid service, email or real report is accessed.
The tests intentionally reopen SQLite between interactions to model browser
reruns, process restarts, and repeated clicks on the same reviewed PO.
"""

from __future__ import annotations

import json
from collections import Counter

import requests

from app import smartsheet
from app.smartsheet import load_config, reconcile_submission, submit_po
from app.smartsheet_store import SubmissionStore


ROW_ID = "9007199254740997"  # Above JavaScript's lossless integer limit.


def _config():
    specifications = {
        "request_type": {"id": 1, "title": "REQUEST TYPE", "type": "PICKLIST", "options": ["PO"]},
        "site_location": {"id": 2, "title": "SITE NUMBER / LOCATION", "type": "TEXT_NUMBER"},
        "total": {"id": 3, "title": "PO/CO AMOUNT", "type": "TEXT_NUMBER"},
        "asset_id": {"id": 4, "title": "ASSET ID", "type": "TEXT_NUMBER"},
        "submission_key": {
            "id": 5,
            "title": "Purchase Order Process Control Submission Key",
            "type": "TEXT_NUMBER",
        },
    }
    return load_config(
        {
            "SMARTSHEET_API_MODE": "live",  # Fake provider only, never the deployment.
            "SMARTSHEET_API_TOKEN": "synthetic-not-a-token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_SPECS_JSON": json.dumps(specifications),
            "SMARTSHEET_REQUIRED_FIELDS": "request_type,site_location,total",
        }
    )


def _columns():
    return [
        {"id": 1, "title": "REQUEST TYPE", "type": "PICKLIST", "options": ["PO"]},
        {"id": 2, "title": "SITE NUMBER / LOCATION", "type": "TEXT_NUMBER"},
        {"id": 3, "title": "PO/CO AMOUNT", "type": "TEXT_NUMBER"},
        {"id": 4, "title": "ASSET ID", "type": "TEXT_NUMBER"},
        {
            "id": 5,
            "title": "Purchase Order Process Control Submission Key",
            "type": "TEXT_NUMBER",
        },
    ]


def _fields():
    return {
        "request_type": "PO",
        "site_location": "Synthetic Site",
        "total": "$125.00",
        "asset_id": "synthetic-uid-0007",
    }


def test_partial_attachment_retry_reopens_store_and_never_recreates_row(monkeypatch, tmp_path):
    config = _config()
    path = tmp_path / "isolated" / "submissions.sqlite3"
    files = [("original-quote.pdf", b"%PDF-quote"), ("msapo-form.pdf", b"%PDF-msapo")]
    remote_names: set[str] = set()
    calls = Counter()
    inserted_cells = []
    monkeypatch.setattr(smartsheet, "get_columns", lambda unused: _columns())

    def create_row(unused, cells):
        calls["create"] += 1
        inserted_cells.extend(cells)
        return {"id": ROW_ID}

    def list_remote(unused, row_id):
        assert str(row_id) == ROW_ID
        return set(remote_names)

    def attach(unused, row_id, filename, data):
        assert str(row_id) == ROW_ID
        calls[filename] += 1
        # One attachment actually fails; a retry must use the *same row*.
        if filename == "msapo-form.pdf" and calls[filename] == 1:
            raise requests.ConnectionError("synthetic upload interruption")
        remote_names.add(smartsheet._api_attachment_name(filename, data))

    monkeypatch.setattr(smartsheet, "_create_row", create_row)
    monkeypatch.setattr(smartsheet, "_row_attachment_names", list_remote)
    monkeypatch.setattr(smartsheet, "_attach_file", attach)

    first = submit_po(_fields(), files, config=config, store=SubmissionStore(path))
    assert first["ok"] is True and first["partial"] is True
    assert first["row_id"] == ROW_ID and first["attached"] == 1
    assert len(first["skipped_attachments"]) == 1
    assert calls["create"] == 1
    assert {cell["columnId"]: cell["value"] for cell in inserted_cells}[4] == "synthetic-uid-0007"
    assert all(cell["strict"] is True for cell in inserted_cells)

    # New SQLite object models a reopened tab/process; dict order is irrelevant.
    reversed_fields = dict(reversed(list(_fields().items())))
    assert smartsheet.submission_fingerprint(reversed_fields, files) == first["submission_key"]
    second = submit_po(reversed_fields, files, config=config, store=SubmissionStore(path))
    assert second["ok"] is True and not second["partial"]
    assert second["row_id"] == ROW_ID and second["attached"] == 2

    # A third click after a second reopen returns the durable prior result.
    third = submit_po(_fields(), files, config=config, store=SubmissionStore(path))
    assert third["ok"] is True and third["duplicate"] is True
    assert third["row_id"] == ROW_ID
    assert calls["create"] == 1
    assert calls["original-quote.pdf"] == 1
    assert calls["msapo-form.pdf"] == 2
    assert SubmissionStore(path).get(first["submission_key"])["status"] == "complete"


def test_lost_row_response_requires_exact_remote_reconciliation_before_resume(monkeypatch, tmp_path):
    config = _config()
    path = tmp_path / "isolated" / "submissions.sqlite3"
    fields = _fields()
    files = [("quote.pdf", b"synthetic pdf bytes")]
    calls = Counter()
    remote_key = smartsheet.submission_fingerprint(fields, files)
    actual_row_key = "not-the-current-submission"
    attached_names: set[str] = set()
    monkeypatch.setattr(smartsheet, "get_columns", lambda unused: _columns())

    def ambiguous_create(unused, cells):
        calls["create"] += 1
        assert any(c["columnId"] == 5 and c["value"] == remote_key for c in cells)
        raise requests.Timeout("synthetic lost row-create response")

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_get(unused, url, **kwargs):
        calls["get"] += 1
        if "/search/sheets/" in url:
            return FakeResponse({"results": [{"objectType": "row", "objectId": ROW_ID}]})
        assert url.endswith("/rows/" + ROW_ID)
        return FakeResponse({"cells": [{"columnId": 5, "value": actual_row_key}]})

    def attach(unused, row_id, filename, data):
        assert str(row_id) == ROW_ID
        calls["attach"] += 1
        attached_names.add(smartsheet._api_attachment_name(filename, data))

    monkeypatch.setattr(smartsheet, "_create_row", ambiguous_create)
    monkeypatch.setattr(smartsheet, "_safe_get", fake_get)
    monkeypatch.setattr(smartsheet, "_row_attachment_names", lambda unused, row: set(attached_names))
    monkeypatch.setattr(smartsheet, "_attach_file", attach)

    uncertain = submit_po(fields, files, config=config, store=SubmissionStore(path))
    blocked = submit_po(fields, files, config=config, store=SubmissionStore(path))
    assert uncertain["uncertain"] and blocked["uncertain"]
    assert calls["create"] == 1

    # A fuzzy/incorrect search hit is insufficient: row must contain this key.
    wrong = reconcile_submission(fields, files, config=config, store=SubmissionStore(path))
    assert wrong["ok"] is False and wrong["not_found"]
    assert SubmissionStore(path).get(remote_key)["status"] == "uncertain"

    actual_row_key = remote_key
    adopted = reconcile_submission(fields, files, config=config, store=SubmissionStore(path))
    assert adopted["ok"] is True and adopted["row_id"] == ROW_ID
    assert SubmissionStore(path).get(remote_key)["status"] == "partial"

    resumed = submit_po(fields, files, config=config, store=SubmissionStore(path))
    repeated = submit_po(fields, files, config=config, store=SubmissionStore(path))
    assert resumed["ok"] and resumed["row_id"] == ROW_ID and not resumed["partial"]
    assert repeated["ok"] and repeated["duplicate"] and repeated["row_id"] == ROW_ID
    assert calls["create"] == 1 and calls["attach"] == 1
    assert SubmissionStore(path).get(remote_key)["status"] == "complete"
