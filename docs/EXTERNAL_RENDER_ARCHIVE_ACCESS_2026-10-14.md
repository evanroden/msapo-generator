# External-agent retrieval of Render QA archives

**Status: retrieval tool implemented; actual owner archive upload and a cross-deploy byte comparison remain open.** This document describes the existing Render archive shelves, not an assertion that either shelf already contains owner data. See the [current remaining-work ledger](PHASE1_PHASE2_REMAINING_2026-10-14.md) for dated witnesses and precise blocked operations.

## Location and access

Production testing route: https://msapo-generator.onrender.com/?workflow=monthly&monthly_qa=fixtures

The existing Render service uses an attached persistent disk, mounted at `/test1`. The two immutable shelves in the existing shared test area are separate from disposable report drafts, AUTH01–03 fixtures, standing client data, designs and maintenance history.

- **Originals:** "Immutable six-source reference archive for external testers"; only the one six-source owner ZIP format, verified on admission and each download.
- **Synthetic:** "Synthetic QA evidence archive for external agents"; separate bounded ZIP and independent receipt.

**No login is required.** Anyone who finds the testing URL can view or download uploaded archives. This was the owner's explicit shared-testing preference; it is **not confidentiality** or an invitation to upload unrelated customer files. Do not copy client binaries, presigned links, names or hashes into public Git, CI artifacts or logs.

## Fetch and verify from a non-ChatGPT agent

Check out the public application repository, install Playwright locally, and obtain the expected *full archive* SHA-256 and exact byte count **independently** from the owner's original archive or preserved owner manifest, not merely the remote shelf caption. Then run:

```bash
python -m pip install playwright==1.58.0
python -m playwright install chromium
python -m scripts.qa_fetch_render_archive \
  --archive-kind originals \
  --archive-sha256 "<independent-64-hex-archive-SHA256>" \
  --archive-size "<exact-original-ZIP-byte-count>" \
  --output ./enfra-original-sources.zip
```

For previously stored synthetic test evidence, use `--archive-kind synthetic` with that archive's own expected hash/length and an appropriate output name. The optional `--bundle-prefix` takes the visible 12-hex archive prefix to select a specific immutable version. A standalone browser can perform the same steps manually via the test page.

The command:
1. Reads the *actual served Git commit* from the existing isolated QA build marker.
2. Opens the existing no-login shelf, finds the archive with exactly the independently supplied hash and length, and verifies the native download control's **full** stored bundle ID plus hash binding.
3. Clicks the existing deferred download without resetting a test run or modifying standing data.
4. Checks the actual served commit again. The entire downloaded ZIP must match the expected SHA-256 and exact length before it creates a local `.zip` file; an existing local file is never overwritten.
5. Emits **metadata-only** JSON: bundle ID, SHA-256, size and served commit. Client files remain on the requesting agent's filesystem and never enter CI.

If the shelf is empty, says no matching archive, or Render is restarting, the command fails without creating a partially accepted local output. An absent file is not an empty or approved report.

## Separate deployment-retention evidence

Use the existing manually dispatched [Shared Archive Redeploy Read-only](https://github.com/evanroden/msapo-generator/actions/workflows/shared-archive-redeploy-readonly.yml) workflow to download a *known existing* original on the **before** served build and again on a **different after** served build. It records hash-only receipts (not source bytes), and the comparison must reject wrong IDs, unequal hashes/sizes, unchanged served commits or outdated receipt timestamps.

The external download command verifies one retrieval; it does **not** substitute for the two-served-build witness. CI, screenshots, native Microsoft Word/Adobe output review and owner acceptance remain different evidence levels. Report imports AUTH01–03 require independent scenario labels, source/target facts and actual approved owner files; a six-source reference ZIP alone does not satisfy them.

## Immutable archive and rollback boundaries

The source/evidence ZIPs are not stored in public Git, in Docker images, or in short-lived GitHub Actions artifact storage. They reside on the live Render persistent disk **only after a successful explicit upload** via the browser. A code revert should leave verified disk originals untouched. Render disk snapshots are not an independent geographically redundant backup; retain the owner Library copy separately. Deleting this ChatGPT conversation is not proof of Render upload or shared availability.

Start future work by checking the exact GitHub main SHA, Render served SHA, displayed stored archive digest/size, last hash-only verification receipts, and the [current remaining-work ledger](PHASE1_PHASE2_REMAINING_2026-10-14.md). The [execution record](PHASE1_PHASE2_EXECUTION_2026-10-13.md) retains historical coverage. Never silently select an AUTH scenario from a filename or infer owner acceptance from synthetic tests.
