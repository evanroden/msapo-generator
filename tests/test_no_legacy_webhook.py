from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_abandoned_webhook_files_are_removed():
    assert not (REPO_ROOT / "run_api.py").exists()
    assert not (REPO_ROOT / "app/webhook.py").exists()
    assert not (REPO_ROOT / "app/email_handler.py").exists()


def test_abandoned_webhook_dependencies_are_removed():
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "sendgrid" not in requirements.casefold()
    assert "fastapi" not in requirements.casefold()
    assert "uvicorn" not in requirements.casefold()
    assert "python-multipart" not in requirements.casefold()


def test_compose_file_has_only_supported_application_service():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  api:" not in compose
    assert "app.webhook" not in compose


def test_deployment_manifest_does_not_restore_the_legacy_api():
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "runtime: docker" in render
    assert "run_api.py" not in render
    assert "uvicorn" not in render.casefold()
