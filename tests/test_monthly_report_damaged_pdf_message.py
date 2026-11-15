"""A damaged PDF gets the same actionable message as other damaged files."""
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles


@pytest.fixture
def scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def test_damaged_pdf_message_is_actionable_and_valid_sibling_is_kept(scoped):
    batch = (("bad.pdf", b"%PDF-1.4\nsynthetic broken"),
             ("good.txt", b"Completed synthetic pump inspection."))
    accepted, messages = sources.ingest_batch(scoped, batch)
    assert [item.source.filename for item in accepted] == ["good.txt"]
    pdf_messages = [m for m in messages if "bad.pdf" in m]
    assert len(pdf_messages) == 1
    assert "Export a fresh copy" in pdf_messages[0]
    assert "Failed to open stream" not in pdf_messages[0]
