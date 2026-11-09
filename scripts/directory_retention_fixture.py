"""Generate the invented #291 comparison workbook, not a tracked binary fixture.

Cells and sheet visibility match the original November 6 synthetic workbook.
Fixed document properties and ZIP headers make the new generation reproducible
with the locked openpyxl dependency. This deliberately does NOT reconstruct the
historical ZIP bytes or replace historical evidence identified by 32f56e5c….
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

FIXTURE_NAME = "synthetic-retention.xlsx"
FIXTURE_SHA = "854e76ae35afc67f7a6cfbbd2162ac02c6fe2c89e15a476d6aa0e2cbabb23baa"
FIXED_TIME = datetime(2000, 1, 1)
ZIP_TIME = (2000, 1, 1, 0, 0, 0)


def workbook_bytes() -> bytes:
    """Create ordinary spreadsheet cells through openpyxl's workbook API."""
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Active Contracts"
    for cell, value in {
        "A6": "Contract", "B6": "Synthetic Retention", "A7": "Address", "B7": "100 Example Way",
        "A9": "Executive Director", "B9": "Synthetic Accepted Executive", "A10": "Phone", "B10": "202-555-0100",
        "A11": "Email", "B11": "executive@example.invalid", "C6": "INACTIVE Synthetic Closed",
        "C9": "Synthetic Inactive Person", "C11": "inactive@example.invalid",
    }.items():
        summary[cell] = value
    detail = workbook.create_sheet("Synthetic Retention Sites")
    for cell, value in {
        "A6": "Facility", "B6": "Synthetic North", "A7": "Address", "B7": "200 Example Way",
        "A9": "Facility Director", "B9": "Synthetic Accepted Site Lead", "A10": "Phone", "B10": "202-555-0101",
        "A11": "Email", "B11": "site@example.invalid",
    }.items():
        detail[cell] = value
    hidden = workbook.create_sheet("Hidden Retention Archive")
    hidden.sheet_state = "hidden"
    for cell, value in {"A6": "Facility", "B6": "Synthetic Hidden Site", "A9": "Facility Director",
                        "B9": "Synthetic Hidden Person"}.items():
        hidden[cell] = value
    workbook.create_sheet("Index")["A1"] = "Synthetic excluded index marker"
    workbook.properties.creator = "Synthetic Directory Retention QA"
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    generated = BytesIO()
    # ExcelWriter preserves explicitly supplied properties; Workbook.save would
    # overwrite modified with wall-clock time. All XML is openpyxl-generated.
    with ZipFile(generated, "w", ZIP_DEFLATED) as archive:
        ExcelWriter(workbook, archive).write_data()
    workbook.close()
    result = BytesIO()
    # Normalize only ZIP packaging, not workbook XML. Stored entries avoid
    # compression-library variations, OS permission bits and current timestamps.
    with ZipFile(generated, "r") as source, ZipFile(result, "w", ZIP_STORED) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_STORED
            target.writestr(info, source.read(name))
    return result.getvalue()


def write_fixture(output: Path) -> Path:
    """Emit once inside the caller's newly created, empty owned directory."""
    if (not output.is_absolute() or output.resolve() != output or output.is_symlink()
            or not output.is_dir() or any(output.iterdir())):
        raise ValueError("Fixture requires a new empty owned output directory")
    raw = workbook_bytes()
    if sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError("Generated fixture differs from its pinned identity; check locked dependencies")
    target = output / FIXTURE_NAME
    with target.open("xb") as stream:
        stream.write(raw)
    return target
