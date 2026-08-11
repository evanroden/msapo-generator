from pathlib import Path
from unittest.mock import Mock

from docx import Document

from app import document_generator
from app.quote_analyzer import QuoteAnalysis


def _make_template(path: Path) -> None:
    doc = Document()
    doc.add_paragraph(document_generator.SCOPE_SENTINEL)
    doc.save(path)


def test_repeated_generations_use_distinct_paths(tmp_path, monkeypatch):
    template = tmp_path / "template.docx"
    output = tmp_path / "output"
    output.mkdir()
    _make_template(template)

    monkeypatch.setattr(document_generator, "TEMPLATE_PATH", template)
    monkeypatch.setattr(document_generator, "OUTPUT_DIR", output)

    analysis = QuoteAnalysis(
        vendor_name="Vendor",
        project_description="Pump repair",
        scope_of_work="Repair the pump.",
    )

    first = document_generator.generate_docx(
        analysis,
        final_inclusions=[],
        final_exclusions=[],
        output_name="Test MSAPO",
    )
    second = document_generator.generate_docx(
        analysis,
        final_inclusions=[],
        final_exclusions=[],
        output_name="Test MSAPO",
    )

    assert first != second
    assert first.exists()
    assert second.exists()
    assert first.parent == output
    assert second.parent == output


def test_cleanup_sweep_runs_only_once_per_process(monkeypatch):
    iterdir = Mock(return_value=[])
    output_dir = Mock()
    output_dir.iterdir = iterdir
    monkeypatch.setattr(document_generator, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(document_generator, "_cleanup_done", False)

    document_generator._cleanup_old_outputs()
    document_generator._cleanup_old_outputs()

    iterdir.assert_called_once_with()
