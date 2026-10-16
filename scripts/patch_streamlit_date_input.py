"""Compose scalar-date compatibility with the pinned full-run batch repair.

The date widget retains its array-valued server protocol. Only its BaseWeb
scalar boundary changes; one shared publisher owns the selected client entry.
"""
from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path

try:
    from scripts import patch_streamlit_frontend as frontend
except ModuleNotFoundError:  # Direct `python scripts/...` entrypoint.
    import patch_streamlit_frontend as frontend

STREAMLIT_VERSION = frontend.STREAMLIT_VERSION
BUNDLE_NAME = frontend.DATE_BUNDLE
INDEX_BUNDLE = frontend.INDEX_BUNDLE
ORIGINAL_SHA256 = frontend.DATE_SHA256
INDEX_SHA256 = frontend.INDEX_SHA256
ORIGINAL = frontend.DATE_ORIGINAL
REPAIRED = frontend.DATE_REPAIRED


def patch_bundle(static_dir: Path, *, installed_version: str):
    return frontend.patch_bundle(static_dir, installed_version=installed_version, scalar_date=True)


def main():
    import json
    import streamlit
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(patch_bundle(args.static_dir or Path(streamlit.__file__).parent / "static",
                                  installed_version=version("streamlit")), sort_keys=True))


if __name__ == "__main__":
    main()
