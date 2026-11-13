# MSAPO migration manifest — ENFRA GitHub → Azure App Service

**Status:** PREPARATION / proposed architecture; no migration, infrastructure provisioning, repository transfer, production routing or data transfer authorized.
**Audit date:** 2026-11-11 (UTC).
**Source:** https://github.com/evanroden/msapo-generator
**Tracker:** https://github.com/evanroden/msapo-generator/issues/270
**Current Render site:** https://msapo-generator.onrender.com/
**Architecture decision:** Azure App Service (Linux custom container), **not Azure Container Apps**.
**Manifest ownership:** migration coordination / architecture. Functional-release coordination remains P20 under #270. ENFRA named approvers are NOT YET IDENTIFIED.
**Publication policy:** source repository is public. Never add enterprise hostnames if restricted, customer source files, tenant/subscription IDs, authentication tokens, directory data, contact lists, snapshots, connection strings, storage keys or approval secrets to this manifest. Record sensitive values in an approved restricted ENFRA change record.

## 1. Release source and evidence states

| Item | Recorded value | State / evidence |
|---|---|---|
| Audited main SHA | 57c5cd87e3e441dfea3cddbc666248f8e469d986 | Merged into main; read from exact main Git ref, 11 Nov 2026. Includes #826 contact identity/schema changes. |
| Production served SHA | 57c5cd87e3e441dfea3cddbc666248f8e469d986 | **Verified for isolated synthetic Monthly** at 17:08–17:11 UTC 11 Nov by GitHub Actions run 43032816730, attempt 2, successful; exact-served-SHA log assertion. Not verification of all customer workflows. https://github.com/evanroden/msapo-generator/actions/runs/43032816730 |
| Repair integration #844 | 2b81be6226bf59eabeb4b18ec79b719270644b12 | **Submitted as DRAFT**, not merged, not production deployed, not fully verified; integrates #827 and an earlier #828 head. https://github.com/evanroden/msapo-generator/pull/844 |
| #827 source head integrated by #844 | b822b83275270b77fde482854846cbfc77fde9e2 | MPO frame intake; source PR still open. https://github.com/evanroden/msapo-generator/pull/827 |
| #828 head originally integrated by #844 | 35e30db9f5371dc60f7336b7f376bee50d8eacd0 | Historical input to #844, **not current #828 head**. |
| #828 current head at audit | b052fff1704b07e1bb3094a549e286e18d95d450 | Open, updated after #844 was composed. Reconcile new commits and integration tree, rerun checks before claiming #844 current. https://github.com/evanroden/msapo-generator/pull/828 |
| #844 exact-head checks | Mixed: some successful, others queued/in progress at inspection around 17:57 UTC | Container, monthly-simplicity, cover-photo-resources, retained-state-upgrade successful; pytest and many other checks not complete. Do not promote success of subset to release PASS. |
| Root AGENTS.md | Absent in fully enumerated recursive main tree | Do not invent instructions. Recheck at the release-baseline SHA for new repository instructions. |
| docs/AZURE_MIGRATION.md | Existing, platform-specific to Azure Container Apps | **Historical reference only** for data/export/host checks; do not run Container Apps CLI, use revisions settings or port/probe semantics as an App Service plan. |
| Enterprise destination / Azure resource IDs | Not available from current connected repository account | Connected GitHub account lists only individual owner and no organization membership. No ENFRA Azure configuration or private Render dashboard environment is accessible here. Missing ≠ nonexistent. |

**Proposed frozen migration release baseline:** start from main 57c5cd87e3e441dfea3cddbc666248f8e469d986 as the **audited/served reference**, not as the final approved migration release. P20 must integrate accepted changes into a new main SHA, close all release-blocking CI/acceptance gates and establish a final immutable **release commit SHA plus content-addressed image digest**. The final SHA is **TBD**, not #844's draft head and not the Build/About metadata alone. Pin image by SHA256 digest, stamp APP_GIT_COMMIT with the exact source SHA, build PUBLIC_SITE_ORIGIN for the approved hostname, and record resolved dependency SHA/PR ledger.

### Outstanding release integration dependencies

