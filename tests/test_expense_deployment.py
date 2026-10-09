import os
import runpy
from pathlib import Path

import pytest

from app.expense_report import _SIGNATURE_FONT_CANDIDATES
from tests.conftest import libreoffice_can_convert

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


def test_the_renderer_probe_agrees_that_ci_can_render():
    """The skip guard must never be the thing that silences CI.

    ``requires_libreoffice`` skips when the writer/calc import filters are
    absent, which is correct on a developer machine carrying only
    ``libreoffice-core``. On CI it must never fire: the workflow installs both
    packages, so a False here means the PROBE is wrong, and the renderer tests
    would go back to skipping silently -- the precise failure the package pin
    below was written to end.

    Asserted only under GITHUB_ACTIONS, because the probe returning False is the
    expected and useful answer everywhere else.
    """
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        pytest.skip("only meaningful on the CI runner")

    assert libreoffice_can_convert(), (
        "CI installs libreoffice-writer and libreoffice-calc, but the probe in "
        "tests/conftest.py reports it cannot render. The renderer tests are "
        "skipping on CI. Fix the probe -- do not relax the guard."
    )


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

    renderers = {
        "libreoffice-writer", "libreoffice-calc", "fontconfig",
        "fonts-liberation", "fonts-texgyre", "fonts-opensymbol",
        "fonts-crosextra-carlito", "fonts-crosextra-caladea",
    }
    for package in renderers:
        assert package in dockerfile, f"{package} missing from the image"
        assert package in workflow, (
            f"{package} is installed in the image but not in CI, so every test "
            "that needs it will skip instead of verifying the behavior."
        )

    # Signature fonts must match too -- see the candidate-path test above.
    for package in set(_FONT_DIRECTORY_PACKAGES.values()):
        assert package in workflow, f"{package} missing from CI"


def test_document_runtime_is_fixed_and_verified_before_release():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "FROM ubuntu:24.04" in dockerfile
    assert "python3.12 -m venv /opt/venv" in dockerfile
    assert 'PATH="/opt/venv/bin:$PATH"' in dockerfile
    assert "runs-on: ubuntu-24.04" in workflow
    assert "ubuntu-latest" not in workflow
    for config in (dockerfile, workflow):
        assert "FONTCONFIG_FILE" in config
        assert "runtime/fonts.conf" in config
        assert "python runtime/check_renderer.py" in config
    assert "docker build" in workflow
    assert "State.Health.Status" in workflow


@pytest.mark.parametrize("version", ["LibreOffice 25.2.7.2", "LibreOfficeDev 26.8.0.0.alpha0"])
def test_renderer_gate_rejects_unverified_renderer(monkeypatch, version):
    gate = runpy.run_path(str(ROOT / "runtime/check_renderer.py"))
    monkeypatch.setattr("subprocess.check_output", lambda *args, **kwargs: version)
    with pytest.raises(RuntimeError, match="verified LibreOffice 24.2"):
        gate["check_renderer"]()


def test_renderer_gate_rejects_wrong_font_even_if_renderer_is_correct(monkeypatch):
    gate = runpy.run_path(str(ROOT / "runtime/check_renderer.py"))
    results = iter(["LibreOffice 24.2.7.2", "/fonts/DejaVuSans.ttf"])
    monkeypatch.setattr("subprocess.check_output", lambda *args, **kwargs: next(results))
    with pytest.raises(RuntimeError, match="LiberationSans-Regular.ttf"):
        gate["check_renderer"]()


def test_renderer_gate_accepts_verified_fonts_and_security_patch(monkeypatch, tmp_path):
    gate = runpy.run_path(str(ROOT / "runtime/check_renderer.py"))
    results = ["LibreOffice 24.2.7.2 420(Build:2)"]
    for font in gate["FONT_MATCHES"].values():
        path = tmp_path / font
        path.touch()
        results.append(str(path))
    responses = iter(results)
    monkeypatch.setattr("subprocess.check_output", lambda *args, **kwargs: next(responses))
    gate["check_renderer"]()
