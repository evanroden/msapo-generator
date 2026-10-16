"""Explicit bootstrap for one isolated diagnostic server, never the normal CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.qa_native_owner_assets import owned_static


def main(argv=None, *, cli=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    if (os.environ.get("EPC_MONTHLY_DOM_FIXTURE") != "1"
            or os.environ.get("EPC_MONTHLY_FRESH_TASK") != "1"
            or os.environ.get("SMARTSHEET_API_MODE") != "disabled"):
        raise RuntimeError("Native owner server requires the existing isolated Fresh fixture guards")
    data = Path(os.environ["EPC_DATA_DIR"])
    if args.manifest.resolve() != args.static_dir.resolve().parent / "manifest.json":
        raise RuntimeError("Diagnostic manifest must belong to the owned static copy")
    manifest = json.loads(args.manifest.read_bytes())
    with owned_static(args.static_dir, manifest, data):
        if cli is None:
            from streamlit.web.cli import main as cli
        return cli(args=["run", str(ROOT / "tests/fixtures/workspaces/monthly_fresh_app.py"),
                         "--server.address", "127.0.0.1", "--server.port", "8529",
                         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                   standalone_mode=False)


if __name__ == "__main__":
    main()
