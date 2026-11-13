"""Focused synthetic A02 governance checks; no credentials, network or deploy."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migration_preflight", ROOT / "scripts/azure/github_migration_preflight.py")
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class MigrationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for rel in module.REQUIRED:
            f = self.root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("synthetic\n")
        (self.root / ".github/workflows").mkdir(parents=True)
        self.config(False, False, "preparation")

    def config(self, azure, render, phase):
        path = self.root / module.CONTROL
        path.write_text(json.dumps({
            "schema_version": 1, "phase": phase,
            "azure_deployment_enabled": azure,
            "render_automation_retired": render,
        }))

    def test_read_only_preparation(self):
        (self.root / ".github/workflows/tests.yml").write_text("name: Tests\npermissions:\n  contents: read\n")
        self.assertEqual(module.check(self.root), [])

    def test_azure_login_rejected_during_preparation(self):
        (self.root / ".github/workflows/deploy.yml").write_text("steps:\n  - uses: azure/login@v2\n")
        self.assertTrue(any("Azure deployment workflow" in e for e in module.check(self.root)))

    def test_duplicate_azure_render_authority_rejected(self):
        self.config(True, False, "approved_cutover")
        self.assertTrue(any("Duplicate deployment" in e for e in module.check(self.root)))

    def test_render_retired_cannot_be_claimed_in_preparation(self):
        self.config(False, True, "preparation")
        self.assertTrue(any("Preparation" in e for e in module.check(self.root)))

    def test_approved_phase_is_not_an_actual_deployment(self):
        self.config(True, True, "approved_cutover")
        (self.root / ".github/workflows/release.yaml").write_text("steps:\n  - uses: azure/webapps-deploy@v3\n")
        self.assertEqual(module.check(self.root), [])

    def test_missing_a01_contract_is_rejected(self):
        (self.root / module.REQUIRED[0]).unlink()
        self.assertTrue(any("Missing required" in e for e in module.check(self.root)))

if __name__ == "__main__":
    unittest.main()