- **Primary shared-feature integration:** #844 depends on #827/#828 and must reconcile #828 head movement. #839 also modifies app/monthly_report_docx.py and must be reviewed **after** #844's MPO/row-card output changes; inspect for double-emitted issue evidence.
- **Shared guided interface:** #834 (directory Undo), #838 (warning recovery) and #835 (pre-generation Word/PDF size estimates) all edit app/monthly_report_guided.py; reconcile adjacent editor/Prepared-by/review hunks, preserve new input and source bindings, run joined tests.
- **Other open repair/acceptance submissions at audit:** #829 (vendor totals), #830 (Smartsheet retries), #831 (PNG validation), #832 (capacity identity), #833 (preview latency evidence), #836 (device method), #837 (two-browser Training), #840 (AR output regression), #841 (original PO quote), #842 (history), #843 (PDF viewer bytes), #845 (Activity import), #846 (joined Scorecard/MBCx/Water), #847 (Smartsheet crash duplicate), #848 (Section 10 review rehydration). These are **submitted**; the presence of a PR is not a merged, tested or deployed outcome. Some are draft and some exact-head checks still running.
- **Strategic provider refactor:** #26 is a stacked draft dependent on #25; **not** implicitly authorized, merged or needed just because hosting changes. Revisit only for an explicitly approved AI/DB/storage contract that requires an adapter.
- **Acceptance still open:** authentic Monthly AUTH01/02/03, original-source output geometry, manual-save/undo conflicts, real multi-session behavior, financial gating, source retention, PO and Expense success/failure, mobile/physical Safari, performance, operational disaster recovery. Track in #270/P20; do not re-open completed changes or claim closure from synthetic-only tests.
- Before each integration, refresh exact PR head, comments and review threads, shared-file diff, CI checks and already-merged changes. P20 owns merging; migration-prep docs must not alter production/runtime/shared feature files.

## 2. Destination inventory and decision register

Legend: **CONFIRMED** = user or repository evidence; **PROPOSED** = recommendation, no infrastructure authorization; **MISSING** = unverified required input. Fields are intentionally blank until ENFRA supplies an approved, appropriately shareable source of truth.

| Area | Decision / field | Status | Authority / next evidence |
|---|---|---|---|
| Platform | Standard Azure App Service, Linux single custom container | CONFIRMED (product decision) | User migration scope. |
| Source repo | github.com/evanroden/msapo-generator, main ref and audited SHA above | CONFIRMED | GitHub |
| ENFRA GitHub **host** | TBD (github.com, enterprise GHE.com, or GHES private hostname) | MISSING | ENFRA GitHub administrator |
| GitHub **edition** | TBD (GitHub Enterprise Cloud vs Enterprise Server, exact version if Server) | MISSING | ENFRA GitHub administrator |
| GitHub **organization** | TBD | MISSING | ENFRA GitHub administrator |
| GitHub destination **repository** | TBD | MISSING | ENFRA repository owner |
| Repository destination mode | New ENFRA-private repository via reviewed history/secret scan, no source deletion until approved | PROPOSED | ENFRA security and repo owner |
| Azure tenant ID / verified domain | TBD | MISSING | ENFRA Entra administrator; restricted record |
| Subscription ID/name, management group/policy | TBD | MISSING | ENFRA Azure platform |
| Region and data residency | TBD | MISSING | ENFRA Azure platform and data owner |
| Resource groups, app service plan, app names, environments | TBD actual names | MISSING | ENFRA cloud/operations |
| Environment boundaries | Separate dev, test/staging, prod; distinct resources and stores, no customer data in non-prod by default | PROPOSED | ENFRA operations/data owner |
| Resource ownership/cost center | TBD owning department, cost center, budget and escalation/on-call roster | MISSING | ENFRA platform/business owner |
| Container registry | ENFRA-controlled private Azure Container Registry; immutable tags/digests | PROPOSED | ENFRA platform |
| Runtime identity | System-/user-assigned managed identity with narrowly scoped ACR pull and Key Vault read | PROPOSED | ENFRA IAM |
| User identity | Entra workforce single-tenant auth, deny unauthenticated traffic, authorize group/role membership (not merely tenant membership) | PROPOSED | ENFRA IAM/security |
| Approved database | **TBD; none discovered/approved** | MISSING, RELEASE BLOCKER | ENFRA data owner/DBA |
| Approved file storage | **TBD; none discovered/approved** | MISSING, RELEASE BLOCKER | ENFRA storage/security |
| AI destination/model/credential path | **TBD; none discovered/approved** | MISSING, RELEASE BLOCKER if AI used | ENFRA IT/AI governance |
| Smartsheet mode/approved destination | Existing form URL prefill; API direct mode disabled in checked-in render.yaml | CONFIRMED code baseline; dashboard overrides unverified | PO owner/ENFRA integration team |
| Networking / DNS / ingress | TBD: private endpoint + internal DNS vs controlled public endpoint with Entra/access restrictions | MISSING | ENFRA network/security |
| Operations | TBD app owner, security owner, backup/restore owner, SRE/on-call, data steward, AI owner | MISSING | ENFRA management |
| Production cutover date, rollback authority | TBD; no cutover authorized | MISSING | ENFRA change authority and business owner |

