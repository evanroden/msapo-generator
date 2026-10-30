"""A rejected repeated Capital source leaves corrected preview/Word/PDF intact."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

import pymupdf
import pytest
from docx import Document

from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_preview import section_preview_docx
from app.monthly_report_setup import new_month_draft
from app.monthly_report_start_replay import merge_starting_drafts
from app.pdf_converter import convert_to_pdf
from tests.conftest import requires_libreoffice
from test_monthly_report_capital_source_replay import source, block, change, import_source, NEXT, KEYS


def prepared(source):
    path, original, initial = source
    table = block(initial, KEYS[0]).extra_tables[0]
    rows = (table.rows[1], (*table.rows[2][:-1], "Verified note"))
    current = change(new_month_draft(initial, NEXT), KEYS[0],
                     extra_tables=(replace(table, rows=rows),))
    with pytest.raises(ValueError, match="Capital.*already contains"):
        merge_starting_drafts(current, import_source(path, initial.profile, NEXT))
    focused = replace(current, sections=tuple(replace(section, included=section.key == "capital")
                                              for section in current.sections))
    assert not [check for check in preflight(focused) if check.blocking]
    return path, original, focused


def assert_word(raw):
    word = Document(BytesIO(raw))
    cells = [cell.text for table in word.tables for row in table.rows for cell in row.cells]
    assert cells.count("Review roof") == cells.count("Review controls") == 1
    assert cells.count("Verified note") == 1
    assert "Renew north pump" not in cells and "First occurrence" not in cells
    assert cells.count("CH-001") == cells.count("CH-002") == 1
    assert "Distinct source row" in cells and "Closed" in cells


def test_corrected_capital_section_preview_survives_rejected_import(source):
    path, original, draft = prepared(source)
    assert_word(section_preview_docx(draft, "capital"))
    assert path.read_bytes() == original


@requires_libreoffice
@pytest.mark.parametrize("native", (False, True))
def test_corrected_capital_actual_word_pdf_preserves_cells_once(source, tmp_path, native):
    path, original, draft = prepared(source)
    raw = (build_native_docx(draft, path, section_key="capital") if native else
           assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint))
    assert_word(raw)
    out = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "capital-source-replay" / ("native" if native else "plain")
    out.mkdir(parents=True, exist_ok=True)
    docx = out / "capital.docx"
    docx.write_bytes(raw)
    pdf_path = convert_to_pdf(docx)
    pdf_bytes = pdf_path.read_bytes()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        text = " ".join(" ".join(page.get_text().split()) for page in pdf)
        assert text.count("Review roof") == text.count("Review controls") == 1
        assert text.count("Verified note") == 1
        assert "Renew north pump" not in text and "First occurrence" not in text
        assert text.count("CH-001") == text.count("CH-002") == 1
        assert "Distinct source row" in text and "Closed" in text
        for number, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(out / f"page-{number}.png")
        manifest = {"pages": len(pdf), "docx_sha256": sha256(raw).hexdigest(),
                    "pdf_sha256": sha256(pdf_bytes).hexdigest(),
                    "original_unchanged": path.read_bytes() == original}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    assert path.read_bytes() == original
