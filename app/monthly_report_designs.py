"""Versioned, contract-scoped native Word page designs.

Reference reports remain runtime data, never source-controlled templates. A
draft pins the selected file hash; installing another reference cannot change
the appearance of an already pinned report.
"""

from dataclasses import replace
import hashlib
from pathlib import Path
import re

from app import monthly_report_library as library

PREFIX = "enfra_native:"
MASTER_PREFIX = "enfra_master:"


def _directory(contract):
    return library._root() / "designs" / library._contract_directory(contract)


def state(contract):
    path = _directory(contract) / "manifest.json"
    return library._read(path) if path.exists() else {"revision": 0, "default": "", "profiles": {}, "history": []}


def master_state():
    path = library._root() / "designs" / "master" / "manifest.json"
    return library._read(path) if path.exists() else {"revision": 0, "default": "", "history": []}


def _digest(profile):
    prefix = MASTER_PREFIX if profile.template.startswith(MASTER_PREFIX) else PREFIX
    if profile.template.startswith(prefix):
        value = profile.template[len(prefix):]
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("The saved report design reference is invalid.")
        return value
    saved = state(profile.contract)
    selected = saved.get("profiles", {}).get(profile.key)
    if selected:
        return selected
    # Older saved drafts predate explicit design pins. Their imported original
    # is still their design; installing the company master must not replace it.
    # Keep the reference even if its file is missing so source_for fails clearly.
    if profile.imported_from:
        return profile.imported_from
    master = master_state().get("default", "")
    if master:
        return master
    return saved.get("default", "")


def is_master(profile):
    if profile.template.startswith(MASTER_PREFIX):
        return True
    if profile.template.startswith(PREFIX):
        return False
    if profile.imported_from:
        return False
    return bool(master_state().get("default") and not state(profile.contract).get("profiles", {}).get(profile.key))


def source_for(profile):
    digest = _digest(profile)
    if not digest:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("The saved report design reference is invalid.")
    directory = _directory(profile.contract)
    candidates = [library._root() / "designs" / "master" / (digest + ".docx")] if is_master(profile) else [directory / (digest + ".docx"),
                  library._profile_path(profile.contract, profile.key) / "imports" / (digest + ".docx")]
    # A new site can reuse a pinned design within its own contract. Never search
    # another contract, and never choose an import by recency or filename.
    if not is_master(profile):
        candidates.extend((library._root() / "library" / library._contract_directory(profile.contract)).glob("*/imports/" + digest + ".docx"))
    for path in candidates:
        if path.is_file():
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != digest:
                raise ValueError("The saved ENFRA design failed its integrity check.")
            return path
    raise ValueError("The original ENFRA page design is unavailable. Restore its saved reference report in Report design settings.")


def fingerprint(profile):
    return _digest(profile)


def _inspection_order(inspection):
    from app.monthly_report_model import known_sections, default_sections
    known = {section.key for section in known_sections()}
    found = tuple(dict.fromkeys(item.section for item in inspection.items
                               if item.part == "word/document.xml" and item.section in known))
    # All core sections remain available even in partially populated references.
    return (*found, *(section.key for section in default_sections() if not section.appendix and section.key not in found))


def master_section_order(profile):
    """Immutable per-hash design metadata; legacy masters are inspected once."""
    digest = _digest(profile)
    if not digest or not is_master(profile):
        return ()
    root = library._root() / "designs" / "master"
    metadata = root / "metadata" / (digest + ".json")
    if metadata.exists():
        return tuple(library._read(metadata).get("section_order", ()))
    from app.monthly_report_import import inspect_docx
    source = source_for(profile)
    if source is None:
        return ()
    order = _inspection_order(inspect_docx(source))
    library._atomic_write(metadata, library._json({"schema": 1, "hash": digest, "section_order": order}))
    return order


def pin(profile, *, latest_master=False):
    selected = profile
    if latest_master and is_master(profile):
        digest = master_state().get("default", "")
        if digest:
            selected = replace(profile, template=MASTER_PREFIX + digest)
    digest = _digest(selected)
    prefix = MASTER_PREFIX if is_master(selected) else PREFIX
    selected = replace(selected, template=prefix + digest) if digest else selected
    if digest and is_master(selected) and (not selected.section_order or latest_master):
        selected = replace(selected, section_order=master_section_order(selected))
    return selected


def install_master(source: Path, *, actor, expected_revision):
    """Replace the ENFRA master for future reports; retain every older version."""
    actor = library._confirmation(actor, True)
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_native_package import passive_docx
    inspection = inspect_docx(source)
    found = {item.section for item in inspection.items if item.section}
    from app.monthly_report_model import default_sections
    missing = {section.key for section in default_sections() if not section.appendix} - found
    if missing:
        raise ValueError("The master needs every standard report section. Missing: " + ", ".join(sorted(missing)) + ".")
    passive_docx(source)
    directory = library._root() / "designs" / "master"
    with library._locked(directory):
        current = master_state()
        if current["revision"] != expected_revision:
            raise library.RevisionConflict("The master design changed. Reopen design settings before updating it.")
        digest = inspection.sha256
        if current.get("default") == digest:
            return digest
        from app.monthly_report_objects import store_file
        store_file(directory / (digest + ".docx"), source)
        library._atomic_write(directory / "metadata" / (digest + ".json"), library._json(
            {"schema": 1, "hash": digest, "section_order": _inspection_order(inspection)}))
        value = {"schema": 1, "revision": current["revision"] + 1, "default": digest,
                 "history": [*current.get("history", []), {"hash": digest, "actor": actor, "at": library._now()}]}
        library._atomic_write(directory / "history" / f'{value["revision"]:08d}.json', library._json(value))
        library._atomic_write(directory / "manifest.json", library._json(value))
    return digest


def install(source: Path, profile, *, actor, expected_revision):
    """Save the reference's layout only; no source values enter the draft."""
    actor = library._confirmation(actor, True)
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_native_package import passive_docx
    inspection = inspect_docx(source)
    if not any(item.section for item in inspection.items):
        raise ValueError("Choose an ENFRA monthly report with recognizable section headings.")
    # Validate passive rendering before making the reference selectable.
    passive_docx(source)
    directory = _directory(profile.contract)
    with library._locked(directory):
        current = state(profile.contract)
        if current["revision"] != expected_revision:
            raise library.RevisionConflict("Another report design was saved. Reopen the design settings before replacing it.")
        digest = inspection.sha256
        if current.get("profiles", {}).get(profile.key) == digest:
            return replace(profile, template=PREFIX + digest)
        from app.monthly_report_objects import store_file
        store_file(directory / (digest + ".docx"), source)
        value = {"schema": 1, "revision": current["revision"] + 1,
                 "default": current.get("default") or digest,
                 "profiles": {**current.get("profiles", {}), profile.key: digest},
                 "history": [*current.get("history", []), {"hash": digest, "profile": profile.key,
                              "actor": actor, "at": library._now()}]}
        library._atomic_write(directory / "history" / f'{value["revision"]:08d}.json', library._json(value))
        library._atomic_write(directory / "manifest.json", library._json(value))
    return replace(profile, template=PREFIX + digest)