**GitHub destination tradeoff:** if ENFRA permits GitHub Enterprise Cloud, recommend private organization repository, CODEOWNERS, required checks and protected production deployment environments with OIDC. If ENFRA requires GHES, confirm host/version, runner networking, GitHub Actions availability, registry reachability, OIDC token issuer/trust support and enterprise-to-Azure connectivity **before** writing workflow assumptions. Do not guess enterprise URLs or issue IDs.

## 3. Recommended App Service architecture (not Container Apps)

    ENFRA enterprise GitHub
      protected PRs + exact-head CI + approval + secret/dependency scan
           ↓ OIDC federation when issuer supported
    ENFRA-owned private ACR ── immutable image digest
           ↓ managed-identity image pull
    Azure App Service: Linux, SINGLE container, one active app instance
      MS Entra authentication/authorization at ingress
      Streamlit :8501 + WebSocket /_stcore/stream
      /_stcore/health (health check; prove access semantics)
      Monthly | PO | Expense, LibreOffice/PyMuPDF/fonts retained
           ↓
      /test1 approved persistent FILE mount + approved transactional DB
      Key Vault references / managed identities; outbound approved AI + Smartsheet
      App Insights / Log Analytics with redaction, alerting and backup controls

**Container/runtime** (PROPOSED):
- Reuse the current Dockerfile (Ubuntu 24.04, pinned repository dependencies, LibreOffice Writer/Calc and fonts, Streamlit launch on 0.0.0.0:8501) with an exact SHA/digest. Do not replace Streamlit or the three workflows as a hosting prerequisite.
- Set App Service custom-container **WEBSITES_PORT=8501** (the legacy ACA targetPort is not this setting). Use Linux App Service Health Check path /_stcore/health, enable **Always On**, validate Streamlit WebSockets and authentication on /_stcore/stream. Configure HTTPS-only, TLS and approved DNS; optionally retain a custom company domain from day one to preserve browser session origin.
- Set one active instance initially and disable scale-out/autoscale. Verify actual App Service platform behavior, restart/update overlap and any staging slots: unlike ACA there are **no revisions settings** to copy. Deployment slots must not run two writers against the same SQLite store. No automatic swap while either instance writes.
- Current .streamlit/config.toml allows uploads up to 512 MiB. Verify browser, ENFRA ingress/proxy/WAF/App Service limits and memory with the largest permitted file and long conversion. Do not interpret a Streamlit maxUploadSize setting as proof that end-to-end request/proxy limits permit it. Propose an App Service Premium v3 class (starting benchmark candidate ~2 vCPU / 8 GiB), not a purchased SKU or demonstrated sizing. Measure native PDF, images, CPU/RSS, cold starts and concurrent authenticated users before sizing approval.
- Existing App Service storage **/home** behavior and WEBSITES_ENABLE_APP_SERVICE_STORAGE do **not** automatically create a persistent mount at **/test1**. Configure the approved App Service custom storage mount at /test1 explicitly and verify permissions and recovery; avoid using an ephemeral container folder. For Linux custom-container storage consult https://learn.microsoft.com/en-us/azure/app-service/configure-connect-to-azure-storage and https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container.
- Require build args APP_GIT_COMMIT (full release SHA) and PUBLIC_SITE_ORIGIN (approved full https origin); prohibit uncontrolled live rebuild of latest. Release evidence ties source SHA → image digest → App Service slot/deployment → About/served SHA → synthetic browser and actual downloaded Word/PDF.

