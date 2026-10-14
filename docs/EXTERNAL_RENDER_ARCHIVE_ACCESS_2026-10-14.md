# External-agent retrieval of Render QA archives

**Status: retrieval tool implemented; actual owner archive upload, independent external retrieval and cross-deploy byte comparison remain open.** Both source archives were recovered from owner Library and revalidated during the evening October 14 continuation. This is not an assertion that either Render shelf contains those bytes.

## Location and access

Production testing route: https://msapo-generator.onrender.com/?workflow=monthly&monthly_qa=fixtures

The existing Render service uses an attached persistent disk, mounted at `/test1`. The two immutable shelves in the shared test area are separate from disposable report drafts, AUTH01–03 fixtures, standing client data, designs and maintenance history.

- **Originals:** “Immutable six-source reference archive for external testers”; the six-source owner ZIP format, verified on admission and each download.
- **Synthetic:** “Synthetic QA evidence archive for external agents”; separate bounded ZIP and independent receipt.

**No login is required.** Anyone who finds the testing URL can view or download uploaded archives. This is the owner's explicit shared-testing preference, not confidentiality or permission to upload unrelated customer files. Do not copy client binaries, presigned links, names or source hashes into public Git, CI artifacts or logs. The current continuation authorizes uploading the two existing selected archives without altering their bytes; no upload receipt has yet been established.

## Fetch and verify from a non-ChatGPT agent

Check out the application repository, install Playwright locally, and obtain the expected *full archive* SHA-256 and exact byte count **independently** from the owner's original archive or preserved owner manifest, not merely the remote shelf caption. Then run:

```bash
python -m pip install playwright==1.58.0
python -m playwright install chromium
python -m scripts.qa_fetch_render_archive \
  --archive-kind originals \
  --archive-sha256 "<independent-64-hex-archive-SHA256>" \
  --archive-size "<exact-original-ZIP-byte-count>" \
  --output ./enfra-original-sources.zip
```

For the separate synthetic evidence, use `--archive-kind synthetic` with its own expected hash/length and output name. Optional `--bundle-prefix` takes the visible 12-hex archive prefix to select a specific immutable version. A standalone browser can perform the same steps manually via the test page. Do not include literal backticks or percent-encoded backticks in a URL.

The command:
1. Reads the actual served Git commit from the existing isolated QA build marker.
2. Opens the no-login shelf, finds the archive matching the independently supplied hash and length, and verifies the native download control's full stored bundle ID and hash binding.
3. Clicks the existing deferred download without resetting a test run or modifying standing data.
4. Checks the served commit again. The entire downloaded ZIP must match the expected SHA-256 and exact length before it creates the local ZIP; an existing local file is never overwritten.
5. Emits metadata-only JSON: bundle ID, SHA-256, size and served commit. Client files remain on the requesting agent's filesystem and never enter CI artifacts.

An empty shelf, absent matching archive or restarting service causes failure without a partially accepted output. An absent file is not an empty or approved report. Archive upload, importer replay and independently expected-result verification are three different deliverables.

## Separate deployment-retention evidence

The manually dispatched [Shared Archive Redeploy Read-only](https://github.com/evanroden/msapo-generator/actions/workflows/shared-archive-redeploy-readonly.yml) workflow can retrieve a *known existing* archive on a before served build and again on a different after served build. The exact receipt comparison must reject wrong IDs, unequal hashes/sizes, unchanged served revisions and outdated timestamps. Use a normal authorized implementation deployment; do not create infrastructure churn or an outage just for this check. Observe the owner's restrictions on publishing original-source identifiers and receipt contents.

A single external download does not prove two-deployment retention. The six-source reference ZIP does not select AUTH01–03 source/target/partial-state or certify importer, actual output or Word/owner acceptance.

## Immutable archive and rollback boundaries

The source/evidence ZIPs are not stored in public Git, Docker images or short-lived Actions artifact storage. They reside on the Render persistent disk only after a successful explicit upload through the existing browser controls. A code revert should leave verified disk originals untouched. Retain the independent owner Library copy; a disk snapshot or deletion of this conversation does not establish external availability.

Start future work with the exact main and served revisions, actual stored digest/size, latest verified retrieval/retention receipts and the [compact current ledger](PHASE1_PHASE2_REMAINING_2026-10-14.md). The [historical execution record](PHASE1_PHASE2_EXECUTION_2026-10-13.md) preserves earlier failures and coverage, not current pending status.
