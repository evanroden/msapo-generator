"""A rejected replacement must not unmount the last successful directory review."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from test_monthly_report_directory_batch import detail, summary, workbook

APP = '''
import streamlit as st
from unittest.mock import patch
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
with patch.object(st, "file_uploader", return_value=st.session_state.get("test_upload")):
    render_directory(_field)
'''
SINGLE = "Import a workbook"
BATCH = "Import all contract contacts"
CONTRACT = "Synthetic Recovery Contract"


def control(items, label):
    return next(item for item in items if item.label == label)


def read(app):
    return control(app.button, "Read workbook")


def confirm(app):
    return next(item for item in app.checkbox if item.label.startswith("I reviewed"))


def save(app, mode):
    return control(app.button, "Save contract directory" if mode == SINGLE else "Save all reviewed contacts")


def bytes_on_disk(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def source(name=CONTRACT):
    return workbook((("Active Contracts", summary(B6=name)),
                     (name + " Sites", detail())))


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def launch(raw, mode):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["test_upload"] = BytesIO(raw)
    app.session_state["report_directory_actor"] = "Synthetic Reviewer"
    app.session_state["report_directory_mode"] = mode
    app.run()
    read(app).click().run()
    assert not app.exception
    if mode == SINGLE:
        control(app.selectbox, "Contract worksheet").select(CONTRACT + " Sites").run()
        # A deliberate mapping change; unlike default 7, 0 omits the address.
        control(app.number_input, "Address row (0 if absent)").set_value(0).run()
    else:
        control(app.multiselect, "Create these new contracts").set_value([CONTRACT]).run()
    confirm(app).check().run()
    assert not save(app, mode).disabled
    return app


def bad_xml():
    raw = source("Synthetic Replacement")
    target = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(target, "w", ZIP_DEFLATED) as changed:
        for item in original.infolist():
            changed.writestr(item, b"<broken" if item.filename == "xl/worksheets/sheet1.xml"
                             else original.read(item.filename))
    return target.getvalue()


@pytest.mark.parametrize("mode", [SINGLE, BATCH])
@pytest.mark.parametrize("failure", ["zip", "xml", "size", "io"])
def test_failed_read_retains_visible_review_mapping_and_confirmation(monkeypatch, tmp_path, mode, failure):
    raw = source()
    app = launch(raw, mode)
    old_stage = app.session_state["report_directory_workbook"]
    old_confirm = confirm(app).id
    disk = bytes_on_disk(tmp_path)
    calls = []
    inspect = directory.inspect_workbook

    def checked(value, **kwargs):
        calls.append(value)
        if failure == "io":
            raise OSError("Synthetic workbook read unavailable")
        return inspect(value, **kwargs)

    monkeypatch.setattr(directory, "inspect_workbook", checked)
    if failure == "size":
        monkeypatch.setattr(directory, "MAX_UPLOAD_BYTES", 8)
    app.session_state["test_upload"] = BytesIO(b"invalid workbook" if failure in {"zip", "size", "io"} else bad_xml())
    read(app).click().run()
    assert not app.exception and app.error
    assert app.session_state["report_directory_workbook"] == old_stage
    assert any(b.label == save_label(mode) for b in app.button), "Failed read unmounted retained review"
    assert confirm(app).id == old_confirm and confirm(app).value
    if mode == SINGLE:
        assert control(app.number_input, "Address row (0 if absent)").value == 0
    else:
        assert control(app.multiselect, "Create these new contracts").value == [CONTRACT]
    assert len(calls) == 1 and bytes_on_disk(tmp_path) == disk
    app.run()
    assert not app.exception and len(calls) == 1
    assert confirm(app).id == old_confirm and confirm(app).value
    assert app.session_state["report_directory_workbook"] == old_stage
    assert bytes_on_disk(tmp_path) == disk


def save_label(mode):
    return "Save contract directory" if mode == SINGLE else "Save all reviewed contacts"


@pytest.mark.parametrize("mode", [SINGLE, BATCH])
def test_valid_replacement_installs_new_workbook_and_requires_its_review(mode, tmp_path):
    app = launch(source(), mode)
    old_confirm = confirm(app).id
    raw = source("Synthetic Replacement")
    app.session_state["test_upload"] = BytesIO(raw)
    read(app).click().run()
    assert not app.exception and not app.error
    assert app.session_state["report_directory_workbook"][0] == raw
    if mode == SINGLE:
        control(app.selectbox, "Contract worksheet").select("Synthetic Replacement Sites").run()
    else:
        control(app.multiselect, "Create these new contracts").set_value(["Synthetic Replacement"]).run()
    assert confirm(app).id != old_confirm and not confirm(app).value
    assert save(app, mode).disabled
    assert directory.load_directory(CONTRACT) is None
    assert directory.load_directory("Synthetic Replacement") is None


@pytest.mark.parametrize("mode", [SINGLE, BATCH])
def test_retained_review_can_be_saved_without_reupload_and_other_directory_is_unchanged(mode, tmp_path):
    # Standing data and its history are independent of a staged import.
    other = directory.save_directory("Synthetic Other Contract", (), expected_revision=0,
        actor="Synthetic Other Reviewer", confirmed=True,
        contract_contacts=(directory.DirectoryContact("Manager", "Synthetic Other Person"),))
    before = bytes_on_disk(tmp_path)
    raw = source()
    app = launch(raw, mode)
    app.session_state["test_upload"] = BytesIO(b"invalid workbook")
    read(app).click().run()
    assert not app.exception and not save(app, mode).disabled
    assert bytes_on_disk(tmp_path) == before
    save(app, mode).click().run()
    assert not app.exception and app.success
    saved = directory.load_directory(CONTRACT)
    assert saved.revision == 1 and saved.source_sha256 == directory.inspect_workbook(raw).sha256
    assert saved.sites[0].contacts[0].name == "Synthetic Site Lead"
    assert saved.sites[0].address == ("" if mode == SINGLE else "100 Example Way")
    assert directory.load_directory(CONTRACT, 1) == saved
    assert directory.load_directory(other.contract) == other
    for path, value in before.items():
        assert (tmp_path / path).read_bytes() == value
    # Explicit re-entry through saved-directory UI, not just cached preview.
    reopened = AppTest.from_string(APP, default_timeout=30)
    reopened.session_state["report_directory_actor"] = "Synthetic Reopening Reviewer"
    reopened.session_state["report_directory_mode"] = "Review saved directory"
    reopened.session_state["report_directory_existing"] = CONTRACT
    reopened.run()
    assert not reopened.exception
    assert any("Synthetic Site Lead" in str(frame.value.to_dict()) for frame in reopened.dataframe)
    assert directory.load_directory(CONTRACT).revision == 1


@pytest.mark.parametrize("mode", [SINGLE, BATCH])
def test_explicit_retry_recovers_and_neutral_reruns_do_not_parse(monkeypatch, mode):
    raw = source()
    app = launch(raw, mode)
    attempts = []
    inspect = directory.inspect_workbook
    replacement = source("Synthetic Retry Contract")

    def flaky(value, **kwargs):
        attempts.append(value)
        if len(attempts) == 1:
            raise OSError("Synthetic temporary failure")
        return inspect(value, **kwargs)

    monkeypatch.setattr(directory, "inspect_workbook", flaky)
    app.session_state["test_upload"] = BytesIO(replacement)
    read(app).click().run()
    assert app.error and len(attempts) == 1
    app.run()
    assert len(attempts) == 1 and app.session_state["report_directory_workbook"][0] == raw
    read(app).click().run()
    assert not app.exception and not app.error and len(attempts) == 2
    assert app.session_state["report_directory_workbook"][0] == replacement
    assert directory.load_directory(CONTRACT) is None


@pytest.mark.parametrize("mode", [SINGLE, BATCH])
def test_selected_but_unread_or_cleared_upload_keeps_old_review_labeled(mode):
    raw = source()
    app = launch(raw, mode)
    for selected in (BytesIO(source("Synthetic Unread")), None):
        app.session_state["test_upload"] = selected
        app.run()
        assert not app.exception
        assert app.session_state["report_directory_workbook"][0] == raw
        assert any("last successfully read workbook" in c.value for c in app.caption)
        assert not save(app, mode).disabled
    assert read(app).disabled


def test_same_event_mapping_correction_and_failed_read_preserve_choice_but_invalidate_confirmation():
    app = launch(source(), SINGLE)
    control(app.number_input, "Address row (0 if absent)").set_value(7).run()
    confirm(app).check().run()
    confirmed_id = confirm(app).id
    app.session_state["test_upload"] = BytesIO(b"invalid workbook")
    control(app.number_input, "Address row (0 if absent)").set_value(0)
    read(app).click().run()
    assert not app.exception and app.error
    assert control(app.number_input, "Address row (0 if absent)").value == 0
    assert confirm(app).id != confirmed_id and not confirm(app).value
    assert save(app, SINGLE).disabled
    assert directory.load_directory(CONTRACT) is None


def test_first_failed_read_has_no_previous_review_claim_and_can_retry():
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["report_directory_actor"] = "Synthetic Reviewer"
    app.session_state["test_upload"] = BytesIO(b"invalid workbook")
    app.run()
    read(app).click().run()
    assert not app.exception and app.error
    assert "report_directory_workbook" not in app.session_state
    assert not any("previous workbook review" in message.value for message in app.info)
    assert not any(b.label.startswith("Save ") for b in app.button)
    app.session_state["test_upload"] = BytesIO(source())
    read(app).click().run()
    assert not app.exception and not app.error
    assert app.session_state["report_directory_workbook"][0] == source_bytes(app)


def source_bytes(app):
    return app.session_state["test_upload"].getvalue()


def test_upload_read_failure_preserves_review_without_calling_parser(monkeypatch):
    app = launch(source(), SINGLE)
    old = app.session_state["report_directory_workbook"]

    class UnavailableUpload:
        def getvalue(self):
            raise OSError("Synthetic upload read failed")

    def forbidden(*args, **kwargs):
        raise AssertionError("No bytes were available to parse")

    monkeypatch.setattr(directory, "inspect_workbook", forbidden)
    app.session_state["test_upload"] = UnavailableUpload()
    read(app).click().run()
    assert not app.exception and app.error
    assert app.session_state["report_directory_workbook"] == old
    assert control(app.number_input, "Address row (0 if absent)").value == 0
    assert confirm(app).value