**Persistence decision (BLOCKED pending approval/tests):** currently EPC_DATA_DIR=/test1 holds files and two SQLite databases, epc_memory.db and smartsheet_submissions.db. SQLite WAL cannot be assumed on network storage; app/sqlite_storage.py detects SMB/NFS and selects rollback journal. A **single App Service instance + Azure Files custom mount at /test1** is the smallest-change **conditional** candidate, *not approved for production* until Linux mount ownership, chmod 0600/0700, flock/lockf, SQLite transactions/reopens, restart overlap, snapshot/backup and restore all pass scripts/host_check.py in the actual target. Azure Files SMB POSIX permissions/locking behavior must be proved, not assumed; do not turn off safety checks, and do not force WAL. If any storage requirement fails, block cutover and choose an explicitly approved managed transactional database adapter (e.g., Azure Database for PostgreSQL for both stores) plus approved file/blob storage; this requires additional reviewed implementation and migration/restore tests. Blob storage alone does not replace relational transactions or POSIX file access. Disallow extra replicas until those adapters support concurrency.

**Authentication/network:** configure App Service Authentication (Easy Auth) with ENFRA Entra tenant allowlist, enforce unauthenticated request rejection and explicit application/user-group authorization. No globally exempt Streamlit routes or broad external providers. Confirm health check access without creating an anonymous data path. Proposed first choice: private ingress, corporate DNS/network, VNet integration, private endpoints for ACR/storage/Key Vault/AI where approved; alternative: guarded public HTTPS ingress with Entra, access restrictions/WAF and controlled egress only if security signs off. Ensure GitHub runners/test accounts can reach the site. Azure Linux WebSockets are supported; native test their behavior through the sign-in layer. See https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-provider-aad and https://learn.microsoft.com/en-us/azure/app-service/configure-common.

**Secrets and external providers:** inspected render.yaml identifies ANTHROPIC_API_KEY, EXPENSE_ACCOUNT_DIRECTORS_JSON, SMARTSHEET_FORM_URL, optional SMARTSHEET_API_TOKEN/SHEET_ID, ANTHROPIC_MODEL=claude-sonnet-4-6, PDF_BACKEND=libreoffice, plus SMARTSHEET_FORM_FIELD_MAP_JSON, SMARTSHEET_URL_PREFILL_ENABLED=true, SMARTSHEET_PREFILL_MAX_URL_LENGTH=7000, SMARTSHEET_API_MODE=disabled, SMARTSHEET_ALLOW_CUSTOM_API_BASE=false, EPC_DATA_DIR=/test1. This is **checked-in baseline only**; Render dashboard values override it and remain unverified. Use ENFRA-approved Key Vault references with managed identity, never copy values to public repo, CI logs, issue or pull-request bodies. No live Smartsheet submit, real email or AI invocation during migration preparation. Current AI uses Anthropic SDK for OCR, quote and receipt paths; ENFRA internal Copilot/Azure AI gateway compatibility is **not established**. Preserve current deterministic review/fail-closed rules; choose either an explicitly approved Anthropic egress or a scoped reviewed adapter after endpoint/auth/input support and retention/security decisions. Do not activate PR #26 by assumption.

**Telemetry/ownership:** structured request ID, runtime SHA/image digest, PII-redacted application metrics, App Insights/Log Analytics, resource and error alerts, secret rotation, vulnerability scanning, configuration and data backup, restore drill with stated RPO/RTO (TBD), business owner and 24/7 or business-hours on-call (TBD). Never log raw quotes, receipts, generated reports, full prompts, tokens or private directory contents by default.

