"""Safe, host-neutral Streamlit container launcher and local readiness probe.

The default Dockerfile command remains unchanged for Render and existing hosts.
Run ``python scripts/container_portability.py serve`` only when the operator
explicitly configures a nondefault container port or listen address.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_PORT = 8501
HEALTH_PATH = "/_stcore/health"
ROOT = Path(__file__).resolve().parents[1]


class ContractError(ValueError):
    """A host configuration cannot safely start the existing application."""


def settings(env=None):
    env = os.environ if env is None else env
    raw = env.get("EPC_PORT", str(DEFAULT_PORT))
    if not re.fullmatch(r"[0-9]{1,5}", raw or ""):
        raise ContractError("EPC_PORT must be an integer from 1 to 65535")
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ContractError("EPC_PORT must be an integer from 1 to 65535")
    host = env.get("EPC_HOST", "0.0.0.0")
    if not host or not re.fullmatch(r"[A-Za-z0-9.:-]{1,255}", host):
        raise ContractError("EPC_HOST must be a valid bind-address token")
    return host, port


def _writable(path: Path, *, must_exist: bool) -> bool:
    """Use a private disposable probe; never read or change a report."""
    if must_exist and not path.is_dir():
        return False
    if not path.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(prefix=".msapo-port-", dir=path, delete=True):
            pass
    except OSError:
        return False
    return True


def check(env=None):
    env = os.environ if env is None else env
    host, port = settings(env)
    data = env.get("EPC_DATA_DIR")
    # Current main uses /app/output. PR #868's opt-in EPC_OUTPUT_DIR is
    # deliberately NOT assumed to be integrated here.
    output = ROOT / "output"
    checks = {
        "entrypoint_present": (ROOT / "run_web.py").is_file(),
        "output_writable": _writable(output, must_exist=True),
        "temp_writable": _writable(Path(tempfile.gettempdir()), must_exist=True),
        "configured_data_writable": not data or (
            Path(data).is_absolute() and _writable(Path(data), must_exist=True)
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "bind": host,
        "port": port,
        "health_path": HEALTH_PATH,
        "revision_embedded": bool(re.fullmatch(r"[0-9a-f]{40}", env.get("APP_GIT_COMMIT", ""))),
    }


def ready(env=None, *, opener=urlopen):
    """Readiness is the local Streamlit HTTP health endpoint, not data safety."""
    _, port = settings(env)
    try:
        with opener(f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=5) as response:
            return response.status == 200 and response.read(64).strip() == b"ok"
    except (OSError, URLError, TimeoutError, ValueError):
        return False


def serve(env=None, *, execvp=os.execvp):
    result = check(env)
    if not result["ok"]:
        raise ContractError("Runtime writable-path preflight failed (see check output)")
    argv = [
        "streamlit", "run", "run_web.py",
        f"--server.address={result['bind']}",
        f"--server.port={result['port']}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    # Replace PID 1: Streamlit receives SIGTERM and handles graceful shutdown.
    execvp("streamlit", argv)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "ready", "serve"))
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            result = check()
            print(json.dumps({**result, "bind": "wildcard" if result["bind"] == "0.0.0.0" else "configured"}, sort_keys=True))
            return 0 if result["ok"] else 1
        if args.command == "ready":
            return 0 if ready() else 1
        serve()
        return 0
    except ContractError as exc:
        print(f"Container contract error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

