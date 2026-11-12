"""Focused synthetic port contract tests; no host, secrets or customer inputs."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from scripts import container_portability as contract
from scripts import container_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("raw", ["0", "65536", "-1", "0x2145", "abc", "", "8501\nfoo"])
def test_invalid_port_fail_closed(raw):
    with pytest.raises(contract.ContractError):
        contract.settings({"EPC_PORT": raw})


def test_default_does_not_assume_platform_supplied_port():
    assert contract.settings({"PORT": "9000"}) == ("0.0.0.0", 8501)
    assert contract.settings({"EPC_PORT": "9000", "EPC_HOST": "127.0.0.1"}) == ("127.0.0.1", 9000)


def test_bad_host_rejected():
    with pytest.raises(contract.ContractError):
        contract.settings({"EPC_HOST": "0.0.0.0 --server.enableCORS=false"})


def test_missing_configured_persistent_mount_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "ROOT", tmp_path)
    (tmp_path / "run_web.py").touch()
    (tmp_path / "output").mkdir()
    result = contract.check({"EPC_DATA_DIR": str(tmp_path / "missing")})
    assert not result["ok"]
    assert not result["checks"]["configured_data_writable"]


def test_writable_check_disposes_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "ROOT", tmp_path)
    (tmp_path / "run_web.py").touch()
    (tmp_path / "output").mkdir()
    (tmp_path / "data").mkdir()
    assert contract.check({"EPC_DATA_DIR": str(tmp_path / "data")})["ok"]
    assert list((tmp_path / "data").iterdir()) == []
    assert list((tmp_path / "output").iterdir()) == []


def test_portable_launcher_preserves_single_three_workflow_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "ROOT", tmp_path)
    (tmp_path / "run_web.py").touch()
    (tmp_path / "output").mkdir()
    calls = []
    contract.serve({"EPC_PORT": "8951"}, execvp=lambda name, args: calls.append((name, args)))
    assert calls == [("streamlit", ["streamlit", "run", "run_web.py",
                                     "--server.address=0.0.0.0", "--server.port=8951",
                                     "--server.headless=true", "--browser.gatherUsageStats=false"])]


class _FakeResponse:
    status = 200
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, _n):
        return b"ok"


def test_local_readiness_uses_selected_port_not_external_header():
    urls = []
    def opener(url, timeout):
        urls.append((url, timeout))
        return _FakeResponse()
    assert contract.ready({"EPC_PORT": "8951"}, opener=opener)
    assert urls == [("http://127.0.0.1:8951/_stcore/health", 5)]


def test_readiness_refuses_non_ok_http_response():
    class Unready(_FakeResponse):
        def read(self, _n):
            return b"unexpected"
    assert not contract.ready({}, opener=lambda *a, **k: Unready())


def test_docker_image_invariants_and_ocirevision():
    d = (ROOT / "Dockerfile").read_text()
    assert "FROM ubuntu:24.04" in d
    assert "COPY requirements.lock ./" in d
    assert "python -m pip install -r requirements.lock" in d
    assert "python runtime/check_renderer.py" in d
    assert "libreoffice-writer" in d and "libreoffice-calc" in d
    assert "fonts-dejavu-extra" in d and "fonts-urw-base35" in d
    assert "org.opencontainers.image.revision" in d
    assert 'CMD ["streamlit", "run", "run_web.py"' in d
    assert "scripts/container_portability.py ready" in d


def test_single_entrypoint_keeps_all_workflows():
    src = (ROOT / "app/web_ui.py").read_text()
    for name in ("PURCHASE_WORKFLOW", "EXPENSE_WORKFLOW", "MONTHLY_REPORT_WORKFLOW",
                 "render_expense_workflow", "render_monthly_report_workflow"):
        assert name in src
    assert "from app.web_ui import main" in (ROOT / "run_web.py").read_text()
    assert smoke.WORKFLOW_IMPORTS == (
        "app.web_ui", "app.expense_ui", "app.monthly_report_ui"
    )


def test_synthetic_render_markers_are_invented_and_price_free():
    assert "SYNTHETIC" in smoke.MARKER_DOCX
    assert "SYNTHETIC" in smoke.MARKER_EXPENSE
    assert "@" not in smoke.MARKER_DOCX + smoke.MARKER_EXPENSE


def test_full_synthetic_pdf_conversions_when_renderer_installed():
    import shutil
    import os
    if not shutil.which("libreoffice"):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("CI must install LibreOffice to qualify real DOCX/PDF/Calc")
        pytest.skip("LibreOffice not installed locally")
    result = smoke.render_synthetic()
    assert result["word"]["pages"] > 0
    assert result["expense_calc"]["pages"] > 0
    assert result["word"]["extracted_text_matches"]
    assert result["expense_calc"]["extracted_text_matches"]

