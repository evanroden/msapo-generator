"""Exercise the reachable single-sheet import actions with synthetic workbooks."""
from io import BytesIO

import streamlit as st
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_retention as retention
from test_monthly_report_directory_single_sheet_provenance import (
    CONTRACT, _save, _workbook,
)


APP = """
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
"""


def test_reviewed_single_sheet_correction_still_saves_after_nineteen_prior_versions(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    originals, history = {}, {}
    for number in range(19):
        raw = _workbook(number)
        state = _save(raw)
        originals[retention._sources() / (state.source_sha256 + ".xlsx")] = raw
        path = directory._path(CONTRACT) / "history" / f"{state.revision:08d}.json"
        history[path] = path.read_bytes()

    raw = _workbook(19)
    upload = BytesIO(raw)
    upload.name = "synthetic-contact-correction.xlsx"
    original_uploader = st.file_uploader
    # AppTest cannot select a file; only that transport is substituted. The
    # Read workbook parser, review, confirmation, Save and rerun are real.
    monkeypatch.setattr(st, "file_uploader", lambda label, *args, **kwargs:
                        upload if label == "Contract / site directory workbook"
                        else original_uploader(label, *args, **kwargs))
    app = AppTest.from_string(APP, default_timeout=30).run()
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    next(button for button in app.button if button.label == "Read workbook").click().run()
    assert not app.exception
    assert next(box for box in app.selectbox if box.label == "Save under contract").value == CONTRACT
    assert next(button for button in app.button if button.label == "Save contract directory").disabled
    assert directory.load_directory(CONTRACT) == state
    next(box for box in app.checkbox if box.label ==
         "I reviewed all included sites and contacts and confirm this shared save").check().run()
    next(button for button in app.button if button.label == "Save contract directory").click().run()
    assert not app.exception
    assert not app.error, [error.value for error in app.error]

    saved = directory.load_directory(CONTRACT)
    assert saved.revision == 20
    assert saved.sites[0].key == state.sites[0].key
    contact, = saved.sites[0].contacts
    assert (contact.name, contact.phone, contact.email) == (
        "Synthetic Site Lead", "202-555-0019", "site@example.invalid")
    assert len(contact.source) <= 1000
    assert contact.source.endswith(saved.source_sha256 + ":Synthetic Provenance Sites!B9,B10,B11")
    assert (retention._sources() / (saved.source_sha256 + ".xlsx")).read_bytes() == raw
    for path, expected in {**originals, **history}.items():
        assert path.read_bytes() == expected

    # A new UI session reads the persisted version, independent of the import
    # session's staged workbook and editable widget state.
    reopened = AppTest.from_string(APP, default_timeout=30).run()
    reopened.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    reopened.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not reopened.exception and not reopened.error
    assert any("202-555-0019" in str(frame.value) for frame in reopened.dataframe)
    assert directory.load_directory(CONTRACT) == saved
