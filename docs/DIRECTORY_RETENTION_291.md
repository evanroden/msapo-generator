# Directory original retention: #291 verification

Refs #291. The product policy is already merged/deployed; these are synthetic,
local-only regression and evidence paths. They do not change retention, access,
production settings or any live-run permit. Keep #291 open until review and the
applicable checks for the final evidence commit are confirmed.

## Policy and current implementation

The [recorded decision](https://github.com/evanroden/msapo-generator/issues/291#issuecomment-6306420467)
keeps a confirmed directory workbook for 30 days after its latest confirmed
import. Legacy originals get a full period beginning at their first sweep.
Derived contacts/sites, revisions, history, fingerprints and cell references
remain. Deleting the directory link must not remove bytes referenced elsewhere.
Access remains shared. The implementation merged in #362 as
`344cefb6c9c5106db11a470c6e394df61b2a9a29`.

## Repository regression paths

- `tests/test_monthly_report_directory_retention.py`: expiry, refresh, shared
  references, legacy grace, failed source/pool deletion and retry, unreadable
  timestamps, and hourly/routine sweep controls.
- `tests/test_monthly_report_directory_retention_journey.py`: actual AppTest
  import/Storage handlers with a disposable store and 29/31-day fixture time,
  preserving saved/history/other-namespace/report-reference data.
- `tests/test_monthly_report_directory_retention_controls.py`: four spawned-process
  races (import-first/expiry-first, with/without same-byte report references), two
  independent real kernel-contention probes per race, exact 30-day threshold,
  and archive/restore after raw expiry. The scheduler delegates the original
  flock/save/expiry implementations; it does not replace them. Receipts stay in
  each test's own pytest temporary directory.
- `scripts/compare_directory_retention_policy.py`,
  `scripts/directory_retention_policy_probe.py` and
  `scripts/directory_retention_fixture.py`: the same retrospective policy oracle
  on exact pre-policy/current source archives, with a source-generated invented
  workbook, described below.
- `tests/test_directory_retention_policy_comparison.py`: fail-closed source-ref,
  output reuse, extraction and preservation-evidence validation.
- `.github/workflows/directory-retention-lifecycle.yml`: read-only, PR-only
  hosted local tests. No browser, production URL, dispatch, environment secret,
  fixture admission, production cleanup or live permit. It preserves synthetic
  receipts, JUnit, logs and comparison metadata for the exact CI source commit.

The initial integrated local focused suite passed 46 tests. The separate comparison
verified the expected pre-policy failure and current-code pass. Independent
review and exact-head hosted results must be recorded before final integration.

## Reproduce the comparison

Use a complete local clone and the project's locked test dependencies:

```sh
python -m pip install -r requirements-dev.lock
python scripts/compare_directory_retention_policy.py \
  --after "$(git rev-parse HEAD)" \
  --output test-artifacts/directory-retention-comparison-new
```

The output directory must not exist. The runner performs no fetch; the audited
pre-policy commit `45ecc27b7948423049404a70ed58d3f1155c6c2b` must already be present.
The helper `scripts/directory_retention_fixture.py` generates a wholly invented
workbook inside that new output directory, including hidden/inactive/excluded
rows. Ordinary openpyxl cell construction, fixed document properties and stored
ZIP entries produce a pinned SHA-256:
`854e76ae35afc67f7a6cfbbd2162ac02c6fe2c89e15a476d6aa0e2cbabb23baa`.
No workbook binary is tracked. Both comparison phases consume this same generated
file. Its semantic cells and hidden-sheet state match the original synthetic
workbook, but its normalized ZIP bytes deliberately differ from the historical
fixture `32f56e5c991c91eb0d328858848b1c998ff4422e7abdef6aca1d22478ad4bf8e`.

Each phase uses a fresh interpreter, source archive, HOME and pytest-owned store.
All tracked source blobs are checked against Git before and after execution.
The runner accepts before exit 1 only with matching exact source/fixture identity,
all preservation checks true, raw/stamp/pool retained, and the explicit expiry
oracle failure. After must exit 0 and all eligible raw/stamp/pool paths must be
absent. Both observations and pytest logs are retained even though the before
failure is expected. Unexpected outcomes make the comparison fail.

## Preserved first retrospective observation

The [initial source receipt](evidence/directory-retention-291/source-provenance.json)
records all 825 before and 1,381 after blobs verified against exact source trees.

| Phase | Commit / tree | Initial result |
| --- | --- | --- |
| Pre-policy PR #362 base | `45ecc27b7948423049404a70ed58d3f1155c6c2b` / `8242ac09c1760fb84eb9c560bc2af9611f92445a` | [1 failure](evidence/directory-retention-291/before-policy-pytest.log), specifically raw expiry; [observation](evidence/directory-retention-291/before-policy-observation.json) |
| Deployed product | `df8b748325bd096a7affcf4f30671e82e852ae00` / `709b9a0b6986e1610880efe46eeb0a8af4a3835d` | [1 pass](evidence/directory-retention-291/after-policy-pytest.log); [observation](evidence/directory-retention-291/after-policy-observation.json) |

Both phases verified preview/unconfirmed uploads did not persist raw bytes;
confirmed import preserved the exact original; archived history, fingerprints
and the ordinary-root synthetic canary remained unchanged. Opening Storage alone
did not expire it. The actual AppTest `report_storage_check` action was used.

This is a **retrospective policy comparison**, not an original historical defect
report. The issue's original baseline was owner-decision-required. The before
commit is the PR's recorded base, not its merge's immediate first parent. Both
phases receive an explicit 31-day-old fixture stamp; pre-policy code does not
recognize that metadata. The same current dependency environment is used, not
reconstructed historical dependencies. The repository probe retains the
initial lifecycle and preservation assertions, adapting source/output paths and
identity fields. Current reruns use the source-generated, semantically matching
fixture described above, not the historical ZIP bytes. The first logs/observations
and their original fixture hash are unchanged; new CI results are separate
artifacts.

## Preserved integration failure and narrow repair

The first minimal integration at `485343f1a7939058353ea30c5810342d023ae2a2`
passed focused retention checks, then [full run 42360194886](https://github.com/evanroden/msapo-generator/actions/runs/42360194886)
reported 12,047 passes, two failures and two skips. Both failures were integration
rules missed by the initial patch: this guide was absent from `docs/README.md`,
and tracking the generated XLSX violated public-repository hygiene. No retention
assertion failed. The [first JUnit artifact](https://github.com/evanroden/msapo-generator/actions/runs/42360194886/artifacts/13571988471)
remains preserved, ZIP SHA-256
`5a3d21cc852f8d16f407c0df73c53db399d83a1f9620d8f2a9ce83a3dfefffed`.

The repair indexes the guide and generates the workbook from readable source at
runtime instead of tracking a binary. Neither existing repository check nor its
allowlist was weakened. The focused lifecycle workflow now also runs the unchanged
docs-index and repository-hygiene tests, so these failures are caught early. The
repaired focused suite passed 116 tests locally, including both formerly failing
repository checks. The prior commit and first-failure evidence remain intact;
this is a new-head repair,
not a retry that hides the first result. The two original skips were optional YAML
and Playwright imports, not retention cases.

## Native served evidence, already complete

The [deployed acceptance specification](https://github.com/evanroden/msapo-generator/issues/291#issuecomment-6307268805)
is import of a synthetic workbook, import/Storage retention captions, and
unchanged saved history. The single approved live core run completed that journey:

- [Run 42357267337](https://github.com/evanroden/msapo-generator/actions/runs/42357267337),
  attempt 1, job `128357986202`, test head `caeabe2f5366b4a5cfbc9ad5294524c2c9fb3747`.
- Served product `df8b748325bd096a7affcf4f30671e82e852ae00`, checked repeatedly by
  served-build/identity guards and fresh deployment evidence.
- [Artifact 13568148755](https://github.com/evanroden/msapo-generator/actions/runs/42357267337/artifacts/13568148755),
  ZIP SHA-256 `2b29e7d5d50b4f5df75468589af8c8a2623224fbf5f7e4677ef32d02b7ece628`.
- 31 completed native UI actions, no blocked requests or browser faults. Eight
  screenshots independently inspected: both disclosures and matching Version 1,
  saved contacts/history after reload and Storage. The one-run permit was removed.
- Separate loopback run `42353253541`, artifact `13566580874`, provides original/
  pooled byte and hard-link identity receipts and unchanged ordinary-root canary.

No new live test is requested or needed by this test-only integration. The live
run did not verify remote raw bytes or a physical storage root; those fields stay
false. Raw-byte and elapsed-threshold evidence is local. Source/control-plane
isolation proof is distinct from filesystem inspection.

## Remaining scope limits

These local tests use injected time, not 30 calendar days of observation. The
process races cover two controlled orderings on Linux local filesystem locks,
not all crashes or distributed filesystems. AppTest is not substituted for the
separate native served journey. Native CSV export is not claimed: the issue's
stated served gate does not require it, and the auxiliary CSV/picker investigation
must not become a new retention acceptance requirement. All prior first-failure
artifacts remain linked in draft #800.
