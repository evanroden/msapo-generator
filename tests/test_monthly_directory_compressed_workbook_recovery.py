"""Corrupt XLSX compression must be a recoverable directory import rejection."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import struct
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory, monthly_report_library as library
from app import monthly_report_directory_ui as ui
from test_monthly_report_directory import inspected, workbook

ERROR = "Workbook is invalid or contains unsafe XML; nothing was saved."
PARTS = (
    "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml",
    "xl/sharedStrings.xml", "xl/styles.xml",
)


def _book(compression=ZIP_DEFLATED):
    stream = BytesIO()
    with ZipFile(BytesIO(workbook())) as original, ZipFile(stream, "w", compression) as out:
        for info in original.infolist():
            out.writestr(info.filename, original.read(info.filename))
        out.writestr("xl/sharedStrings.xml", f'<sst xmlns="{directory.S[1:-1]}"><si><t>Unused source text</t></si></sst>')
        out.writestr("xl/styles.xml", f'<styleSheet xmlns="{directory.S[1:-1]}"><cellXfs><xf numFmtId="0"/></cellXfs></styleSheet>')
    return stream.getvalue()


def _damaged(raw, part):
    with ZipFile(BytesIO(raw)) as archive:
        member = archive.getinfo(part)
    assert member.compress_type == ZIP_DEFLATED and member.compress_size > 0
    name_length, extra_length = struct.unpack_from("<HH", raw, member.header_offset + 26)
    offset = member.header_offset + 30 + name_length + extra_length
    damaged = bytearray(raw)
    # BFINAL=1 and reserved BTYPE=3, while retaining all ZIP directory metadata.
    damaged[offset] = damaged[offset] & 0xF8 | 7
    result = bytes(damaged)
    with ZipFile(BytesIO(result)) as archive, pytest.raises(zlib.error):
        archive.read(part)
    return result


def _inventory(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("part", PARTS)
def test_damaged_member_has_recoverable_error_and_unchanged_input(part, tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = _damaged(_book(), part)
    original = raw[:]
    before = _inventory(tmp_path)
    with pytest.raises(ValueError, match="^" + ERROR.replace(".", r"\.") + "$") as result:
        directory.inspect_workbook(raw, number_formats=True)
    assert isinstance(result.value.__cause__, zlib.error)
    assert raw == original and _inventory(tmp_path) == before


@pytest.mark.parametrize("compression", (ZIP_STORED, ZIP_DEFLATED))
@pytest.mark.parametrize("number_formats", (False, True))
def test_valid_compression_and_saved_values_remain_unchanged(compression, number_formats):
    raw = _book(compression)
    book = directory.inspect_workbook(raw, number_formats=number_formats)
    expected = directory.inspect_workbook(workbook(), number_formats=number_formats)
    assert book.sha256 == sha256(raw).hexdigest()
    assert book.sheets == expected.sheets
    assert book.notices == expected.notices
    assert book.date1904 == expected.date1904


def test_unused_styles_are_not_newly_read_or_rewritten():
    raw = _damaged(_book(), "xl/styles.xml")
    # The ordinary directory route intentionally does not inspect optional formats.
    assert directory.inspect_workbook(raw).sheets == directory.inspect_workbook(workbook()).sheets


@pytest.mark.parametrize("part", ("xl/workbook.xml", "xl/worksheets/sheet1.xml"))
def test_rejected_save_preserves_current_history_originals_and_other_contract(part, tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw, book, sheet, sites = inspected()
    first = directory.save_directory("Synthetic Contract", sites, expected_revision=0,
        actor="Synthetic Editor", confirmed=True, raw=raw, source_sha256=book.sha256, source_sheet=sheet.name)
    other = directory.save_directory("Synthetic Neighbor", sites, expected_revision=0,
        actor="Synthetic Neighbor Editor", confirmed=True)
    before = _inventory(tmp_path)
    bad = _damaged(raw, part)
    changed = (replace(sites[0], address="300 Synthetic Corrected Road"), *sites[1:])
    with pytest.raises(ValueError, match="Workbook is invalid"):
        directory.save_directory(first.contract, changed, expected_revision=1,
            actor="Synthetic Editor", confirmed=True, raw=bad,
            source_sha256=sha256(bad).hexdigest(), source_sheet=sheet.name)
    assert _inventory(tmp_path) == before
    assert directory.load_directory(first.contract) == first
    assert directory.load_directory(first.contract, 1) == first
    assert directory.load_directory(other.contract) == other
    # A valid retry remains deliberate and revision checked.
    with pytest.raises(library.LibraryError):
        directory.save_directory(first.contract, changed, expected_revision=1,
            actor="Synthetic Editor", confirmed=False, raw=raw,
            source_sha256=book.sha256, source_sheet=sheet.name)
    assert _inventory(tmp_path) == before
    second = directory.save_directory(first.contract, changed, expected_revision=1,
        actor="Synthetic Editor", confirmed=True, raw=raw,
        source_sha256=book.sha256, source_sheet=sheet.name)
    assert second.revision == 2 and second.sites == changed
    assert directory.load_directory(first.contract, 1) == first
    assert directory.load_directory(other.contract) == other
    with pytest.raises(library.RevisionConflict):
        directory.save_directory(first.contract, sites, expected_revision=1,
            actor="Synthetic Editor", confirmed=True)
    for path, value in before.items():
        if "/history/" in path or path.endswith(".xlsx"):
            assert (tmp_path / path).read_bytes() == value


SCRIPT = '''
import streamlit as st
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
st.session_state.setdefault("report_directory_actor", "Synthetic Editor")
render_directory(_field)
'''


def _launch(monkeypatch, payload, *, mode="Import a workbook"):
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **k: BytesIO(payload[0]))
    monkeypatch.setattr(ui, "contract_choices", lambda: ("Synthetic Contract",))
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["report_directory_mode"] = mode
    return app.run()


def _click(app, label):
    return next(item for item in app.button if item.label == label).click().run()


@pytest.mark.parametrize("mode", ("Import a workbook", "Import all contract contacts"))
def test_actual_upload_ui_contains_decoder_failure_and_allows_retry(mode, tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw, book, sheet, sites = inspected()
    first = directory.save_directory("Synthetic Contract", sites, expected_revision=0,
        actor="Synthetic Editor", confirmed=True, raw=raw, source_sha256=book.sha256, source_sheet=sheet.name)
    payload = [_damaged(raw, "xl/worksheets/sheet1.xml")]
    app = _launch(monkeypatch, payload, mode=mode)
    assert not app.exception
    before = _inventory(tmp_path)
    _click(app, "Read workbook")
    assert not app.exception
    assert any(item.value == ui.literal(ERROR) for item in app.error)
    assert not next(item for item in app.button if item.label == "Read workbook").disabled
    assert "report_directory_workbook" not in app.session_state.filtered_state
    assert _inventory(tmp_path) == before
    payload[0] = raw
    _click(app, "Read workbook")
    assert not app.exception
    assert app.session_state["report_directory_workbook"] == (raw, book)
    assert directory.load_directory(first.contract) == first
    assert _inventory(tmp_path) == before
    if mode == "Import a workbook":
        assert next(item for item in app.button if item.label == "Save contract directory").disabled
        next(item for item in app.checkbox if item.label ==
             "I reviewed all included sites and contacts and confirm this shared save").check().run()
        _click(app, "Save contract directory")
        assert not app.exception
        assert directory.load_directory(first.contract).revision == 2
        assert directory.load_directory(first.contract, 1) == first
        app.run()
        assert not app.exception and directory.load_directory(first.contract).revision == 2


def test_failed_replacement_keeps_staged_original_for_next_render(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = workbook()
    payload = [raw]
    app = _launch(monkeypatch, payload)
    _click(app, "Read workbook")
    assert not app.exception
    before = app.session_state["report_directory_workbook"]
    payload[0] = _damaged(raw, "xl/workbook.xml")
    _click(app, "Read workbook")
    assert not app.exception and any(item.value == ui.literal(ERROR) for item in app.error)
    assert app.session_state["report_directory_workbook"] == before
    # This does not claim #589's pending mapping controls survive the error rerun.
    app.run()
    assert not app.exception
    assert app.session_state["report_directory_workbook"] == before
    assert next(item for item in app.selectbox if item.label == "Contract worksheet")


def test_unrelated_programming_error_is_not_relabelled(monkeypatch):
    def fail(*args, **kwargs):
        raise TypeError("Synthetic programming fault")
    monkeypatch.setattr(directory, "_workbook_metadata", fail)
    with pytest.raises(TypeError, match="Synthetic programming fault"):
        directory.inspect_workbook(workbook())
