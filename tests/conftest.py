"""Keep application imports stable regardless of the pytest working directory."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def libreoffice_can_convert() -> bool:
    """Whether LibreOffice can actually open a DOCX or XLSX here.

    ``shutil.which("soffice")`` is NOT enough. ``libreoffice-core`` alone puts
    the binary on PATH while shipping neither import filter, so a conversion
    fails with "source file could not be loaded" -- a red test that looks like a
    code regression and is not one. This container is exactly that case.

    The filter registries are the thing that has to be present, and they arrive
    with ``libreoffice-writer`` and ``libreoffice-calc``. Probing for them rather
    than running a trial conversion keeps collection fast and deterministic.

    Skipping here is safe ONLY because CI cannot lose those packages silently:
    ``tests/test_expense_deployment.py`` pins the workflow's apt list against the
    Dockerfile's. Before that pin existed, every renderer test skipped on CI and
    the combined-PDF test had never once run there. Do not loosen one without
    the other.
    """
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        return False
    registry = Path(binary).resolve().parent.parent / "share" / "registry"
    if not registry.is_dir():
        registry = Path("/usr/lib/libreoffice/share/registry")
    return (registry / "writer.xcd").exists() and (registry / "calc.xcd").exists()


requires_libreoffice = pytest.mark.skipif(
    not libreoffice_can_convert(),
    reason=(
        "LibreOffice cannot convert here: the writer/calc import filters are "
        "missing (libreoffice-core alone is not sufficient)"
    ),
)
