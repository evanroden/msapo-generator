"""Fail-closed compatibility repairs for the exact Streamlit 1.61.1 client.

The widget batcher must retain a full-editor request when preview fragments
share its deferred flush. Optional scalar-date compatibility composes with the
same entry publisher, rather than allowing two installers to undo each other.
Original immutable assets remain available; HTML selects content-named copies.
The shared overlay hook is reached through a pinned closed import graph. Its
cyclic chunks share a generation identity instead of attempting a filename-hash
fixed point; every final payload is independently reconstructed and verified.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import tempfile

try:
    from scripts.streamlit_overlay_resize import OVERLAY_BUNDLE, OVERLAY_SHA256, repair_overlay
    from scripts.streamlit_virtualizer_resize import VIRTUALIZER_BUNDLE, VIRTUALIZER_SHA256, repair_virtualizer
    from scripts.streamlit_floating_resize import FLOATING_BUNDLE, FLOATING_SHA256, repair_floating
except ModuleNotFoundError:  # Direct `python scripts/...` entrypoint.
    from streamlit_overlay_resize import OVERLAY_BUNDLE, OVERLAY_SHA256, repair_overlay
    from streamlit_virtualizer_resize import VIRTUALIZER_BUNDLE, VIRTUALIZER_SHA256, repair_virtualizer
    from streamlit_floating_resize import FLOATING_BUNDLE, FLOATING_SHA256, repair_floating

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
MANIFEST_PATH = Path(__file__).with_name("streamlit_frontend_manifest.json")
MANIFEST_SHA256 = "ebc8b75c6740806e3a23d16e38ec71750cbabf63b09af99dcb60612d07c682e3"
FLOATING_MANIFEST_PATH = Path(__file__).with_name("streamlit_floating_manifest.json")
FLOATING_MANIFEST_SHA256 = "f57691c472085c39b50ef33f29dc5aaf23464160fce86137a7db0180165c4636"
_REFERENCES = re.compile(rb'''["'`](?:\./|static/js/)([A-Za-z0-9_.-]+\.js)["'`]''')
_SCRIPT = re.compile(rb'''<script\b[^>]*\bsrc=["']\./static/js/([^/"']+)["'][^>]*>''', re.I)


@dataclass(frozen=True)
class Publication:
    names: dict[str, str]
    payloads: dict[str, bytes]
    scalar_date: bool
    virtualizer_resize: bool
    floating_resize: bool
    queued_scroll: bool
    generation: str


def _references(raw):
    return {name.decode("ascii") for name in _REFERENCES.findall(raw)}


def _locked_sources(scripts):
    manifest_raw = MANIFEST_PATH.read_bytes()
    if sha256(manifest_raw).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("Unexpected locked frontend import manifest; no bytes were changed.")
    manifest = json.loads(manifest_raw)
    members = manifest["members"]
    if (manifest["streamlit_version"] != STREAMLIT_VERSION or manifest["root"] != OVERLAY_BUNDLE
            or len(members) != 81 or members[INDEX_BUNDLE]["sha256"] != INDEX_SHA256
            or members[DATE_BUNDLE]["sha256"] != DATE_SHA256
            or members[OVERLAY_BUNDLE]["sha256"] != OVERLAY_SHA256
            or members[VIRTUALIZER_BUNDLE]["sha256"] != VIRTUALIZER_SHA256):
        raise RuntimeError("Invalid locked frontend import manifest; no bytes were changed.")
    sources = {}
    for name, record in members.items():
        raw = (scripts / name).read_bytes()
        if (sha256(raw).hexdigest() != record["sha256"]
                or _references(raw) != set(record["references"])):
            raise RuntimeError("Unexpected locked Streamlit frontend asset: " + name + "; no bytes were changed.")
        sources[name] = raw
    # Check the pinned graph itself is the reverse closure, including preload
    # dependency tables, and that the final entry has no incoming module edge.
    incoming = {name: set() for name in members}
    for name, record in members.items():
        for dependency in record["references"]:
            if dependency in incoming:
                incoming[dependency].add(name)
    closure, pending = set(), [OVERLAY_BUNDLE]
    while pending:
        name = pending.pop()
        if name not in closure:
            closure.add(name)
            pending.extend(incoming[name])
    if closure != set(members) or incoming[INDEX_BUNDLE]:
        raise RuntimeError("The locked frontend import graph is not closed; no bytes were changed.")
    # Preserve the former 81-member manifest and recipe exactly for upgrades.
    # The new root adds only Floating UI and its otherwise unmodified Json
    # importer; all other reverse importers are already in the original graph.
    extra_raw = FLOATING_MANIFEST_PATH.read_bytes()
    if sha256(extra_raw).hexdigest() != FLOATING_MANIFEST_SHA256:
        raise RuntimeError("Unexpected locked Floating UI import manifest; no bytes were changed.")
    extra = json.loads(extra_raw)
    if (extra["streamlit_version"] != STREAMLIT_VERSION or extra["root"] != FLOATING_BUNDLE
            or set(extra["members"]) != {FLOATING_BUNDLE, "Json.C9LKsaSO.js"}
            or extra["members"][FLOATING_BUNDLE]["sha256"] != FLOATING_SHA256):
        raise RuntimeError("Invalid locked Floating UI import manifest; no bytes were changed.")
    members = {**members, **extra["members"]}
    for name, record in extra["members"].items():
        raw = (scripts / name).read_bytes()
        if sha256(raw).hexdigest() != record["sha256"] or _references(raw) != set(record["references"]):
            raise RuntimeError("Unexpected locked Floating UI asset: " + name + "; no bytes were changed.")
        sources[name] = raw
    pending = [FLOATING_BUNDLE]
    while pending:
        name = pending.pop()
        if name not in closure:
            closure.add(name)
            pending.extend(n for n, record in members.items() if name in record["references"])
    if closure != set(members):
        raise RuntimeError("The combined frontend import graph is not closed; no bytes were changed.")
    # A new native importer would otherwise retain a second copy of React Aria
    # contexts. Generated variants are immutable outputs, not native inputs.
    for path in scripts.glob("*.js"):
        if path.name not in members and ".enfra-" not in path.name:
            if _references(path.read_bytes()) & closure:
                raise RuntimeError("Unpinned frontend importer: " + path.name + "; no bytes were changed.")
    return sources, members


def _publication(sources, members, scalar_date, *, virtualizer_resize=True, floating_resize=True, queued_scroll=True):
    if not floating_resize:
        originals = json.loads(MANIFEST_PATH.read_bytes())["members"]
        sources = {name: raw for name, raw in sources.items() if name in originals}
        members = {name: record for name, record in members.items() if name in originals}
    repaired = dict(sources)
    repaired[INDEX_BUNDLE] = sources[INDEX_BUNDLE].replace(ORIGINAL, REPAIRED, 1)
    repaired[OVERLAY_BUNDLE] = repair_overlay(sources[OVERLAY_BUNDLE], queued_scroll=queued_scroll)
    if virtualizer_resize:
        repaired[VIRTUALIZER_BUNDLE] = repair_virtualizer(sources[VIRTUALIZER_BUNDLE])
    if floating_resize:
        repaired[FLOATING_BUNDLE] = repair_floating(sources[FLOATING_BUNDLE])
    if scalar_date:
        repaired[DATE_BUNDLE] = sources[DATE_BUNDLE].replace(DATE_ORIGINAL, DATE_REPAIRED, 1)
    # This digest binds all original source pins, their graph, exact repair
    # bytes, configuration and naming recipe. A whole-generation name handles
    # the five-chunk native ESM cycle without circular final-byte hashes.
    identity = json.dumps({
        "schema": 1, "recipe": "same-directory-overlay-closure-v1",
        "manifest_sha256": MANIFEST_SHA256, "scalar_date": scalar_date,
        "repaired_sha256": {name: sha256(raw).hexdigest() for name, raw in sorted(repaired.items())},
    }, sort_keys=True, separators=(",", ":")).encode()
    generation = sha256(identity).hexdigest()
    names = {name: name[:-3] + ".enfra-overlay-" + generation[:20] + ".js"
             for name in sources if name != INDEX_BUNDLE}
    substitutions = {name.encode(): value.encode() for name, value in names.items()}
    pattern = re.compile(b"|".join(re.escape(name) for name in substitutions))
    payloads = {}
    for name, raw in repaired.items():
        rewritten = pattern.sub(lambda match: substitutions[match[0]], raw)
        expected = {names.get(dependency, dependency) for dependency in members[name]["references"]}
        if _references(rewritten) != expected:
            raise RuntimeError("Generated frontend import edges did not match their manifest; no bytes were changed.")
        payloads[name] = rewritten
    names[INDEX_BUNDLE] = _entry_name(payloads[INDEX_BUNDLE])
    return Publication(names, payloads, scalar_date, virtualizer_resize, floating_resize, queued_scroll, generation)


def _legacy_variants(sources):
    entry, date = sources[INDEX_BUNDLE], sources[DATE_BUNDLE]
    repaired_date = date.replace(DATE_ORIGINAL, DATE_REPAIRED, 1)
    date_name = "DateInput.enfra-scalar-" + sha256(repaired_date).hexdigest()[:12] + ".js"
    scheduler = entry.replace(ORIGINAL, REPAIRED, 1)
    legacy = entry.replace(ORIGINAL, LEGACY_REPAIRED, 1)
    date_entry = entry.replace(DATE_BUNDLE.encode(), date_name.encode())
    variants = {
        INDEX_BUNDLE: (entry, False), _entry_name(scheduler): (scheduler, False),
        _entry_name(legacy): (legacy, False),
        "index.enfra-date-" + sha256(date_entry).hexdigest()[:12] + ".js": (date_entry, True),
    }
    for raw in (scheduler, legacy):
        combined = raw.replace(DATE_BUNDLE.encode(), date_name.encode())
        variants[_entry_name(combined)] = (combined, True)
    return variants, date_name, repaired_date


def _validated_publications(static_dir, installed_version):
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError(f"Frontend compatibility requires Streamlit {STREAMLIT_VERSION}; found {installed_version}.")
    scripts = static_dir / "static" / "js"
    sources, members = _locked_sources(scripts)
    if (sources[INDEX_BUNDLE].count(ORIGINAL) != 1 or sources[DATE_BUNDLE].count(DATE_ORIGINAL) != 1
            or sources[INDEX_BUNDLE].count(DATE_BUNDLE.encode()) != 2):
        raise RuntimeError("Unexpected locked frontend repair boundary; no bytes were changed.")
    # The first two are current outputs. The exact previous overlay-only
    # generations remain fully reconstructable upgrade inputs, including all
    # immutable members and preloads. Preserve their original identity recipe.
    publications = tuple(_publication(sources, members, flag, virtualizer_resize=guard,
                                     floating_resize=floating, queued_scroll=scroll)
                         for scroll, floating, guard in ((True, True, True), (False, True, True),
                                                         (False, False, True), (False, False, False))
                         for flag in (False, True))
    legacy, legacy_date_name, legacy_date = _legacy_variants(sources)
    variants = {**legacy, **{p.names[INDEX_BUNDLE]: (p.payloads[INDEX_BUNDLE], p.scalar_date) for p in publications}}
    html = (static_dir / "index.html").read_bytes()
    selected = _SCRIPT.findall(html)
    if len(selected) != 1 or selected[0].decode() not in variants or html.count(selected[0]) != 1:
        raise RuntimeError("Unexpected Streamlit HTML entry; no bytes were changed.")
    name = selected[0].decode()
    raw, has_date = variants[name]
    if (scripts / name).read_bytes() != raw:
        raise RuntimeError("The selected Streamlit entry failed its integrity check; no bytes were changed.")
    selected_publication = next((p for p in publications if p.names[INDEX_BUNDLE] == name), None)
    if selected_publication:
        _verify_publication(scripts, selected_publication, require_all=True)
        if _publication_html(html, name, selected_publication, publications) != html:
            raise RuntimeError("Selected frontend preloads do not match their publication; no bytes were changed.")
    elif has_date and (scripts / legacy_date_name).read_bytes() != legacy_date:
        raise RuntimeError("The selected date asset failed its integrity check; no bytes were changed.")
    return scripts, html, name, has_date, selected_publication, publications


def _verify_publication(scripts, publication, *, require_all=False):
    for native, raw in publication.payloads.items():
        path = scripts / publication.names[native]
        if path.exists():
            if path.read_bytes() != raw:
                raise RuntimeError("Unexpected repaired Streamlit asset: " + path.name + "; no bytes were changed.")
        elif require_all:
            raise RuntimeError("A selected frontend asset is unavailable: " + path.name + "; no bytes were changed.")


def _publication_html(html, selected_name, publication, publications):
    # Normalize only known immutable variants, then select one coherent graph
    # in the script entry AND HTML preloads. No original file is overwritten.
    aliases = {selected_name.encode(): INDEX_BUNDLE.encode()}
    for known in publications:
        aliases.update({name.encode(): native.encode() for native, name in known.names.items()})
    pattern = re.compile(b"|".join(re.escape(name) for name in aliases))
    native_html = pattern.sub(lambda match: aliases[match[0]], html)
    names = {native.encode(): name.encode() for native, name in publication.names.items()}
    pattern = re.compile(b"|".join(re.escape(name) for name in names))
    return pattern.sub(lambda match: names[match[0]], native_html)


def _receipt(publication):
    return {"version": STREAMLIT_VERSION, "entry": publication.names[INDEX_BUNDLE],
            "original_entry_sha256": INDEX_SHA256,
            "patched_entry_sha256": sha256(publication.payloads[INDEX_BUNDLE]).hexdigest(),
            "overlay_bundle": publication.names[OVERLAY_BUNDLE],
            "original_overlay_sha256": OVERLAY_SHA256,
            "overlay_sha256": sha256(publication.payloads[OVERLAY_BUNDLE]).hexdigest(),
            "virtualizer_bundle": publication.names[VIRTUALIZER_BUNDLE],
            "original_virtualizer_sha256": VIRTUALIZER_SHA256,
            "virtualizer_sha256": sha256(publication.payloads[VIRTUALIZER_BUNDLE]).hexdigest(),
            "virtualizer_resize": publication.virtualizer_resize,
            "floating_resize": publication.floating_resize,
            "queued_scroll": publication.queued_scroll,
            "floating_bundle": publication.names.get(FLOATING_BUNDLE, FLOATING_BUNDLE),
            "original_floating_sha256": FLOATING_SHA256,
            "floating_sha256": (sha256(publication.payloads[FLOATING_BUNDLE]).hexdigest()
                                if publication.floating_resize else FLOATING_SHA256),
            "scalar_date": publication.scalar_date,
            "bundle": publication.names[DATE_BUNDLE] if publication.scalar_date else "",
            "original_sha256": DATE_SHA256,
            "patched_sha256": sha256(publication.payloads[DATE_BUNDLE]).hexdigest() if publication.scalar_date else "",
            "date_bundle": publication.names[DATE_BUNDLE],
            "date_sha256": sha256(publication.payloads[DATE_BUNDLE]).hexdigest(),
            "generation": publication.generation, "closure_count": len(publication.names)}


def selected_frontend(static_dir: Path, *, installed_version: str = STREAMLIT_VERSION):
    """Read-only expected identity: reconstruct, then compare every selected blob.

    Hashing whatever the selected files contain would certify their corruption.
    Only exact bytes derived from the pinned graph and known repairs qualify.
    Prior overlay-only generations return virtualizer_resize=False, never an
    assertion that their virtualizer callback includes the current repair.
    """
    *_, selected, _publications = _validated_publications(Path(static_dir), installed_version)
    if selected is None:
        raise RuntimeError("The selected frontend does not include overlay compatibility.")
    return _receipt(selected)


def _publish(path, raw, *, immutable=False):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-enfra-", delete=False) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        if immutable:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != raw:
                    raise RuntimeError("A frontend destination changed during publication.")
        else:
            os.replace(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _entry_name(raw):
    return "index.enfra-frontend-" + sha256(raw).hexdigest()[:12] + ".js"


@contextmanager
def _directory_lock(static_dir):
    """Serialize publishers on the directory, not the replaced HTML inode.

    Docker and CI use Linux. A read-only directory descriptor gives installers
    one stable lock identity without creating a lockfile or touching an asset.
    Validation and date preservation run after acquisition, using fresh HTML.
    """
    import fcntl
    descriptor = os.open(static_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def patch_bundle(static_dir: Path, *, installed_version: str,
                 scalar_date: bool = False) -> dict[str, str | bool | int]:
    static_dir = Path(static_dir)
    with _directory_lock(static_dir):
        return _patch_bundle_locked(static_dir, installed_version, scalar_date)


def _patch_bundle_locked(static_dir, installed_version, scalar_date):
    scripts, html, name, has_date, _selected, publications = _validated_publications(static_dir, installed_version)
    publication = publications[bool(scalar_date or has_date)]
    _verify_publication(scripts, publication)
    next_html = _publication_html(html, name, publication, publications)
    # Validate all immutable destinations before any write, and publish HTML
    # atomically last. An interrupted install leaves the old client usable.
    for native, raw in publication.payloads.items():
        path = scripts / publication.names[native]
        if not path.exists():
            _publish(path, raw, immutable=True)
    _verify_publication(scripts, publication, require_all=True)
    already_patched = next_html == html
    if not already_patched:
        html_path = static_dir / "index.html"
        if html_path.read_bytes() != html:
            raise RuntimeError("Streamlit HTML changed during publication; retry the installer.")
        _publish(html_path, next_html)
    return {**_receipt(publication), "already_patched": already_patched}


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
