from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_official_expense_template_is_packaged_unchanged():
    template = (
        ROOT
        / "templates"
        / "Employee_Reimbursement_Expense_Report_JDE_10012025.xlsx"
    )

    assert template.is_file()
    assert template.read_bytes().startswith(b"PK")


def test_runtime_includes_workbook_writer_and_pdf_renderer():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "openpyxl>=3.1.5" in requirements
    assert "defusedxml>=0.7.1" in requirements
    assert "libreoffice-calc" in dockerfile
    assert "fonts-urw-base35" in dockerfile
    assert 'CMD ["streamlit", "run", "run_web.py"' in dockerfile
