"""Synthetic legacy-to-contract workflow durability across two real code revisions.

Both checkouts run separate interpreters against one new owned temporary data
root. No production restart, service, authentic source or hand-written manifest.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASELINE = "a1b2aa61aa92c596d424c95dba29be66135f3441"
WORKER = r'''
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image
import pymupdf
from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_workflow_standards as workflows
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles

stage, receipt_path = sys.argv[1:]
receipt_path = Path(receipt_path)
profile = replace(synthetic_profiles()[0], contract="Synthetic Upgrade Contract A", key="synthetic-upgrade-site")
period = ReportPeriod(2026, 9)
key = "business_hours_workflow"
def report(target=profile, blocks=(), month=9):
    # Invented records in a disposable root; synthetic=False deliberately
    # exercises the actual reviewed standing-data API, not demo bypasses.
    return ReportDraft(target, ReportPeriod(2026, month), "Synthetic Upgrade Editor", (), blocks)
def disk():
    return {str(p.relative_to(library._root())): sha256(p.read_bytes()).hexdigest()
            for p in library._root().rglob("*") if p.is_file() and p.suffix != ".lock"}
def verify_reports(expected):
    for revision in (1, 2):
        saved = library.load_snapshot_version(profile.contract, profile.key, period, revision)
        assert saved is not None and saved.revision == revision
        assert saved.draft.fingerprint == expected["report_fingerprints"][str(revision)]
        assert sha256(sources.source_bytes(profile, saved.draft.sources[0])).hexdigest() == expected["source_sha256"]
        assert sha256(library.read_asset(profile.contract, profile.key, saved.draft.blocks[0].asset_hashes[0])).hexdigest() == expected["asset_sha256"]
    current = library.load_snapshot(profile.contract, profile.key, period)
    assert current.revision == 2 and current.draft.fingerprint == expected["report_fingerprints"]["2"]

if stage == "baseline-write":
    library.save_profile(profile, expected_revision=0, actor="Synthetic Upgrade Editor", confirmed=True)
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), "TEST ONLY - invented upgrade original, September 2026")
        original_bytes = document.tobytes()
    source, _ = sources.ingest(profile, "synthetic-upgrade-original.pdf", original_bytes)
    picture = BytesIO()
    Image.new("RGB", (40, 30), "navy").save(picture, "PNG")
    raw = picture.getvalue()
    asset = library.asset_reference(raw, "png")
    block = approve_all_assets(ResolvedBlock(key, "Library", asset_hashes=(asset,),
                                            asset_captions=("Synthetic report-only caption",)))
    library.save_import(profile.contract, profile.key, (block,), assets=((asset, raw),),
                        expected_revision=1, actor="Synthetic Upgrade Editor", confirmed=True)
    draft = replace(report(blocks=(block,)), sources=(source.source,))
    first = library.save_snapshot(draft, expected_revision=0)
    second = library.save_snapshot(replace(draft, blocks=(block, ResolvedBlock(
        "activity_summary", "This month", text="Synthetic September work only"))), expected_revision=1)
    legacy = workflows.seed_from_saved_profile(profile.contract, profile.key)
    assert legacy.revision == 1 and len(legacy.workflows) == 1
    expected = {"source_sha256": sha256(original_bytes).hexdigest(), "asset_sha256": sha256(raw).hexdigest(),
                "report_fingerprints": {"1": first.draft.fingerprint, "2": second.draft.fingerprint},
                "legacy_fingerprint": legacy.workflows[0].block.fingerprint, "original_files": disk()}
    verify_reports(expected)
    receipt_path.write_text(json.dumps(expected, indent=2) + "\n")
else:
    expected = json.loads(receipt_path.read_text())
    verify_reports(expected)
    before = disk()
    assert all(before[path] == digest for path, digest in expected["original_files"].items())
    if stage == "candidate-upgrade":
        own, foreign = report(month=10), report(replace(profile, contract="Synthetic Upgrade Contract B"), month=10)
        for draft in (own, foreign):
            assets = {}
            assert workflows.apply_defaults(draft, assets) == draft and assets == {}
        assert disk() == before  # Opening either contract is read-only.
        legacy = workflows.legacy_candidate(profile.contract, key)
        assert legacy.block.fingerprint == expected["legacy_fingerprint"]
        assert workflows.legacy_candidate(foreign.profile.contract, key) is None
        try:
            workflows.adopt_legacy(foreign, key, expected_revision=0,
                                  expected_legacy_fingerprint=legacy.block.fingerprint, confirmed=True)
        except library.RevisionConflict:
            pass
        else:
            raise AssertionError("Foreign adoption unexpectedly succeeded")
        assert disk() == before
        adopted = workflows.adopt_legacy(own, key, expected_revision=0,
                                         expected_legacy_fingerprint=legacy.block.fingerprint, confirmed=True)
        assert adopted.revision == 1
        assets = {}
        next_month = workflows.apply_defaults(own, assets)
        assert len(next_month.blocks) == 1 and next_month.blocks[0].key == key
        assert sha256(next(iter(assets.values()))).hexdigest() == expected["asset_sha256"]
        assert not next_month.blocks[0].asset_captions  # Report-only caption is not a default.
        override = replace(own, blocks=(ResolvedBlock(key, "This month", text="Keep report-specific override"),))
        omitted = replace(own, blocks=(ResolvedBlock(key, "Omit"),))
        assert workflows.apply_defaults(override, {}) == override
        assert workflows.apply_defaults(omitted, {}) == omitted
        assert workflows.apply_defaults(foreign, {}) == foreign
        try:
            workflows.adopt_legacy(own, key, expected_revision=0,
                                  expected_legacy_fingerprint=legacy.block.fingerprint, confirmed=True)
        except library.RevisionConflict:
            pass
        else:
            raise AssertionError("Stale adoption unexpectedly overwrote current procedures")
        assert workflows.load_standards(profile.contract) == adopted
        assert (workflows._path(profile.contract) / "history" / "00000001.json").is_file()
        verify_reports(expected)
        after = disk()
        assert all(after[path] == digest for path, digest in expected["original_files"].items())
    elif stage == "baseline-readback":
        legacy = workflows.load_standards()
        assert legacy.revision == 1 and legacy.workflows[0].block.fingerprint == expected["legacy_fingerprint"]
        assert disk() == before
    else:
        raise ValueError(stage)
print(json.dumps({"stage": stage, "result": "passed", "source_sha256": expected["source_sha256"],
                  "report_fingerprints": expected["report_fingerprints"]}))
'''


def revision(path):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline, candidate = args.baseline.resolve(), args.candidate.resolve()
    assert revision(baseline) == BASELINE, "Baseline must be the exact recorded main revision"
    record = {"synthetic_only": True, "baseline": BASELINE, "candidate": revision(candidate),
              "limits": ["No served browser or production restart", "Baseline readback of retained records is not a downgrade-policy approval"],
              "steps": [], "result": "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="monthly-workflow-upgrade-") as temp:
            root = Path(temp)
            env = dict(os.environ, EPC_DATA_DIR=str(root / "data"), ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
            env.pop("PYTHONPATH", None)
            for stage, checkout in (("baseline-write", baseline), ("candidate-upgrade", candidate), ("baseline-readback", baseline)):
                result = subprocess.run([sys.executable, "-c", WORKER, stage, str(root / "receipt.json")],
                                        cwd=checkout, env=env, text=True, capture_output=True, timeout=60)
                step = {"stage": stage, "revision": revision(checkout), "returncode": result.returncode,
                        "stdout": result.stdout, "stderr": result.stderr}
                record["steps"].append(step)
                assert result.returncode == 0, json.dumps(step, indent=2)
            record["result"] = "passed"
    finally:
        args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