## 4. ACA guide / checker incompatibility ledger

| Existing artifact/instruction | App Service disposition |
|---|---|
| docs/AZURE_MIGRATION.md title, az containerapp show/auth/exec | Historical only. Use App Service webapp/resource/config/auth/storage APIs after resource names approved. |
| scripts/azure_config_check.py | **ACA-schema-only**: must not be reported as App Service validation. Build separate read-only App Service checker and tests (A07), using actual Microsoft.Web/sites and authsettingsV2 shape, without showing secrets. |
| ACA single-revision mode, min/max replicas and revision restarts | **Not applicable**. Enforce one App Service worker instance and control slots/restarts/overlap, one writer, quiet-window restore. |
| ACA volume/NFS /test1 | **Not automatically portable**. App Service custom Azure Files mount requires separate configuration and target host_check; consider SMB ACL/locks. |
| ACA secrets/health probes/traffic splitting | Replace with App Service app settings + Key Vault, App Service Health Check/Always On, slots and auth/access restrictions. |
| Existing migrate_data.py export, verify, restore | Platform-neutral design: reuse only in **approved isolated dry run** after checks; archive SHA/SQLite consistency, target nonempty refusal and restart semantics. |
| Existing host_check.py | Platform-neutral probe with ACA example in docstring; use inside actual App Service container with read-only/offline checks first. |
| Render-only scripts and monthly-live-qa.yml | Continue Render until approved cutover. Post-migration retarget exact served URL/identity and remove or quarantine Render-only QA; never simply disable all acceptance without replacement. |

## 5. A02–A12 proposed task ownership and dependencies

**IMPORTANT:** No previously approved migration A02–A12 scope/owners are identifiable in the audited repo or prior migration context. These are **proposed mapping placeholders** for ENFRA approval, not claims of existing assignments or proof of completion. Do not confuse with unrelated ADP-A02–A12 adaptive-device acceptance IDs. **A01** migration architecture/coordination owns this manifest; **P20** continues release integration.

| ID | Proposed scope | Proposed accountable role (individual TBD) | Dependencies | Completion artifact / gate |
|---|---|---|---|---|
| A02 | Enterprise GitHub host/edition/org/repo, legal ownership, private import and history/secret scan | Enterprise GitHub admin + ENFRA repo owner | A01 destination decision | Signed source→target repo mapping; checks, branch policy, CODEOWNERS and runner availability |
| A03 | Tenant, subscription, region, cost center, resource naming/env isolation and IaC | Azure platform lead | A01, ENFRA policy | Approved resource inventory/IaC reviewed, no apply yet |
| A04 | Entra app registration, membership authorization, corporate ingress/egress and DNS | IAM + network/security lead | A02, A03 | Auth/authorization/network design, test identity, threat boundaries |
| A05 | Approved transactional database/file storage, permissions, backups and retention | DBA + storage/data steward | A03, A04 | Data model decision and actual mount/locking/restore acceptance criteria |
| A06 | Approved AI endpoint/provider credentials, data residency and Smartsheet/external egress | AI governance + integration owner | A03, A04, A05 for audit controls | Endpoint contract; text/image/PDF support, security signoff; provider adaptation decision |
| A07 | App Service Linux image settings, health, custom storage and read-only config checker | Application/platform engineer | A03–A06; final P20 baseline candidate | Reviewable App-Service-specific config/IaC and isolated checker tests |
| A08 | Enterprise CI/CD, OIDC/trust/runner reachability and digest provenance | GitHub DevSecOps lead | A02–A04, A07 | PR-only workflow, image attestation, gated manual promotion, no credentials in source |
| A09 | Data inventory, classified dry-run export/verify/restore and rollback playbook | Data custodian + operations | A05, A07, A08 | SHA256 manifest, isolated restore/locks, rehearsed RPO/RTO; no live export in preparation |
| A10 | Monthly/PO/Expense security, device, financial and actual DOCX/PDF acceptance | QA lead + business workflow owners | P20 approved repair SHA, A04–A09 | One exact-digest authenticated non-prod evidence bundle |
| A11 | Monitoring, incident ownership, disaster recovery, operational runbooks and acceptance | SRE/operations + business owner | A03–A10 | Signed runbook/alerts/backups/restore evidence |
| A12 | Approved change ticket, freeze, final migration release, cutover and rollback | Change authority + business owner + P20 | All A02–A11 plus final accepted P20 SHA | **Future**, separately authorized go/no-go and served-sha; forbidden in this preparation PR |

