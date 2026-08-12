from pathlib import Path

from app.expense_report import _SIGNATURE_FONT_CANDIDATES


ROOT = Path(__file__).resolve().parents[1]

# Debian package that ships each font directory the signature renderer looks in.
# Every candidate path must map to a package the image installs, otherwise the
# "fallback" is a fiction: DejaVuSerif-Italic.ttf lives in fonts-dejavu-EXTRA,
# so an image installing only fonts-dejavu-core silently had one real font and
# one dead entry.
_FONT_DIRECTORY_PACKAGES = {
    "/usr/share/fonts/opentype/urw-base35": "fonts-urw-base35",
    "/usr/share/fonts/truetype/dejavu": "fonts-dejavu-extra",
}


def test_every_signature_font_candidate_is_installed_by_the_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert _SIGNATURE_FONT_CANDIDATES, "the renderer must declare at least one font"
    for candidate in _SIGNATURE_FONT_CANDIDATES:
        directory = str(candidate.parent)
        package = _FONT_DIRECTORY_PACKAGES.get(directory)
        assert package is not None, (
            f"{candidate} lives in {directory}, which is not mapped to a Debian "
            "package here. Add the mapping and install the package in the "
            "Dockerfile, or the fallback can never resolve at runtime."
        )
        assert package in dockerfile, (
            f"{candidate} requires {package}, which the Dockerfile does not "
            "install. Signature rendering would fail closed in production."
        )


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
    assert "libreoffice-writer" in dockerfile
    assert "curl" in dockerfile
    assert "fonts-urw-base35" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["streamlit", "run", "run_web.py"' in dockerfile


def test_ci_installs_the_same_document_renderers_as_the_image():
    """CI must render documents the same way production does.

    The runner image ships no LibreOffice. Every renderer-dependent test
    therefore SKIPPED rather than failed, which reads identically to "passing"
    in a summary line -- the expense combined-PDF test skipped silently from the
    day it was written, and the purchase-order MSAPO render would have done the
    same. Pinning the two package lists together means a renderer can never be
    added to the image, or dropped from CI, without this failing loudly.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    renderers = {"libreoffice-writer", "libreoffice-calc"}
    for package in renderers:
        assert package in dockerfile, f"{package} missing from the image"
        assert package in workflow, (
            f"{package} is installed in the image but not in CI, so every test "
            "that needs it will skip instead of verifying the behavior."
        )

    # Signature fonts must match too -- see the candidate-path test above.
    for package in set(_FONT_DIRECTORY_PACKAGES.values()):
        assert package in workflow, f"{package} missing from CI"
