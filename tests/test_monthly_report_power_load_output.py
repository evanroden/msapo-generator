"""Synthetic power loads retain editable values across shared report paths."""
from io import BytesIO
import re

import pytest
from docx import Document

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_content_policy import price_free_table
from app.monthly_report_docx import generate_report
from app.monthly_report_guided import client_table_draft
from app.monthly_report_model import BlockSpec, ColumnSpec, ResolvedBlock
from conftest import requires_libreoffice
import test_monthly_engineering_estimate_columns as engineering


@pytest.mark.parametrize("unit", ("W", "kW", "MW"))
def test_power_schema_filters_only_the_price_column(unit):
    title = f"Est. Peak Coincident Load ({unit})"
    spec = BlockSpec("thermal_capacity", "table", columns=(
        ColumnSpec("site", "Facility"), ColumnSpec("load", title),
        ColumnSpec("price", "Unit Price"),
    ))
    block = ResolvedBlock("thermal_capacity", "This month",
                          rows=(("Synthetic generator A", "173", "$9300"),))
    safe_spec, safe, removed = price_free_table(spec, block)
    assert tuple(column.title for column in safe_spec.columns) == ("Facility", title)
    assert safe.rows == (("Synthetic generator A", "173"),)
    assert removed == ("Unit Price",)
    assert block.rows == (("Synthetic generator A", "173", "$9300"),)
    assert price_free_table(safe_spec, safe) == (safe_spec, safe, ())


@requires_libreoffice
@pytest.mark.parametrize("unit", ("W", "kW", "MW"))
def test_native_power_load_import_reload_and_word_pdf(monkeypatch, tmp_path, unit):
    import fitz

    # Keep the existing independent values and real native-layout journey;
    # vary only the unit-qualified headings, never client content.
    tables = tuple((tuple(title.replace("Tons", unit).replace("MBH", unit)
                          for title in columns), rows)
                   for columns, rows in engineering.SOURCE_TABLES)
    monkeypatch.setattr(engineering, "SOURCE_TABLES", tables)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    path = engineering._source_file(tmp_path)
    original = path.read_bytes()
    inspection, draft = engineering._import(path)
    engineering._assert_engineering_tables(draft)
    working, removed_again = client_table_draft(draft)
    assert working == draft and not removed_again
    engineering._save_import(draft, path, inspection)
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor=engineering.ACTOR)
    restored = library.load_snapshot(engineering.PROFILE.contract,
                                    engineering.PROFILE.key, engineering.PERIOD)
    assert restored == saved
    assert not [check for check in preflight(restored.draft) if check.blocking]
    package = generate_report(restored.draft,
                              acknowledged_fingerprint=restored.draft.fingerprint)
    # Keep first output bytes before checking the independent expected values.
    if package.docx:
        (tmp_path / "generated.docx").write_bytes(package.docx)
    if package.pdf:
        (tmp_path / "generated.pdf").write_bytes(package.pdf)
    assert package.docx and package.pdf, package.pdf_error
    engineering._assert_native_tables(package.docx, path)
    result = Document(BytesIO(package.docx))
    assert len(result.tables) == 2
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    for _, rows in tables:
        for row in rows:
            assert row[0] in text
            for value in row[1:3]:
                assert re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d.])", text)
            assert row[3] not in text and row[3].lstrip("$") not in text
    assert "Unit Price" not in text and "Cost" not in text
    assert library.load_imported_draft(engineering.PROFILE.contract,
                                       engineering.PROFILE.key) == draft
    assert path.read_bytes() == original
    assert library.imported_original(engineering.PROFILE.contract,
                                     engineering.PROFILE.key).read_bytes() == original
