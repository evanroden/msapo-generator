"""Fail-closed compatibility repairs for the exact Streamlit 1.61.1 client.

The widget batcher must retain a full-editor request when preview fragments
share its deferred flush. Optional scalar-date compatibility composes with the
same entry publisher, rather than allowing two installers to undo each other.
Original immutable assets remain available; HTML selects content-named copies.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

STREAMLIT_VERSION = "1.61.1"
INDEX_BUNDLE = "index.bE3scgDe.js"
INDEX_SHA256 = "2ca8d2fdc237ec568ac10b8aae70c21e28c9e25ea1924378f068f7a81af6fe6e"
ORIGINAL = b"this.scheduledFragmentId===void 0&&(this.scheduledFragmentId=e)"
LEGACY_REPAIRED = b"(!this.flushScheduled||e===void 0)&&(this.scheduledFragmentId=e)"
# Main-script Delta messages decode fragmentId to the protobuf empty string.
# Normalize only that known full-run representation; undefined remains valid.
REPAIRED = b"e===``&&(e=void 0),(!this.flushScheduled||e===void 0)&&(this.scheduledFragmentId=e)"
DATE_BUNDLE = "DateInput.BXvTEfuB.js"
DATE_SHA256 = "d152ac48cbaa8213d627e0207a45d0acc8b9c35494d07827a25ac7b02f791ccc"
DATE_ORIGINAL = b"value:x,minDate:M,maxDate:N,range:t.isRange,clearable:F"
DATE_REPAIRED = b"value:(t.isRange?x:(x?.[0]??null)),minDate:M,maxDate:N,range:t.isRange,clearable:F"


def _entry_name(raw):
    return "index.enfra-frontend-" + sha256(raw).hexdigest()[:12] + ".js"


def patch_bundle(static_dir: Path, *, installed_version: str,
                 scalar_date: bool = False) -> dict[str, str | bool]:
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError(f"Frontend compatibility requires Streamlit {STREAMLIT_VERSION}; found {installed_version}.")
    scripts = static_dir / "static" / "js"
    entry = (scripts / INDEX_BUNDLE).read_bytes()
    date = (scripts / DATE_BUNDLE).read_bytes()
    html_path = static_dir / "index.html"
    html = html_path.read_bytes()
    if (sha256(entry).hexdigest() != INDEX_SHA256 or entry.count(ORIGINAL) != 1
            or entry.count(DATE_BUNDLE.encode()) != 2
            or sha256(date).hexdigest() != DATE_SHA256 or date.count(DATE_ORIGINAL) != 1):
        raise RuntimeError("Unexpected locked Streamlit frontend asset; no bytes were changed.")

    repaired_date = date.replace(DATE_ORIGINAL, DATE_REPAIRED, 1)
    date_name = "DateInput.enfra-scalar-" + sha256(repaired_date).hexdigest()[:12] + ".js"
    scheduler_entry = entry.replace(ORIGINAL, REPAIRED, 1)
    legacy_scheduler = entry.replace(ORIGINAL, LEGACY_REPAIRED, 1)
    date_entry = entry.replace(DATE_BUNDLE.encode(), date_name.encode())
    combined_entry = scheduler_entry.replace(DATE_BUNDLE.encode(), date_name.encode())
    # Accept the previous exact date installer as an input, as well as either
    # composed output. Never infer compatibility from a filename alone.
    variants = {
        INDEX_BUNDLE: (entry, False),
        _entry_name(scheduler_entry): (scheduler_entry, False),
        _entry_name(legacy_scheduler): (legacy_scheduler, False),
        "index.enfra-date-" + sha256(date_entry).hexdigest()[:12] + ".js": (date_entry, True),
        _entry_name(combined_entry): (combined_entry, True),
        _entry_name(legacy_scheduler.replace(DATE_BUNDLE.encode(), date_name.encode())):
            (legacy_scheduler.replace(DATE_BUNDLE.encode(), date_name.encode()), True),
    }
    selected = [name for name in variants if name.encode() in html]
    if len(selected) != 1 or html.count(selected[0].encode()) != 1:
        raise RuntimeError("Unexpected Streamlit HTML entry; no bytes were changed.")
    selected_name = selected[0]
    selected_raw, has_date = variants[selected_name]
    if (scripts / selected_name).read_bytes() != selected_raw:
        raise RuntimeError("The selected Streamlit entry failed its integrity check; no bytes were changed.")
    if has_date and (scripts / date_name).read_bytes() != repaired_date:
        raise RuntimeError("The selected date asset failed its integrity check; no bytes were changed.")

    include_date = scalar_date or has_date
    repaired_entry = combined_entry if include_date else scheduler_entry
    entry_name = _entry_name(repaired_entry)
    destinations = [(scripts / entry_name, repaired_entry)]
    if include_date:
        destinations.append((scripts / date_name, repaired_date))
    # Validate every input and destination before the first write. Publishing
    # HTML last cannot select a partially written client entry.
    for path, raw in destinations:
        if path.exists() and path.read_bytes() != raw:
            raise RuntimeError("Unexpected repaired Streamlit asset; no bytes were changed.")
    for path, raw in destinations:
        if not path.exists():
            path.write_bytes(raw)
    already_patched = selected_name == entry_name
    if not already_patched:
        html_path.write_bytes(html.replace(selected_name.encode(), entry_name.encode(), 1))
    return {"version": installed_version, "entry": entry_name,
            "original_entry_sha256": INDEX_SHA256,
            "patched_entry_sha256": sha256(repaired_entry).hexdigest(),
            "scalar_date": include_date, "bundle": date_name if include_date else "",
            "original_sha256": DATE_SHA256,
            "patched_sha256": sha256(repaired_date).hexdigest() if include_date else "",
            "already_patched": already_patched}


def main():
    import json
    import streamlit
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-dir", type=Path)
    parser.add_argument("--scalar-date", action="store_true")
    args = parser.parse_args()
    print(json.dumps(patch_bundle(args.static_dir or Path(streamlit.__file__).parent / "static",
                                  installed_version=version("streamlit"),
                                  scalar_date=args.scalar_date), sort_keys=True))


if __name__ == "__main__":
    main()