**Sequence:** P20 repair release → A02/A03 destination and policy decisions → A04/A05/A06 security/data/AI decisions → A07/A08 App Service/IaC/CI preparation → A09 isolated data rehearsal → A10 whole-workflow validation → A11 ops signoff → A12 separately authorized cutover. Some discovery can proceed in parallel; none authorizes a live write.

## 6. ONE acceptance/evidence matrix (authoritative for migration preparation)

State vocabulary: **CONFIRMED CODE/CONFIG**, **SYNTHETIC VERIFIED**, **OPEN / NOT TESTED**, **MISSING DECISION**, **FUTURE ONLY**. Only link exact-run SHA/digest and independent evidence; do not inherit tests from parent PRs after cherry-picks or rebases.

| Gate | What must be demonstrated | At-audit evidence/state | Owner / dependency |
|---|---|---|---|
| M01 Source release inventory | Exact main, active PRs/reviews, #844 current #828 head, assigned owners and complete issue→PR→commit ledger | Main SHA captured; #844 draft and stale vs #828; **OPEN** for final | P20 → A01 |
| M02 GitHub target | Verified host/edition/org/repo, access, SSO, protected main/environments, actions runner, secret scan | **MISSING DECISION** | A02 |
| M03 Azure control plane | Tenant/subscription/region, env isolation, RBAC, cost and IaC ownership | **MISSING DECISION** | A03 |
| M04 Container fidelity | Full-SHA image/digest, Ubuntu/LibreOffice/fonts, startup, 8501, health, WebSockets, Always On, 512 MiB upload path | Dockerfile verified **CODE**; App Service **NOT TESTED** | A07 |
| M05 Authentication | Tenant restriction plus approved user/group, deny anonymous, direct URL/WS/health behavior, no data leak | **MISSING DECISION / NOT TESTED** | A04 |
| M06 Network and external | Private/public decision, DNS/TLS, ACR/Key Vault/AI/Smartsheet egress, GitHub runner access | **MISSING DECISION / NOT TESTED** | A04/A06/A08 |
| M07 Durable data | Real mount /test1, owner modes, file locks, rollback journal, backup of both SQLite stores, crash/restart consistency | Scripts exist **CODE**; Azure mount **NOT TESTED** | A05/A07/A09 |
| M08 Data dry run | Sanitized source inventory, archive checksum, consistent DB backup, verify/restore to clean isolated target, history/source integrity | migrate_data.py exists **CODE**; no production export | A09 |
| M09 Monthly fidelity | AUTH01 same sites, AUTH02 different site same contract, AUTH03 half-finished month, native edit/reopen, prepared-by, all source page/order/geometry, actual Word and PDF | Render synthetic Monthly SHA **VERIFIED** run 43032816730; authentic and Azure **OPEN** | P20/A10 |
| M10 PO correctness | Quote original bytes/hash, no silent fallback, unknowns remain unanswered, Smartsheet stable fingerprint and no duplicate row, retry, disabled direct API | #830/#841/#847 submitted; **NOT DEPLOYED / OPEN** | P20/A10 |
| M11 Expense | Receipt correction, profile/director lookup, PDF/Excel/email handoff, real large receipt/converter failure/retry, no unauthorized message | Existing code; App Service **NOT TESTED** | A06/A10 |
| M12 Financial/safety | Approved AR audience; forbidden vendor invoice totals excluded in **all** outputs; original and stale approval failure | #829/#840/#848 pending; **OPEN** | P20/A10 |
| M13 Cross-session and history | Two browser contexts, CAS/revisions, recovery, no unblurred-input loss, correct document history | #837/#842 submitted; **OPEN** at integrated release | P20/A10 |
| M14 Performance and device | Cold/warm, concurrent users, large PDF/512 MiB route, actual WebSocket reconnect, narrow/physical Safari/accessibility, CPU/RSS budgets | #833/#836 submitted; actual App Service **NOT TESTED** | P20/A10 |
| M15 CI/CD and observability | Same exact image in staging/prod, OIDC if supported, signed approval, alerts/audit/backup restore, no secret/personal docs in CI | **OPEN** | A08/A11 |
| M16 Release and rollback | Cutover freeze, confirmed saved drafts, writes stopped on old host, no simultaneous writers, served final SHA and actual Word/PDF, recovery within signed RPO/RTO | **FUTURE ONLY**, no cutover authorization | A12 |

