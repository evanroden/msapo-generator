# MSAPO rollback rehearsal record

**Date:** 2026-11-11. **Environment:** local isolated Python 3 + SQLite temporary directory, entirely synthetic. **Run command:** `python3 docs/azure/synthetic_cutover_rehearsal.py`. **Result:** **8/8 simulated safety-invariant assertions PASS, 0 FAIL**. This is **NOT a rehearsed Render→Azure backup/restore or reverse migration**, and does not certify actual RTO/RPO, enterprise authentication, Azure storage semantics or real data. No real app, employee data, AI, Smartsheet, Render or Azure infrastructure was accessed by this test.

## Executed synthetic checks

| Case | Stimulus and oracle | Result | Proof limit |
|---|---|---|---|
| R01 Writer handoff | Reject direct Render→Azure transfer; require intermediate zero-writer fence | PASS | In-memory model; no Render process/network fence |
| R02 Frozen snapshot | Back up 2 local SQLite databases and one synthetic original after quiescence; 3/3 SHA256 checks and DB rows equal | PASS | Tests model's backup, not `scripts/migrate_data.py` or real authoritative-store inventory |
| R03 Corrupt transfer | Replace copied original bytes and require hash verification failure | PASS | Synthetic file only; no archive-partial or Azure Blob failure |
| R04 Image-only rollback | Change simulated image pointer, retain 2/2 existing Azure-side report records | PASS | Does not run a previous real MSAPO image |
| R05 Data rollback/replay | Demonstrate a pre-cutover snapshot contains 1 record after Azure has accepted 2; replay 1 newly acknowledged change, recover 2/2 | PASS | In-memory change journal; real event capture/delta/consistency not implemented |
| R06 Idempotent replay | Replay identical synthetic report ID twice; retain 2/2 without duplicate; separate claim DB retained | PASS | Does **not** verify remote Smartsheet side effects or claim store atomicity |
| R07 Schema downgrade guard | Incompatible schema v2 disallows simulated app-only revert supporting max v1 | PASS | No schema map/real DB migrations exercised |
| R08 Stale writer denial | Reject incorrect old-owner attempt to change writer when both are fenced | PASS | Does not prove App Service/Render lease durability |

**Console summary:** `Synthetic cutover invariant model: 8 PASS, 0 FAIL`. Test file is included for local reproduction. It uses synthetic IDs/content only and cleans up the temporary directory.

## Adjacent A09 evidence and required target-environment rehearsals

A09 draft [#852](https://github.com/evanroden/msapo-generator/pull/852) reports a POSIX/SQLite fenced snapshot/import/reconcile wrapper and synthetic failure/retry tests. A05/A09 draft [#851](https://github.com/evanroden/msapo-generator/pull/851) reports isolated PostgreSQL/blob contracts without integrations. Neither is merged, live tested or independently executed in **this** rehearsal. The eight local results below are only from the included standalone model; do not combine them with claimed PR tests into an acceptance tally.

### Required but NOT executed target-environment rehearsals (NO-GO until closed)

- **TR01** Run the *actual candidate* on an isolated App Service instance and chosen datastore. Confirm storage locks, atomicity, hard links/objects, private permissions, version/restore behavior, start/stop overlap and one-writer enforcement with parallel clients.
- **TR02** Test the selected A09 migration implementation against realistic synthetic **all-store** data (reports/history, source files/artifacts, directories/designs/contacts, approvals, browser-recovery and Smartsheet claim state). Freeze source, export consistently, import idempotently to blank target; reconcile 100% counts/hashes/relationships/versions.
- **TR03** Interrupt export, transfer, import and DB migration; poison or omit file; attempt repeated import into nonempty target; prove clean rejection and recovery without overwriting accepted target data.
- **TR04** Execute actual application rollback digest `D→D-1` **without** data rewind; test known DB schema backwards compatibility, report save/reopen and DOCX/PDF fidelity. If incompatible, demonstrate roll-forward.
- **TR05** Generate new Azure acknowledged writes after imported snapshot, perform controlled Azure failure/recovery and **journal/replay/reconcile** each write and remote claim. Verify 0 lost acknowledgements, 0 duplicates and all original hashes.
- **TR06** Prove a reverse path to Render is possible **only with validated backward schema adapter and Azure delta replay**, using isolated stores and host write fences; otherwise expressly remove “return to Render” from automated rollback choices and use forward repair.
- **TR07** Exercise authenticated enterprise DNS/TLS and app origin change in nonproduction, plus stale old URL tabs, reconnect, session cookies, direct URL bypass and old pipeline accidental deployment.
- **TR08** Measure restore and repair elapsed time and maximum acknowledged-data exposure against ENFRA-approved RTO/RPO (values currently unknown). Simulate incident, escalation, on-call paging and approvals.

## Release decision

**NO-GO for a real cutover.** The local model supports why the playbook must fence writes and replay deltas, but does not establish that current MSAPO implements these guarantees on ENFRA Azure. A09/A05/A07/A11 must sign TR01–TR08 evidence and verify selected schema/storage interfaces before A12 changes this state. Do **not** label these eight local passes as Azure migration acceptance.