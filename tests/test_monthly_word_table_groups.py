"""Synthetic Word table band, cell-pointer and conservative editor regressions (A40).

No client documents or report-derived fixture bytes are committed.
"""
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
import pytest

from app.monthly_report_import import ImportMapping, inspect_docx, map_items
from app.monthly_report_sections import table_without_prices
from app.monthly_report_vendor_groups import grouped_vendor_contacts
from app.monthly_report_source_table_roles import native_table_class


def _set_header(row):
    row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))


def _fill(row, values):
    for cell, value in zip(row.cells, values):
        cell.text = value


def _fixture(tmp_path):
    doc = Document()
    doc.add_heading("5 Maintenance Schedule", 1)
    calls = doc.add_table(rows=4, cols=5)
    calls.cell(0, 0).merge(calls.cell(0, 4)).text = "Client Service Calls"
    headings = ("WO", "Finish Date", "Area", "Task Code/Description", "Tag")
    _fill(calls.rows[1], headings)
    # A two-level title/header is structural even if Word lacks tblHeader.
    _fill(calls.rows[2], ("SC-07", "2026-09-14", "Mechanical", "Inspected filter", "AHU-7"))
    _fill(calls.rows[3], headings)
    _set_header(calls.rows[3])  # Native repeated page header, not a service call.
    doc.add_heading("6 Sub-Contractor Status", 1)
    vendors = doc.add_table(rows=5, cols=3)
    _fill(vendors.rows[0], ("Vendor", "Phone", "Email"))
    vendors.cell(1, 0).merge(vendors.cell(1, 2)).text = "Electrical"
    _fill(vendors.rows[2], ("Synthetic Wire Co", "555-0101", "wire@example.invalid"))
    vendors.cell(3, 0).merge(vendors.cell(3, 2)).text = "Mechanical"
    _fill(vendors.rows[4], ("Synthetic Air Co", "555-0102", "air@example.invalid"))
    doc.add_heading("7 Water Treatment Reports", 1)
    summary = doc.add_table(rows=3, cols=3)
    summary.cell(0, 0).merge(summary.cell(0, 2)).text = "Synthetic Water Summary"
    _fill(summary.rows[1], ("Sample", "Value", "Note"))
    # A second-level native heading need not carry the tblHeader flag.
    _fill(summary.rows[2], ("Tower A", "0", "Checked"))
    # A nested grid cannot masquerade as one flat parent data row.
    outer = doc.add_table(rows=1, cols=1)
    nested = outer.cell(0, 0).add_table(rows=2, cols=2)
    _fill(nested.rows[0], ("Code", "Status"))
    _fill(nested.rows[1], ("N-1", "Pending"))
    path = tmp_path / "a40-synthetic-word-bands.docx"
    doc.save(path)
    return path


def _table(inspection, text):
    return next(item for item in inspection.items if item.kind == "table"
                and any(text in cell for row in item.rows for cell in row))


def test_native_cell_coordinates_and_groups_are_lossless(tmp_path):
    path = _fixture(tmp_path)
    initial = path.read_bytes()
    inspected = inspect_docx(path)
    calls = _table(inspected, "Client Service Calls")
    vendors = _table(inspected, "Synthetic Wire Co")
    summary = _table(inspected, "Synthetic Water Summary")
    assert calls.rows[2] == ("SC-07", "2026-09-14", "Mechanical", "Inspected filter", "AHU-7")
    assert calls.table_header_row == 1
    assert native_table_class(calls) == "service_calls"
    assert len(calls.table_cell_refs) == 16
    assert calls.table_cell_refs[0] == (0, 0, 0, 5, "")
    assert calls.table_row_roles == ("title_band", "header", "data", "repeated_header")
    assert calls.table_row_groups == (0, 0, 0, 0)
    assert vendors.merged_title_rows == (1, 3)
    assert native_table_class(vendors) == "vendor_contacts"
    assert vendors.table_cell_refs[4] == (2, 0, 0, 1, "")
    assert vendors.table_row_roles == ("header", "group_band", "data", "group_band", "data")
    assert vendors.table_row_groups == (0, 1, 1, 2, 2)
    assert len(vendors.table_cell_refs) == 11
    assert len(summary.table_cell_refs) == 7
    assert summary.table_row_roles == ("title_band", "header", "data")
    assert summary.rows[-1] == ("Tower A", "0", "Checked")
    assert native_table_class(summary) == ""
    assert path.read_bytes() == initial
    assert inspect_docx(path).items == inspected.items


def test_typed_tables_skip_only_proven_repeated_native_header(tmp_path):
    path = _fixture(tmp_path)
    inspection = inspect_docx(path)
    calls = _table(inspection, "Client Service Calls")
    native, removed = table_without_prices(calls)
    assert not removed
    assert native.columns == ("WO", "Finish Date", "Area", "Task Code/Description", "Tag")
    assert native.rows == (("SC-07", "2026-09-14", "Mechanical", "Inspected filter", "AHU-7"),)
    mapped = map_items(path, inspection, (ImportMapping(calls.id, "service_calls"),))
    assert mapped.blocks[0].rows == native.rows
    assert mapped.blocks[0].references == (f"docx:{inspection.sha256}:{calls.id}",)
    vendors = _table(inspection, "Synthetic Wire Co")
    grouped = grouped_vendor_contacts(vendors)
    assert grouped is not None
    assert [row[0] for row in grouped.rows] == ["Electrical", "Mechanical"]
    assert [row[1] for row in grouped.rows] == ["Synthetic Wire Co", "Synthetic Air Co"]


