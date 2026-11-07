"""Retrospective policy oracle on exact source snapshots, synthetic stores only.

Both targets receive the same invented workbook and explicit 31-day-old fixture
import stamp. The pre-policy implementation does not know that stamp. This is a
counterfactual before/after policy comparison, not a historic defect accusation,
real elapsed-time claim, or native-browser replacement.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

import pytest

BASE = Path(os.environ["RETENTION_COMPARISON_OUTPUT"]).resolve()
SOURCE = Path(os.environ["RETENTION_COMPARISON_SOURCE"]).resolve()
PHASE = os.environ["RETENTION_COMPARISON_PHASE"]
assert PHASE in {"before", "after"}
assert SOURCE == BASE / PHASE / "source"
sys.path.insert(0, str(SOURCE))
from streamlit.testing.v1 import AppTest
from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from app import monthly_report_library as library
from app import monthly_report_testing as testing
from app.monthly_report_objects import object_path

TOKEN = "91" * 16
FIXTURE = Path(os.environ["RETENTION_COMPARISON_FIXTURE"])
assert not FIXTURE.is_symlink() and FIXTURE == BASE / "synthetic-retention.xlsx"
assert FIXTURE.resolve() == FIXTURE and FIXTURE.stat().st_size <= 65536
RAW = FIXTURE.read_bytes()
DIGEST = sha256(RAW).hexdigest()
assert DIGEST == os.environ["RETENTION_COMPARISON_FIXTURE_SHA"] == "854e76ae35afc67f7a6cfbbd2162ac02c6fe2c89e15a476d6aa0e2cbabb23baa"
SOURCE_SHA = os.environ["RETENTION_COMPARISON_SHA"]


def contents(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_approved_policy_erases_eligible_raw_but_preserves_derived_history(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    ordinary = tmp_path / "monthly_reports"
    ordinary.mkdir()
    (ordinary / "synthetic-control.bin").write_bytes(b"invented ordinary-root canary")
    ordinary_before = contents(ordinary)
    with testing.isolated(TOKEN):
        root = library._root()
        assert root != ordinary and not root.is_relative_to(ordinary)
        source = root / "directory_sources" / (DIGEST + ".xlsx")
        stamp = source.with_suffix(".imported")
        plan = batch.prepare_workbook(directory.inspect_workbook(RAW))
        assert len(plan.entries) == 1 and plan.entries[0].contract == "Synthetic Retention"
        assert len(plan.entries[0].sites) == 1
        assert {x.worksheet for x in plan.exclusions} >= {"Active Contracts", "Index", "Hidden Retention Archive"}
        assert not source.exists()  # Preview alone does not persist raw bytes.
        with pytest.raises(library.LibraryError):
            batch.save_workbook_plan(plan, RAW, actor="Synthetic Comparison", confirmed=False)
        assert not source.exists()  # Rejected unconfirmed input is not retained.
        result = batch.save_workbook_plan(plan, RAW, actor="Synthetic Comparison", confirmed=True,
                                         create=tuple(e.contract for e in plan.entries if e.new_contract))
        assert result.saved == ("Synthetic Retention",)
        assert source.read_bytes() == RAW
        archived = directory.archive_directory("Synthetic Retention", expected_revision=1,
                    actor="Synthetic Comparison", confirmed=True)
        history_before = contents(root / "directory")
        imported = datetime.now(timezone.utc) - timedelta(days=31)
        stamp.write_text(imported.isoformat(), encoding="ascii")
        pooled = object_path(source)
        assert pooled.read_bytes() == RAW

    app = AppTest.from_string("""
from app.monthly_report_testing import isolated
from app.monthly_report_admin_ui import render_storage_maintenance
with isolated('91919191919191919191919191919191'):
    render_storage_maintenance()
""", default_timeout=20).run()
    assert not app.exception and not app.error
    assert source.exists()  # Opening Storage alone is not its maintenance action.
    app.button("report_storage_check").click().run()
    assert not app.exception and not app.error
    with testing.isolated(TOKEN):
        history_same = contents(root / "directory") == history_before
        archive_same = directory.load_directory("Synthetic Retention", include_archived=True) == archived
        fingerprint_same = archived.source_sha256 == DIGEST
        record = {"source_sha": SOURCE_SHA, "source_snapshot": PHASE,
                  "fixture_sha256": DIGEST, "synthetic_only": True, "fixture_age_days": 31,
                  "native_browser": False, "real_calendar_elapsed": False,
                  "before_action_raw_exact": True, "preview_and_unconfirmed_not_persisted": True,
                  "raw_remaining": source.exists(), "stamp_remaining": stamp.exists(),
                  "unreferenced_pool_remaining": pooled.exists(),
                  "history_unchanged": history_same, "archived_state_unchanged": archive_same,
                  "fingerprint_preserved": fingerprint_same,
                  "ordinary_root_unchanged": contents(ordinary) == ordinary_before,
                  "storage_captions": [c.value for c in app.caption]}
        with (BASE / PHASE / "observation.json").open("x") as out:
            json.dump(record, out, indent=2)
        assert history_same and archive_same and fingerprint_same
        assert contents(ordinary) == ordinary_before
        assert not source.exists(), "Approved-policy oracle: eligible raw workbook must expire"
        assert not stamp.exists() and not pooled.exists()
        assert any("deleted 30 days after their latest import" in c.value for c in app.caption)
