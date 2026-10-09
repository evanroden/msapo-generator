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


def _metadata(profile, digest):
    directory = library._root() / "designs" / "master" if is_master(profile) else _directory(profile.contract)
    path = directory / "metadata" / (digest + ".json")
    if not path.exists():
        return {}
    value = library._read(path)
    if "companion_sha256" in value:
        from app.monthly_report_render_profile import identity
        if any(not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]) for key in ("source_sha256", "companion_sha256")):
            raise ValueError("The saved PDF rendering profile failed its integrity check.")
        if identity(value.get("source_sha256", ""), value["companion_sha256"], value.get("render_profile")) != digest:
            raise ValueError("The saved PDF rendering profile failed its integrity check.")
        companion = directory / (value["companion_sha256"] + ".pdf")
        if not companion.is_file():
            raise ValueError("The saved companion PDF failed its integrity check.")
        with companion.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != value["companion_sha256"]:
                raise ValueError("The saved companion PDF failed its integrity check.")
    return value


def render_profile_for(profile):
    from app.monthly_report_render_profile import validate_profile
    digest = _digest(profile)
    metadata = _metadata(profile, digest) if digest else {}
    return validate_profile(metadata.get("render_profile") if "companion_sha256" in metadata else None)


def _paired_metadata(source, source_hash, companion_pdf):
    if companion_pdf is None:
        return source_hash, {}
    from app.monthly_report_render_profile import MAX_PDF_BYTES, calibrate, identity
    companion_pdf = Path(companion_pdf)
    if not 0 < companion_pdf.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("The companion PDF must be nonempty and at most 30 MB.")
    with companion_pdf.open("rb") as stream:
        pdf_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    evidence = calibrate(source, companion_pdf)
    with companion_pdf.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != pdf_hash:
            raise ValueError("The companion PDF changed during inspection. Choose it again.")
    digest = identity(source_hash, pdf_hash, evidence["render_profile"])
    return digest, {"source_sha256": source_hash, "companion_sha256": pdf_hash, **evidence}


def source_for(profile):
    digest = _digest(profile)
    if not digest:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("The saved report design reference is invalid.")
    metadata = _metadata(profile, digest)
    source_hash = metadata["source_sha256"] if "companion_sha256" in metadata else digest
    directory = _directory(profile.contract)
    candidates = [library._root() / "designs" / "master" / (source_hash + ".docx")] if is_master(profile) else [directory / (source_hash + ".docx"),
                  library._profile_path(profile.contract, profile.key) / "imports" / (source_hash + ".docx")]
    # A new site can reuse a pinned design within its own contract. Never search
    # another contract, and never choose an import by recency or filename.
    if not is_master(profile):
        candidates.extend((library._root() / "library" / library._contract_directory(profile.contract)).glob("*/imports/" + source_hash + ".docx"))
    for path in candidates:
        if path.is_file():
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != source_hash:
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


def install_master(source: Path, *, actor, expected_revision, companion_pdf=None):
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
    digest, paired = _paired_metadata(source, inspection.sha256, companion_pdf)
    directory = library._root() / "designs" / "master"
    with library._locked(directory):
        current = master_state()
        if current["revision"] != expected_revision:
            raise library.RevisionConflict("The master design changed. Reopen design settings before updating it.")
        if current.get("default") == digest:
            return digest
        from app.monthly_report_objects import store_file
        store_file(directory / (inspection.sha256 + ".docx"), source)
        if companion_pdf is not None:
            store_file(directory / (paired["companion_sha256"] + ".pdf"), Path(companion_pdf))
        library._atomic_write(directory / "metadata" / (digest + ".json"), library._json(
            {"schema": 1, "hash": digest, "section_order": _inspection_order(inspection), **paired}))
        value = {"schema": 1, "revision": current["revision"] + 1, "default": digest,
                 "history": [*current.get("history", []), {"hash": digest, "actor": actor, "at": library._now()}]}
        library._atomic_write(directory / "history" / f'{value["revision"]:08d}.json', library._json(value))
        library._atomic_write(directory / "manifest.json", library._json(value))
    return digest


def install(source: Path, profile, *, actor, expected_revision, companion_pdf=None):
    """Save the reference's layout only; no source values enter the draft."""
    actor = library._confirmation(actor, True)
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_native_package import passive_docx
    inspection = inspect_docx(source)
    if not any(item.section for item in inspection.items):
        raise ValueError("Choose an ENFRA monthly report with recognizable section headings.")
    # Validate passive rendering before making the reference selectable.
    passive_docx(source)
    digest, paired = _paired_metadata(source, inspection.sha256, companion_pdf)
    directory = _directory(profile.contract)
    with library._locked(directory):
        current = state(profile.contract)
        if current["revision"] != expected_revision:
            raise library.RevisionConflict("Another report design was saved. Reopen the design settings before replacing it.")
        if current.get("profiles", {}).get(profile.key) == digest:
            return replace(profile, template=PREFIX + digest)
        from app.monthly_report_objects import store_file
        store_file(directory / (inspection.sha256 + ".docx"), source)
        if companion_pdf is not None:
            store_file(directory / (paired["companion_sha256"] + ".pdf"), Path(companion_pdf))
        if paired:
            library._atomic_write(directory / "metadata" / (digest + ".json"), library._json(
                {"schema": 1, "hash": digest, "section_order": _inspection_order(inspection), **paired}))
        value = {"schema": 1, "revision": current["revision"] + 1,
                 "default": current.get("default") or digest,
                 "profiles": {**current.get("profiles", {}), profile.key: digest},
                 "history": [*current.get("history", []), {"hash": digest, "profile": profile.key,
                              "actor": actor, "at": library._now()}]}
        library._atomic_write(directory / "history" / f'{value["revision"]:08d}.json', library._json(value))
        library._atomic_write(directory / "manifest.json", library._json(value))
    return replace(profile, template=PREFIX + digest)