def test_unclassified_bands_and_nested_grid_are_not_invented_work(tmp_path):
    path = _fixture(tmp_path)
    inspection = inspect_docx(path)
    summary = _table(inspection, "Synthetic Water Summary")
    assert summary.rows[0] == ("Synthetic Water Summary", "", "")
    assert summary.rows[2] == ("Tower A", "0", "Checked")
    assert any(i.kind == "unsupported" and "nested" in i.note.lower() for i in inspection.items)
    assert not any(i.kind == "table" and "N-1" in str(i.rows)
                   and i.table_header_row == 0 and "Pending" in str(i.rows)
                   and "Code" not in str(i.rows) for i in inspection.items)




def test_ambiguous_group_band_is_never_promoted_to_a_contact(tmp_path):
    from app.monthly_report_source_table_roles import native_table_class
    path = _fixture(tmp_path)
    doc = Document(path)
    doc.tables[1].cell(2, 0).text = ""  # Contact identity is absent.
    doc.save(path)
    inspection = inspect_docx(path)
    vendors = _table(inspection, "Synthetic Air Co")
    assert vendors.table_row_roles == ("header", "group_band", "data", "group_band", "data")
    assert grouped_vendor_contacts(vendors) is None
    assert native_table_class(vendors) == ""
    # No replacement row is invented; the full original grid remains available.
    assert vendors.rows[2] == ("", "555-0101", "wire@example.invalid")
    assert len(vendors.table_cell_refs) == 11



def test_grid_before_after_vertical_merge_and_unlisted_columns(tmp_path):
    from docx.oxml.ns import qn
    doc = Document()
    doc.add_heading("7 Water Treatment Reports", 1)
    table = doc.add_table(rows=2, cols=2)
    _fill(table.rows[0], ("Left", "Right"))
    _fill(table.rows[1], ("", "0"))
    for row in table.rows:
        before = OxmlElement("w:gridBefore")
        before.set(qn("w:val"), "1")
        row._tr.get_or_add_trPr().append(before)
    after = OxmlElement("w:gridAfter")
    after.set(qn("w:val"), "2")
    table.rows[1]._tr.get_or_add_trPr().append(after)
    for index, state in ((0, "restart"), (1, "continue")):
        merge = OxmlElement("w:vMerge")
        merge.set(qn("w:val"), state)
        table.cell(index, 0)._tc.get_or_add_tcPr().append(merge)
    path = tmp_path / "native-indents.docx"
    doc.save(path)
    source_bytes = path.read_bytes()
    found = next(i for i in inspect_docx(path).items if i.kind == "table")
    assert all(len(row) == 5 for row in found.rows)
    assert found.rows[0] == ("", "Left", "Right", "", "")
    assert found.rows[1] == ("", "", "0", "", "")
    assert found.table_cell_refs == ((0, 0, 1, 1, "restart"), (0, 1, 2, 1, ""),
                                     (1, 0, 1, 1, "continue"), (1, 1, 2, 1, ""))
    assert path.read_bytes() == source_bytes


def test_saved_native_docx_contains_only_real_call_and_reloads(tmp_path, monkeypatch):
    import hashlib
    from app import monthly_report_library as library
    from app.monthly_report_model import synthetic_profiles
    from app.monthly_report_native_layout import _table as write_native_table
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    path = _fixture(tmp_path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    calls = _table(inspection, "Client Service Calls")
    mapped = map_items(path, inspection, (ImportMapping(calls.id, "service_calls"),))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic A40", confirmed=True)
    saved = library.save_import(profile.contract, profile.key, mapped.blocks, overrides=mapped.overrides,
                                expected_revision=1, actor="Synthetic A40", confirmed=True)
    reloaded = library.load_profile(profile.contract, profile.key)
    assert saved.revision == reloaded.revision == 2
    assert reloaded.block("service_calls").rows == mapped.blocks[0].rows
    assert reloaded.block("service_calls").references == mapped.blocks[0].references
    native = table_without_prices(calls)[0]
    output = Document()
    table = output.add_table(rows=2, cols=len(native.columns))
    write_native_table(table._tbl, native.columns, native.rows)
    data = BytesIO()
    output.save(data)
    assert len(hashlib.sha256(data.getvalue()).hexdigest()) == 64
    rows = [tuple(cell.text for cell in row.cells) for row in Document(BytesIO(data.getvalue())).tables[0].rows]
    assert rows == [native.columns, *native.rows]
    assert path.read_bytes() == original



@pytest.mark.parametrize("contents", [b"", b"not a docx", b"PK\\x03\\x04broken"])
def test_invalid_word_input_is_rejected_without_partial_state(tmp_path, contents):
    from app.monthly_report_import import ImportError
    path = tmp_path / "invalid.docx"
    path.write_bytes(contents)
    with pytest.raises((ImportError, ValueError)):
        inspect_docx(path)