Use status progression for each acceptance row **Proposed → Submitted → Reviewed → Exact-head CI passed → Merged → Staging deployed → Staging verified → Production deployed → Production verified → Closed**. Recording a step never implies the next step. Every evidence row must carry test name, date, operator, exact commit, image digest, environment/host, dataset classification and artifact link. Individual P20 issue and PR evidence stays in #270 and source PRs; this is the **one** migration acceptance/evidence matrix.

## 7. Exact inputs ENFRA must provide to unblock implementation

1. **Enterprise GitHub:** authoritative host URL (or restricted reference), Cloud vs Server edition/version, organization/repository path, repository visibility/retention policy, runner type/reachability, SSO and administrator/business owner.
2. **Azure:** tenant, subscription, region/data residency, resource group(s), app service plan and app name per environment, registry and Key Vault ownership, permissible SKU/cost center/quotas, IaC standard and deployment approval role.
3. **Storage:** permitted Azure Files/Blob/managed DB services and SKUs, required data classification/retention, who owns /test1 and database migration, permitted keys vs managed identity, backup frequency, RPO/RTO, restore retention, access/lock requirements.
4. **Identity and network:** Entra app registration/group entitlement, allowed guest/service accounts, inbound (private endpoint versus gated public) and corporate DNS/TLS, VNet/subnet/private endpoints, outbound allowlist/proxy and build-runner access.
5. **AI and integrations:** explicitly approved Anthropic vs Azure OpenAI/internal gateway destination, model IDs, base URL/auth and image/PDF support, telemetry/retention rules, Smartsheet form and optional API policy, account director map custody. **Names/IDs only in approved restricted records.**
6. **Operations:** environment and business owners, security approver, release authority, on-call roster, synthetic QA identity, production freeze window, data freeze/writer cutover and rollback thresholds.
7. **Functional release:** P20-approved final main SHA, #844 dependency reconciliation, all issue gates and exact SHA CI/Word/PDF/native evidence; do not pick a moving draft head as release source.

## 8. Explicit no-change constraints and next approval gates

This draft may add **documentation only** to an isolated source-repository branch. It MUST NOT: move/duplicate enterprise source history, import customer data, rotate or disclose secrets, run live external test submissions, activate Smartsheet API mode, replace AI provider, provision Azure/ACR/paid resources, retarget DNS, disable Render live QA, change Render production or merge #844.

Next permitted preparation increments: (a) ENFRA-specific **read-only App Service** configuration checker with mocked schema tests, independently reviewable; (b) un-applied IaC design using placeholders; (c) nonproduction deployment workflow held behind protected environment/manual approval; (d) isolated synthetic mount and Word/PDF acceptance harness. Every file requires P20 collision review and a separate draft PR if it modifies runtime/shared paths.

**Authority:** The selected platform (App Service) is a user decision; all ENFRA identifiers, data/AI/storage selections and operational signoffs remain unverified. No migration go-live or production access authorization is implied.

### Platform references
- App Service custom Linux container and port: https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container
- App Service Azure Storage mounts: https://learn.microsoft.com/en-us/azure/app-service/configure-connect-to-azure-storage
- App Service Entra auth: https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-provider-aad
- App Service Always On/WebSockets: https://learn.microsoft.com/en-us/azure/app-service/configure-common
- GitHub Actions OIDC deployment: https://learn.microsoft.com/en-us/azure/app-service/deploy-github-actions
