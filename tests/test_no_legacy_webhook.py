from pathlib import Path


def test_abandoned_webhook_files_are_removed():
    assert not Path("run_api.py").exists()
    assert not Path("app/webhook.py").exists()
    assert not Path("app/email_handler.py").exists()


def test_abandoned_webhook_dependencies_are_removed():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "fastapi" not in requirements
    assert "uvicorn" not in requirements
    assert "python-multipart" not in requirements
    assert "sendgrid" not in requirements


def test_compose_file_has_only_supported_application_service():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "  api:" not in compose
    assert "app.webhook" not in compose
