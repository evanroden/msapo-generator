"""Deployment diagnostics for adapter and host migration readiness."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from typing import Mapping

from app.ai_provider import get_ai_provider
from app.memory import get_memory_backend
from app.pdf_converter import get_pdf_converter
from app.pdf_reader import get_pdf_reader
from app.runtime import RuntimeSettings, writable_probe
from app.smartsheet_store import SubmissionStore, SubmissionStoreError


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    required: bool
    detail: str


def collect_checks(env: Mapping[str, str] | None = None) -> list[Check]:
    source = dict(os.environ if env is None else env)
    checks: list[Check] = []
    try:
        runtime = RuntimeSettings.from_environment(source)
        for name, path in (
            ("data directory", runtime.data_dir),
            ("work directory", runtime.work_dir),
            ("output directory", runtime.output_dir),
        ):
            ok, detail = writable_probe(path)
            checks.append(Check(name, ok, True, f"{path}: {detail}"))
        checks.append(
            Check(
                "MSAPO template",
                runtime.template_path.is_file(),
                True,
                str(runtime.template_path),
            )
        )
        checks.append(Check("port", True, True, f"{runtime.host}:{runtime.port}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("runtime settings", False, True, str(exc)))

    for name, factory, required in (
        ("AI provider", lambda: get_ai_provider(source), True),
        ("PDF reader", lambda: get_pdf_reader(source), True),
        ("PDF converter", lambda: get_pdf_converter(source), False),
        ("memory backend", lambda: get_memory_backend(source), False),
    ):
        try:
            adapter = factory()
            diagnostic = dict(adapter.diagnostic())
            configured = bool(diagnostic.get("configured", True))
            checks.append(
                Check(
                    name,
                    configured,
                    required,
                    json.dumps(diagnostic, sort_keys=True),
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(name, False, required, str(exc)))

    smartsheet_live = source.get("SMARTSHEET_API_MODE", "disabled").lower() == "live"
    try:
        store = SubmissionStore.from_environment(source)
        detail = f"{getattr(store, 'path', store.__class__.__name__)}"
        checks.append(Check("submission store", True, smartsheet_live, detail))
    except SubmissionStoreError as exc:
        checks.append(Check("submission store", False, smartsheet_live, str(exc)))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check Email Process Control deployment readiness."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    checks = collect_checks()
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        for check in checks:
            marker = "PASS" if check.ok else ("FAIL" if check.required else "WARN")
            print(f"[{marker}] {check.name}: {check.detail}")
    if any(check.required and not check.ok for check in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
