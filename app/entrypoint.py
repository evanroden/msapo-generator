"""Host-neutral process entrypoint for Streamlit."""

from __future__ import annotations

import os
import sys

from app.runtime import get_runtime_settings


def main() -> None:
    settings = get_runtime_settings()
    argv = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "run_web.py",
        f"--server.port={settings.port}",
        f"--server.address={settings.host}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    os.execv(sys.executable, argv)


if __name__ == "__main__":
    main()
