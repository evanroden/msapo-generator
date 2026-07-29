"""Host-neutral runtime paths and process settings."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class RuntimeConfigurationError(RuntimeError):
    """Raised when runtime paths or process settings are invalid."""


def _path(value: str | None, default: Path) -> Path:
    candidate = Path(value).expanduser() if value else default
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _port(value: str | None) -> int:
    raw = (value or "8501").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeConfigurationError(f"Application port must be numeric, not {raw!r}.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeConfigurationError("Application port must be between 1 and 65535.")
    return port


@dataclass(frozen=True)
class RuntimeSettings:
    project_root: Path
    template_path: Path
    data_dir: Path
    work_dir: Path
    output_dir: Path
    port: int
    host: str

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "RuntimeSettings":
        source = os.environ if env is None else env
        work_dir = _path(
            source.get("EPC_WORK_DIR"),
            Path(tempfile.gettempdir()) / "email-process-control",
        )
        return cls(
            project_root=PROJECT_ROOT,
            template_path=_path(
                source.get("EPC_TEMPLATE_PATH"),
                PROJECT_ROOT / "templates" / "Master_MSAPO_Template.docx",
            ),
            # Default to the writable work area rather than the application
            # directory, which is read-only on many PaaS/serverless hosts. A
            # production deployment that needs durable state should always set
            # EPC_DATA_DIR explicitly.
            data_dir=_path(source.get("EPC_DATA_DIR"), work_dir / "data"),
            work_dir=work_dir,
            output_dir=_path(source.get("EPC_OUTPUT_DIR"), work_dir / "output"),
            port=_port(source.get("EPC_PORT") or source.get("PORT")),
            host=(source.get("EPC_HOST") or "0.0.0.0").strip() or "0.0.0.0",
        )

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.work_dir, self.output_dir):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RuntimeConfigurationError(
                    f"Required runtime directory {path} is unavailable: {exc}"
                ) from exc


def get_runtime_settings(env: Mapping[str, str] | None = None) -> RuntimeSettings:
    settings = RuntimeSettings.from_environment(env)
    settings.ensure_directories()
    return settings


def writable_probe(path: Path) -> tuple[bool, str]:
    """Return whether a directory is writable without leaving a file behind."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".epc-probe-", delete=True):
            pass
        return True, "ok"
    except OSError as exc:
        return False, str(exc)
