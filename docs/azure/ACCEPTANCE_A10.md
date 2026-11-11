# A10 — Azure acceptance suite and release blockers (11 November 2026)

**Status: PREPARATION ONLY / NO AZURE ACCEPTANCE OR TRAFFIC SWITCH.** The source is msapo-generator main at SHA 57c5cd87e3e441dfea3cddbc666248f8e469d986, as audited in A01 draft PR #849. This is the baseline/reference, not the final P20-approved release SHA. The target App Service, production-safe stage, identities, managed stores and final promoted image digest have not been established.

## Already established

- Existing Render [synthetic isolated Monthly QA run 43032816730](https://github.com/evanroden/msapo-generator/actions/runs/43032816730), attempt 2, was successful at SHA 57c5cd87e3e441dfea3cddbc666248f8e469d986; artifact: monthly-isolated-live-evidence. This is not AUTH01, AUTH02 or AUTH03 acceptance.
- Existing Tests workflow runs all pytest with LibreOffice/fonts, verifies container APP_GIT_COMMIT, starts a healthy container, exports synthetic DOCX/PDF, and separately performs capped resource testing. It does not certify Azure.
- A10 added focused tests for document semantics, page order, geometry, font and artwork, grayscale, output metadata tolerance, absent artifacts, SHA/digest/fixture matching, and fail-closed target isolation. The independent local environment ran all 16 tests successfully. GitHub exact-head CI remains necessary.
- Native Microsoft Word layout, private originals, Entra negative cases, physical-device checks, live Azure storage, tenant access, and matched-digest Azure comparison are NOT RUN.

## Classification and method

For a migration-regression verdict, use the **same immutable source SHA, locked dependencies, image sha256 digest, actual renderer/fonts, fixture contents and identifier, user action sequence and feature flags** in an isolated container baseline and an authorized Azure staging deployment. Current Render output may supplement history but is not automatically the same image. Record the first failure (do not turn retries into a first-attempt pass).

- **Existing product defect**: independently reproducible with identical input/actions in the baseline container and on Azure.
- **Migration regression**: baseline candidate passes while the Azure deployment of that same candidate/fixture fails, with a reproducible hosting/storage/auth/network/rendering difference.
- **Infrastructure/harness**: environment, browser, runner, credentials or test setup fails; no product verdict.
- **NOT RUN / BLOCKED**: required stage, fixture, device, account, permission, image identity or outputs are absent. Never mark this PASS.

## Focused executable commands

Run only on an isolated checkout of the exact selected commit, with no customer originals or keys in public CI:

    python -m pytest -q tests/test_azure_acceptance_parity.py tests/test_qa_azure_authenticated.py
    python -m compileall -q scripts/azure_acceptance_parity.py scripts/qa_azure_authenticated.py

Reuse the existing container job and scripts/qa_monthly_report_outputs.py for artifact production, and the existing qa_po_adaptive.py, qa_expense_adaptive.py, qa_monthly_report_resources.py, tests/test_smartsheet_store.py, tests/test_smartsheet_api.py, tests/test_monthly_report_persistence_processes.py and tests/test_monthly_report_full_synthetic_output.py on their permitted isolated local/test routes. Do not direct scripts with synthetic write/reset actions to production.

### Read-only authenticated staging smoke

Run on a private ENFRA runner with an **authorized Entra** Playwright storage-state file, which must never be committed, logged or retained in public artifacts. A04/A05/A07 must independently prove the stage service principal cannot write to production data/Smartsheet. The probe checks for matching served About SHA and real Streamlit WebSocket before/after reload without an anonymous bypass.

A separate restricted isolation.json (not a substitute for verified Azure grants) must provide the following keys: environment="staging"; smartsheet_api_mode="disabled"; production_write_access=false; database_target and database_production different and present; files_target and files_production different and present; smartsheet_target and smartsheet_production different and present. The code refuses missing or matching resources, production mode, non-HTTPS and a host identical to the production origin.

    python -m scripts.qa_azure_authenticated \
      --origin "$APPROVED_STAGING_HTTPS_ORIGIN" \
      --production-origin "$PRODUCTION_HTTPS_ORIGIN" \
      --sha "$EXACT_RELEASE_SHA" \
      --storage-state "$RESTRICTED_AUTH_STATE_PATH" \
      --isolation-json "$RESTRICTED_ISOLATION_JSON" \
      --output "$PRIVATE_EVIDENCE_DIR/authenticated-staging.json"

This smoke also runs a signed-out browser context and a separate cookie-free HTTP Upgrade handshake to the Streamlit WebSocket to require an actual Entra challenge or explicit denial; a blank page alone is not a PASS. This smoke is **not** a complete security test. With different authorized, wrong-tenant, unassigned and restricted-role contexts, separately verify signed-out routes; report/original/preview/download access; direct URL and WebSocket access; login/logout/session expiration; concurrent users and tabs; contract/site isolation. Capture observed outcomes rather than inferring them from the app shell.

### Paired DOCX/PDF semantic, geometry and visual parity

Use identically named private local files for the same fixture, e.g. container/monthly.docx + monthly.pdf and azure/monthly.docx + monthly.pdf. Every environment has a metadata.json with exact measured source_sha, image_digest (sha256:64 hex), fixture_id, dataset_classification="synthetic", and environment="container" or "azure-staging". Independently verify those values against actual Git SHA, the pushed image digest and the App Service image reference; a matching self-reported JSON value is not remote attestation.

    python -m scripts.azure_acceptance_parity \
      --baseline "$PRIVATE_EVIDENCE_DIR/container" \
      --azure "$PRIVATE_EVIDENCE_DIR/azure" \
      --baseline-identity "$PRIVATE_EVIDENCE_DIR/container/metadata.json" \
      --azure-identity "$PRIVATE_EVIDENCE_DIR/azure/metadata.json" \
      --sha "$EXACT_RELEASE_SHA" \
      --require monthly.docx --require monthly.pdf \
      --output "$PRIVATE_EVIDENCE_DIR/paired-parity.json"

Use --require separately for each expected DOCX/PDF format actually supported by Monthly/PO/Expense. Code 0=PASS, 2=FAIL, 3=NOT RUN (missing paired files), 4=BLOCKED (identity/evidence). Word comparison covers body/header/footer words, tables, direct/effective font styles, OOXML geometry, ordered media references, embedded media, embedded attachments and grayscale. PDF covers page order/count, text, spans/fonts/captions, page and text coordinates, image counts, embedded attachment bytes, chromatic fractions and bounded per-page rendered-pixel differences. Timestamp/OOXML ZIP and PDF metadata differences do not alone fail parity. Results are hashed/summary-only; actual text, screenshots and documents stay in approved private evidence storage.

For authentic acceptance, use **restricted authorized originals only**, and keep them outside public GitHub/CI: AUTH01 prior month same sites; AUTH02 different site under same contract; AUTH03 incomplete correct target month. Verify first gesture, import scope, prepared-by, edit, save/reopen, original preservation, every DOCX/PDF page, object/page order, tables, captions, artwork and grayscale. LibreOffice-generated PDF is not native Microsoft Word acceptance. Native Word and physical iOS/Safari remain NOT RUN until physically observed.

## A01 M01–M16 blocker matrix

| A01 gate | Acceptance requirement | Observed verdict 2026-11-11 |
|---|---|---|
| M01 | Integrated exact P20 release SHA and all repair PR ownership | BLOCKED: #844 draft is stale against newer #828 head; final SHA TBD |
| M02–M03 | Enterprise repo, policy, approved Azure resources and distinct environments | BLOCKED: no approved target identifiers verified |
| M04 | Exact SHA + same image digest, runtime, port 8501, health and WSS | NOT RUN on Azure |
| M05 | Tenant/assignment/role and direct URL/download/WS denial, expiration | NOT RUN |
| M06 | Corporate TLS/DNS/proxy/egress and outbound provider fakes | NOT RUN |
| M07 | Durable database/files, locks, chmod, restart and worker overlap | NOT RUN on Azure |
| M08 | Lossless export/import/verify/restore, corrupt/partial data, idempotence | NOT RUN |
| M09 | Monthly first-action, edit/reopen, DOCX/PDF and AUTH01/02/03 | Synthetic Render evidence only; AUTH NOT RUN |
| M10 | PO quote original bytes, corrections, downloads, fake Smartsheet retry | NOT RUN on Azure |
| M11 | Expense receipt corrections, PDF/Excel/email attachment handoff | NOT RUN on Azure |
| M12 | Financial suppression in every report and permitted AR decisions | NOT RUN on Azure |
| M13 | Two user/two session conflict resolution, history and site isolation | NOT RUN on Azure |
| M14 | Upload proxy/512MiB, large report, conversion resource budgets, physical Safari | NOT RUN on Azure; physical device NOT RUN |
| M15 | CI exact digest promotion, OIDC, stage isolation, logging and rollback image | NOT RUN |
| M16 | Signed cutover, writer freeze and restoration/rollback | FUTURE ONLY; not authorized |

### Required behavior journeys and before/after receipts

1. **Monthly**: initial entry; prepared-by on first activation; permitted original source intake; review warning; edit native row; save/reopen; history; Word/PDF content, sections, page order, geometry, fonts/captions/tables, photos, grayscale and exact SHA.
2. **PO**: initial entry; quote upload and immutable original hash; uncertainty correction; save/reopen; download; fake interrupted/duplicated Smartsheet submits using stable key; direct live API disabled; no external row.
3. **Expense**: initial entry; receipt upload/preview/correction; save/reopen; correct account/director routing; PDF/Excel and native .eml attachment handoff; no server-side send.
4. **Security/concurrency**: independent assigned/unassigned/wrong-tenant/read-only contexts; forbidden originals/previews/downloads; two users and two tabs performing conflicting writes and explicit merge/review; report/site/contract boundaries.
5. **Operations**: upper upload limit measured through proxy and app; multi-page image-heavy output; cold/warm CPU/RSS; long conversion, cancellation, DB outage/file-store failures, restart during save and renderer failure; recovery with no accepted state loss.
6. **Identity and release**: actual App Service-served SHA, image digest confirmed from ACR and deployed config, correct origin, authenticated WSS and reconnection, trusted deployment evidence.

Each private before/after row must include date/time UTC, exact SHA, immutable digest, environment, allowed data classification, fixture hash, first action/result, persisted correction, downloaded artifact hashes, compare report, reproduction, observed failure classification and rollback/recovery evidence. Publish only sanitized boolean/hash/count summaries. Synthetic evidence is not authentic acceptance. A screenshot of the app shell or a successful process exit is insufficient.

**Decision: NO GO.** Azure staging, its storage/identity contracts and the approved immutable candidate are not present in A01 evidence. Do not enable a new Smartsheet provider, alter production access controls, migrate real customer data, merge concurrent P20 repair paths without ownership review, or change production traffic. Product bugs belong in separate P20 repair PRs; Azure-only gaps in coordinated A04–A10 PRs, with failing-before/passing-after evidence.


## 11 November 2026 independent local evidence update

On an independent Python 3.13 environment, 16 synthetic focused unit tests passed (tests/test_azure_acceptance_parity.py + tests/test_qa_azure_authenticated.py). This is a harness self-test, not a project-wide exact-PR CI result.

A locally constructed 30-page/4.8 MB synthetic DOCX (six noisy-image examples, repeated tables and captions) converted twice with installed LibreOffice. Each output had 30 PDF pages and approximately 5.5 MB. Conversion times were 2.17s and 1.94s; peak descendant process RSS recorded approximately 201 MiB. The two PDF binaries differed, while all semantic, geometry, font, caption, attachment, grayscale and visual checks passed (maximum per-page mean pixel error 0.0). The fixture was **not generated by MSAPO**, and neither pass ran on Azure. Results do not establish App Service capacity, performance SLO or authentic-source Word fidelity.

The self-test evidence bundle also contains intentional page-geometry FAIL and missing-artifact NOT RUN cases, plus a difference render and JUnit outcome. All SHA/digest identifiers in local parity examples are simulated and must never be interpreted as a served image or customer acceptance.
