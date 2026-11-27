"""Keep application imports stable regardless of the pytest working directory."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# pytest's own entry point, captured before any test runs. Streamlit's AppTest
# installs the script it runs as ``sys.modules['__main__']`` (see the fixture
# below); this snapshot is what spawned children must start from again.
_REAL_MAIN_MODULE = sys.modules.get("__main__")


@pytest.fixture(autouse=True, scope="session")
def _private_memory_status_dir(tmp_path_factory):
    """Keep app.memory's failure-status files out of the machine's temp folder.

    Outage tests make the memory module record failures, and it publishes the
    counts for scripts/host_check.py in a status folder. Pointing that folder at
    a per-session directory (inherited by spawned app processes) means a test
    run never leaves counts behind for a real host check to report.
    """
    previous = os.environ.get("EPC_MEMORY_STATUS_DIR")
    os.environ["EPC_MEMORY_STATUS_DIR"] = str(tmp_path_factory.mktemp("memory-status"))
    yield
    if previous is None:
        os.environ.pop("EPC_MEMORY_STATUS_DIR", None)
    else:
        os.environ["EPC_MEMORY_STATUS_DIR"] = previous


@pytest.fixture(autouse=True)
def _restore_script_main_module():
    """Undo AppTest's replacement of ``sys.modules['__main__']`` after each test.

    A script run from a string lives in a temporary file, and
    multiprocessing's spawn start method re-executes ``__main__`` by path in
    every child it starts. A child spawned after such a test therefore
    re-runs that temporary script instead of the test target and dies on its
    first session-state read (``st.session_state['date_draft']``), so the
    fixture-process tests exit with code 1 instead of the expected 23 and
    the lifecycle events other tests wait for never fire. Restoring the
    genuine entry point after each test keeps spawned children starting
    from pytest's own no-op main.
    """
    yield
    if _REAL_MAIN_MODULE is not None:
        sys.modules["__main__"] = _REAL_MAIN_MODULE


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


@pytest.fixture(autouse=True)
def _fresh_visible_queue(monkeypatch):
    """Give every test its own A24 admission queue.

    ``QUEUE`` is process-wide and remembers how many previews were admitted in
    a row (``_preview_burst``). Without a fresh queue, a test that admits two
    previews changes which waiter the next test admits first: after
    tests/test_monthly_report_section_preview.py, a waiting export went
    ahead of a waiting Review in tests/test_review_preview_priority.py.
    """
    from app import monthly_report_visible_queue as visible
    monkeypatch.setattr(visible, "QUEUE", visible.VisibleFirstQueue())


@pytest.fixture(autouse=True)
def _fresh_source_view_cache():
    """Start each test without native source views remembered by another test.

    The cache is keyed by file bytes, so a test that patches the derivation to
    fail must not be handed a view that an earlier test built from the same
    fixture file.
    """
    from app import monthly_report_compatibility_view as compatibility_view
    compatibility_view.clear_view_cache()
    yield
    compatibility_view.clear_view_cache()


@pytest.fixture(autouse=True)
def _fresh_native_preview_caches():
    """Start each test without repeat-preview proofs remembered by another test.

    Both caches are keyed by verified source hashes, so a test that patches a
    scan or image read to fail must not be handed an earlier test's result.
    """
    from app import monthly_report_native_art_review as art
    from app import monthly_report_native_layout as layout
    art.clear_physical_cache()
    layout.clear_view_image_digests()
