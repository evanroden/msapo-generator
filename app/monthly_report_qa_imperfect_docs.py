"""Load immutable, entirely synthetic imperfect DOCX/PDF fixtures for isolated QA.

Files are checked in once, with a hash-pinned archive and per-file provenance.
No invented substitute parser, paid model, generated client bytes or network access.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import json

from app.monthly_report_testing import scope


_PACK = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixtures" / "monthly_report" / "imperfect_vendor_chemical"
    / "ENFRA_Synthetic_Imperfect_Vendor_Chemical_QA_Pack.zip"
)
_PACK_SHA256 = "c767124fb922445ced29c07de7755567f3adf6945b2218021584aa8f325c627f"
_CONTRACT = "QA Demonstration - Synthetic Only"


def load_pack() -> bytes:
    """Return original fixture bytes only from a verified isolated QA context.

    Every read checks both archive and member digests. A missing/corrupt
    package fails closed; it never downloads an unverified replacement.
    """
    if scope() is None:
        raise ValueError("Synthetic fixture loading requires isolated QA.")
    raw = _PACK.read_bytes()
    if sha256(raw).hexdigest() != _PACK_SHA256:
        raise ValueError("The synthetic fixture archive failed integrity verification.")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            if archive.testzip() is not None:
                raise ValueError("The synthetic fixture archive contains corrupted members.")
            files = set(archive.namelist())
            if "MANIFEST.json" not in files:
                raise ValueError("Synthetic fixture manifest is missing.")
            manifest = json.loads(archive.read("MANIFEST.json"))
            if (manifest.get("testing_target", {}).get("contract") != _CONTRACT
                    or not isinstance(manifest.get("files"), list)
                    or len(manifest["files"]) != 9):
                raise ValueError("Synthetic fixture identity or file inventory is invalid.")
            declared = set()
            for item in manifest["files"]:
                name = item.get("name")
                if (not isinstance(name, str) or not name.startswith("QA_")
                        or not name.endswith((".pdf", ".docx"))
                        or "/" in name or "\\" in name or name not in files
                        or name in declared):
                    raise ValueError("Synthetic fixture filename is invalid.")
                declared.add(name)
                contents = archive.read(name)
                if (len(contents) != item.get("bytes")
                        or len(contents) > 30 * 1024 * 1024
                        or sha256(contents).hexdigest() != item.get("sha256")):
                    raise ValueError("A synthetic fixture member failed integrity verification.")
            if set(n for n in files if n.startswith("QA_")) != declared:
                raise ValueError("Synthetic fixture member inventory does not match the manifest.")
    except (BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("The synthetic fixture archive cannot be trusted.") from exc
    return raw
