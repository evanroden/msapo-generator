"""Correct Streamlit 1.61.1's scalar date boundary to BaseWeb.

Streamlit keeps date values as arrays in its widget protocol, even for one
scalar date. BaseWeb's assertive selection announcement treats a one-element
array as an unfinished range regardless of its ``range`` prop. Pass a scalar
Date (or null) only at that component boundary. Range values, native controls,
callbacks, and the array-valued widget protocol remain unchanged.

This exact, fail-closed compatibility patch preserves the original locked
assets and writes content-named repaired bundles. The no-cache HTML selects
the new entry, so an old immutable browser cache cannot hide the correction.
A different wheel must be reviewed rather than patched by a fuzzy search.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

STREAMLIT_VERSION = "1.61.1"
BUNDLE_NAME = "DateInput.BXvTEfuB.js"
INDEX_BUNDLE = "index.bE3scgDe.js"
ORIGINAL_SHA256 = "d152ac48cbaa8213d627e0207a45d0acc8b9c35494d07827a25ac7b02f791ccc"
INDEX_SHA256 = "2ca8d2fdc237ec568ac10b8aae70c21e28c9e25ea1924378f068f7a81af6fe6e"
ORIGINAL = b"value:x,minDate:M,maxDate:N,range:t.isRange,clearable:F"
REPAIRED = b"value:(t.isRange?x:(x?.[0]??null)),minDate:M,maxDate:N,range:t.isRange,clearable:F"


def patch_bundle(static_dir: Path, *, installed_version: str) -> dict[str, str | bool]:
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError(f"Date input compatibility patch requires Streamlit {STREAMLIT_VERSION}; found {installed_version}.")
    scripts = static_dir / "static" / "js"
    original = (scripts / BUNDLE_NAME).read_bytes()
    entry = (scripts / INDEX_BUNDLE).read_bytes()
    html_path = static_dir / "index.html"
    html = html_path.read_bytes()
    if (sha256(original).hexdigest() != ORIGINAL_SHA256 or original.count(ORIGINAL) != 1
            or sha256(entry).hexdigest() != INDEX_SHA256 or entry.count(BUNDLE_NAME.encode()) != 2):
        raise RuntimeError("Unexpected Streamlit date input/entry asset; no bytes were changed.")
    repaired = original.replace(ORIGINAL, REPAIRED, 1)
    repaired_name = "DateInput.enfra-scalar-" + sha256(repaired).hexdigest()[:12] + ".js"
    repaired_entry = entry.replace(BUNDLE_NAME.encode(), repaired_name.encode())
    entry_name = "index.enfra-date-" + sha256(repaired_entry).hexdigest()[:12] + ".js"
    already_patched = html.count(entry_name.encode()) == 1 and INDEX_BUNDLE.encode() not in html
    if not already_patched and (html.count(INDEX_BUNDLE.encode()) != 1 or entry_name.encode() in html):
        raise RuntimeError("Unexpected Streamlit HTML entry; no bytes were changed.")
    destinations = ((scripts / repaired_name, repaired), (scripts / entry_name, repaired_entry))
    for path, raw in destinations:
        if path.exists() and path.read_bytes() != raw:
            raise RuntimeError("Unexpected repaired Streamlit asset; no bytes were changed.")
    # Validate all three inputs and both destinations before the first write.
    # Publication of HTML is last; a failed asset write cannot select a partial
    # client entry. Original assets remain available to pre-existing sessions.
    for path, raw in destinations:
        if not path.exists():
            path.write_bytes(raw)
    if not already_patched:
        html_path.write_bytes(html.replace(INDEX_BUNDLE.encode(), entry_name.encode(), 1))
    return {"version": installed_version, "bundle": repaired_name, "entry": entry_name,
            "original_sha256": ORIGINAL_SHA256,
            "patched_sha256": sha256(repaired).hexdigest(),
            "patched_entry_sha256": sha256(repaired_entry).hexdigest(),
            "already_patched": already_patched}


def main() -> None:
    import json
    import streamlit
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(patch_bundle(args.static_dir or Path(streamlit.__file__).parent / "static",
                                  installed_version=version("streamlit")), sort_keys=True))


if __name__ == "__main__":
    main()
