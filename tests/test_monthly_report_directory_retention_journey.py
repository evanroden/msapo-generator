"""Synthetic isolated-admin retention journey; no hosted/customer acceptance claim.

Only file selection is injected (AppTest cannot upload). Reading, reviewing,
confirming, saving and the storage-maintenance action use the real UI handlers.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from app import monthly_report_directory_ui as directory_ui
from app import monthly_report_library as library
from app import monthly_report_testing as testing
from app.monthly_report_objects import object_path
from test_monthly_report_directory_batch import prepared, save


_TOKEN = "a" * 32
_APP = """
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow('a' * 32)
"""


def _open(kind):
    app = AppTest.from_string(_APP, default_timeout=20)
    app.query_params.update({"monthly_qa": "isolated", "monthly_admin": kind})
    app.run()
    assert not app.exception and not app.error
    return app


def _records(path):
    return {str(item.relative_to(path)): item.read_bytes()
            for item in path.rglob("*") if item.is_file()}


@pytest.mark.parametrize("days_old", [29, 31])
def test_storage_action_expires_only_eligible_workbook_and_reopens_saved_history(
        tmp_path, monkeypatch, days_old):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw, _ = prepared()
    digest = sha256(raw).hexdigest()
    monkeypatch.setattr(directory_ui.st, "file_uploader",
                        lambda label, **kwargs: BytesIO(raw)
                        if label == "Contract / site directory workbook" else None)

    # A separate browser owns an identical workbook and a separate directory.
    # Its marker, workbook, pool, metadata and history must all stay untouched.
    with testing.isolated("b" * 32):
        other_plan = batch.prepare_workbook(directory.inspect_workbook(raw))
        assert save(other_plan, raw).saved == ("Synthetic Contract",)
        other_root = library._root().parent
    other_before = _records(other_root)

    app = _open("directory")
    assert not app.radio  # attribution gate before reading saved contacts
    app.text_input("report_directory_actor").set_value("Synthetic Retention Reviewer").run()
    assert any("30 days" in item.value and "history stay" in item.value for item in app.caption)
    app.button("report_directory_read").click().run()
    assert not app.exception and not app.error
    save_button = next(button for button in app.button if button.label == "Save contract directory")
    assert save_button.disabled
    next(box for box in app.checkbox if box.label.startswith("I reviewed all included")).check().run()
    next(button for button in app.button if button.label == "Save contract directory").click().run()
    assert not app.exception and not app.error
    assert any("Directory saved" in item.value for item in app.success)

    with testing.isolated(_TOKEN):
        before = directory.load_directory("Synthetic Contract")
        assert before.revision == 1
        assert before.sites[0].title == "Synthetic North"
        assert before.sites[0].contacts[0].name == "Synthetic Site Lead"
        own_root = library._root()
        workbook = own_root / "directory_sources" / (digest + ".xlsx")
        stamp = workbook.with_suffix(".imported")
        assert workbook.read_bytes() == raw
        # This is an aged *synthetic* import timestamp, not a changed system
        # clock, customer record or claim that real calendar time elapsed.
        stamp.write_text((datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(), encoding="ascii")
        report_original = own_root / "library" / "synthetic-report" / "sources" / (digest + ".xlsx")
        library._atomic_write(report_original, raw)
        pool = object_path(report_original)
        assert workbook.stat().st_ino == report_original.stat().st_ino == pool.stat().st_ino
        history_before = _records(own_root / "directory")

    # Navigating itself does not trigger this on-demand action. The workbook
    # is removed only after clicking the actual storage-maintenance control.
    app.query_params["monthly_admin"] = "storage"
    app.run()
    assert workbook.exists()
    app.button("report_storage_check").click().run()
    assert not app.exception and not app.error
    assert any("deleted 30 days after their latest import" in item.value for item in app.caption)
    assert workbook.exists() == (days_old == 29)
    assert stamp.exists() == (days_old == 29)
    assert report_original.read_bytes() == raw and pool.read_bytes() == raw
    assert _records(own_root / "directory") == history_before
    assert _records(other_root) == other_before

    reopened = _open("directory")
    reopened.text_input("report_directory_actor").set_value("Synthetic Reopen Reviewer").run()
    reopened.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not reopened.exception and not reopened.error
    assert any("Version 1" in item.value for item in reopened.caption)
    assert any("Synthetic Site Lead" in item.value.astype(str).to_numpy().flatten()
               for item in reopened.dataframe)
    assert next(field for field in reopened.number_input if field.label == "Directory version to inspect").value == 1
    with testing.isolated(_TOKEN):
        assert directory.load_directory("Synthetic Contract") == before
        assert directory.load_directory("Synthetic Contract", 1) == before
    assert _records(other_root) == other_before
