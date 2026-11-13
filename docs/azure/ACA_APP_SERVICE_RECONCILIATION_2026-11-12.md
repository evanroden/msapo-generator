# MSAPO architecture reconciliation: current container apps vs planned App Service

**Version:** 1.0 · **Evidence checkpoint:** 2026-11-12 (UTC) · **Status:** RECONCILIATION / PREPARATION ONLY · **Scope:** documentation, no infrastructure or data changes.

**Source repository:** [MSAPO](https://github.com/evanroden/msapo-generator) · **Ledger:** [#270](https://github.com/evanroden/msapo-generator/issues/270) · **Architecture decision of record:** [merged A01 #849](https://github.com/evanroden/msapo-generator/pull/849) and [migration manifest](MIGRATION_MANIFEST.md) · **Integration authority:** P20 under #270.

This file is a **sanitized public source-of-truth crosswalk**. It does not supersede A01, declare an Azure production deployment, or authorize any platform change. Subscription/tenant identifiers, actual resource names and hostnames, exact storage paths, app and identity IDs, network configuration, secrets and customer evidence belong only in an approved restricted ENFRA change record. The user-provided 12 November Azure inventory was reviewed but **could not be independently queried**: no authorized Azure control-plane/registry connector is available in this session. Do not treat that dated snapshot as current runtime proof.

## 1. Evidence and decision vocabulary

- **VERIFIED — repository:** independently fetched public main/ref/file or current PR metadata; proves what is checked in, not what an Azure container executes.
- **VERIFIED — Render control plane:** independently read from connected Render service/deploy metadata; proves deployment-record status, not browser About SHA or downloaded report acceptance.
- **PROVIDED — unverified:** supplied 2026-11-12 read-only Azure inventory; original control-plane response, permissions and exact time were not available for independent review.
- **INFERRED — test needed:** potential implication of facts, never approval or isolation proof.
- **UNKNOWN / BLOCKED:** required immutable, runtime, access, storage, security, usage or signoff evidence not collected. A tag, FQDN, running state or a resource's name does not prove code lineage, traffic, data isolation or approval.

**Decision reconciliation:** A01 records **Linux single-container Azure App Service** as the previously selected future migration target, and was **merged** on 2026-11-11. The older [ACA migration guide](../AZURE_MIGRATION.md) is an earlier hosting guide; its platform-specific commands do not constitute a reversal of A01. The 2026-11-12 inventory describes **already existing Azure Container Apps**, potentially alongside active Render. These are *as-is observations* versus *to-be product direction*, not inherently contradictory. The supplied inventory does **not** authorize an ACA-to-App-Service cutover or prove App Service resources exist. No new platform decision is necessary for documentation-only preparation; any proposal to make ACA the destination instead requires explicit owner revision of A01, storage/security design and downstream A02–A12 plans. The repository record labels App Service a product decision; an independently signed ENFRA change approval was not available.

## 2. As-is / to-be environment map

| Environment / role | Verified evidence | Provided, unverified detail | Unknown / must not assert |
| --- | --- | --- | --- |
| **Render — current connected live web service** | Render connected service is a web service tracking public GitHub main; auto-deploy is enabled. Its LIVE deployment record on 2026-11-12 15:17:45 UTC lists source SHA **64956cabc5aadbfd02bd76df676ecef9bd226ade**; fetched GitHub main matched that SHA. | No additional Azure role inferred. | No independent current browser About SHA, exact image digest, full end-user traffic, authentic report/PO/Expense output acceptance, or proof Azure is unused. |
| **ACA production-labeled app — existing as-is** | No ACA control-plane or served-code verification available. | Snapshot lists one production-named Container App, image tag suffix **v1**, in a shared managed environment/registry/storage family. | Exact active image digest and source SHA, revision list and traffic weights, ingress/auth, assigned identity permission scope, currently served users, actual mounts/read-write boundaries, immutable provenance, approval and current health. |
| **ACA development-labeled app — existing as-is** | No ACA control-plane, registry or filesystem verification available. | Snapshot lists a separate dev-named Container App, image tag suffix **dev-monthly-30**, reportedly same environment/registry/managed identity/storage family as production. | Whether tag resolves to today's image, source commit/patch history, exact digest, revision/traffic, whether files or DBs overlap production, effective write grants, separate access and test-data isolation. The dev image is NOT evidence of an Eric-authored Git commit. |
| **Azure App Service — planned to-be** | A01/merged migration manifest records the target design; current draft [#859](https://github.com/evanroden/msapo-generator/pull/859) prepares App Service IaC and checks without provision. | None establishes an actual deployed App Service. | Approved destination identifiers, actual plan/site, ingress/Entra roles, storage/DB decision, private networking, build digest, environment isolation, signed business/IT release gates and cutover. Treat as **not verified deployed**. |

The active Render deployment can be described as **LIVE by Render's deploy API**, not as exhaustive application acceptance or exclusive source of user traffic. Naming an ACA resource “production” does not establish it is serving the authoritative product. The Render/ACA role and data-authority relationship must be confirmed from authorized access logs, change records and approved operational ownership; do not guess.

## 3. Source → image → revision → serving → data lineage ledger

| Chain link | Render | ACA production | ACA development | Future App Service |
| --- | --- | --- | --- | --- |
| Git source SHA | **64956cabc5... verified deploy record**, also GitHub main at audit; runtime About not seen | **UNKNOWN** | **UNKNOWN** | Final approved release SHA **TBD** |
| Image reference/tag | Render Docker deployment from repository, per service metadata | **PROVIDED:** v1 | **PROVIDED:** dev-monthly-30 | **PROPOSED:** immutable digest pin |
| Actual immutable SHA256 image digest | **UNKNOWN** | **UNKNOWN** | **UNKNOWN** | **NOT BUILT/VERIFIED** |
| Image build source/attestation and Dockerfile or patch lineage | Render Git commit association observed; build digest not obtained | **UNKNOWN** | **UNKNOWN**, including external monthly-only patches | **BLOCKED** until approved exact-source build |
| Active container revision / slot and traffic assignment | Render API reports one latest LIVE deploy | **UNKNOWN** ACA revisions, mode and weights | **UNKNOWN** ACA revisions, mode and weights | App Service has **no ACA revisions**; future slots/restart overlap require separate design |
| Executing code observed in browser | **NOT independently checked** under About | **NOT CHECKED** | **NOT CHECKED** | **NOT DEPLOYED/NOT CHECKED** |
| Persistent data boundary and write authority | Service/data ownership not independently proven in this pass | **UNKNOWN** | **UNKNOWN** | **REQUIRES APPROVED isolated stores and one-writer qualification** |

Required evidence join: approved source ref/full SHA → reproducible build input and provenance → registry manifest digest (sha256) → actual revision template image by digest → effective revision traffic/replica status → served About SHA and authenticated WebSocket → synthetic downloaded DOCX/PDF and PO/Expense acceptance → storage and data-owner attestation. **A floating or version-named tag cannot replace this join.** Do not publish original image pull credentials, private registry URLs or raw revision exports.

## 4. Shared infrastructure is not verified data isolation

**PROVIDED:** The two ACA apps reportedly share a managed environment, registry, user-assigned managed identity, an Azure Files/NFS storage family, and related network/logging infrastructure. The snapshot gives a volume family name but does not prove the same/different share, mount target or subpath, nor effective POSIX/SMB permissions.

**INFERRED risk only:** If they mount the same backing share/path with write access, development writes, report imports, conversion scratch files, SQLite/learning records or Smartsheet submission claims could interfere with production. The same storage *account* or volume family may also contain **separate** shares/paths. Neither safety nor interference is established from names alone.

**Minimum private read-only comparison, separately for each app and current revision:**
1. ARM resource ID and snapshot timestamp (restricted); environment ID, managed identity principal attachment **presence/equality** and permissions/scope **comparison only**; obtain actual effective storage/registry/Key Vault ACLs without printing principals or secrets in public.
2. Image *tag and resolved digest*, active and inactive revisions, revision mode, replica scale/traffic weights, labels, and source build provenance/SHA when supported.
3. Template volume definitions, storage binding (account/share/export **equality by privately computed fingerprint**, no raw paths), container mount names and target/subpath **equality**, read-only flags and actual isolated write permissions, not merely declared volume names.
4. App-level ingress exposure, target port, auth enforcement/providers, allowed identities, TLS, IP/VNet/network policy, outbound paths, and whether an edge/proxy routes production users to it. Report public **PASS/FAIL/UNKNOWN** results only.
5. File/SQLite data ownership, live-writer count and cross-app lock/isolation test plan. **Do not execute** destructive or real-data write tests on shared resources during inventory; run approved synthetic isolation testing only in a separately authorized environment.

A shared managed identity is a **potential authorization coupling**, not proof of equal read/write ability. Different app names or revisions are not security boundaries if backing stores or grants overlap. Registry, Key Vault, networking and logging sharing also require explicit tenant/role/retention checks. Preserve originals, pinned masters, manual edits, report history and source/contract/site boundaries in every migration option.

## 5. ACA vs proposed App Service: mapping, not mechanical translation

| Concern | ACA as-is: what must be read | App Service to-be: recorded conditional plan | Consequence / gate |
| --- | --- | --- | --- |
| Runtime | Actual image digest, CPU/RAM, targetPort 8501, health probes, scale and revision mode **UNKNOWN** | Linux custom container; WEBSITES_PORT=8501; App Service Health Check/Always On; one worker initially | Retest Streamlit WebSockets, large uploads, LibreOffice/fonts and shutdown; ACA probes/traffic settings do not convert into slots. |
| Traffic & deploy | Actual revision mode, weights, ingress and deployed image **UNKNOWN** | Digest-pinned deployment, separate environment with signed promotion; slot strategy not approved | No inferred zero-downtime swap or revision traffic-splitting. Prevent two live writers during App Service roll, slot overlap or rollback. |
| Identity | Current ACA managed identity attachment and Entra app access **PROVIDED / NOT VERIFIED** | App Service Entra authentication/authorization design in draft [#854](https://github.com/evanroden/msapo-generator/pull/854) | Easy Auth is an **App Service** option; do not claim it currently protects ACA. Independently prove tenant, user/group/site grants and anonymous denial incl. WebSocket paths. |
| Durable storage | ACA NFS/Azure Files share/subpath/permissions and lock behavior **UNKNOWN** | App Service custom storage mount is separately configured; managed DB + Blob adapters proposed but unapproved in [#851](https://github.com/evanroden/msapo-generator/pull/851) | Never assume /home or an ACA volume automatically persists legacy /test1. SQLite on a network filesystem/overlapping writers needs explicit block-or-prove gate; App Service custom mount cannot be treated as transactional DB approval. |
| Sources and integrations | Actual secrets references and egress **UNKNOWN**; do not read values in public | Key Vault + managed identities, controlled AI/Smartsheet egress and reviewed providers; see [#853](https://github.com/evanroden/msapo-generator/pull/853) and merged [#858](https://github.com/evanroden/msapo-generator/pull/858) | No automatic provider activation or real customer submissions. Keep all three workflows and financial provenance policy. |
| Ops | Existing Azure logs/network/storage family **PROVIDED**; health, backup and alert bindings unknown | A11 operational templates in draft [#856](https://github.com/evanroden/msapo-generator/pull/856) | Alerts disabled and costs/RPO/RTO proposed only; require independently restored data and named operators before traffic move. |
| CI & validation | ACA-only existing [config checker](../../scripts/azure_config_check.py) and [historical guide](../AZURE_MIGRATION.md) | New App Service-specific checker/IaC proposed in #859 | ACA check must not be reported as App Service verification; draft IaC != deployed resource, build != CI != served acceptance. |

**Functional invariant:** main [app/web_ui.py](../../app/web_ui.py) retains **Purchase Order/Smartsheet**, **Expense Reimbursement**, and **Monthly Report** in the same application. The checked-in [Dockerfile](../../Dockerfile) supplies LibreOffice Writer/Calc, fonts, Streamlit port 8501 and optional source-commit stamp; [.streamlit/config.toml](../../.streamlit/config.toml) keeps XSRF/CORS protections. These are **verified code** facts, not claims that ACA dev's private monthly image is equivalent. Never carry over any monthly-only tab hiding or global price-permission switch. Owner financial policy is [#458 clarification](https://github.com/evanroden/msapo-generator/issues/458#issuecomment-6476808471): approved client-facing ENFRA/contract amounts need provenance; vendor-invoice totals are excluded from monthly client output.

## 6. Existing work and non-overlap

| Workstream / evidence | State at 2026-11-12 inspection | Relationship to this document |
| --- | --- | --- |
| [A01 #849](https://github.com/evanroden/msapo-generator/pull/849) | **Merged** | Authoritative pre-existing App Service architecture decision and M01–M16 evidence matrix. This document does **not** edit its manifest. |
| [A02 #850](https://github.com/evanroden/msapo-generator/pull/850) | Open draft | Enterprise GitHub governance and migration rules, not platform activation. |
| [A05/A09 #851](https://github.com/evanroden/msapo-generator/pull/851) / [A09 #852](https://github.com/evanroden/msapo-generator/pull/852) | Open drafts | Unactivated persistence adapters and synthetic migration rehearsal; no storage approval or real Azure isolation proof. |
| [A06 #853](https://github.com/evanroden/msapo-generator/pull/853) / [A04 #854](https://github.com/evanroden/msapo-generator/pull/854) | Open drafts | AI/provider and identity preparation; not effective Azure permissions. |
| [A10 #855](https://github.com/evanroden/msapo-generator/pull/855) / [A11 #856](https://github.com/evanroden/msapo-generator/pull/856) | Open drafts | Synthetic acceptance/operations templates; no actual app/host pass. |
| [A12 #857](https://github.com/evanroden/msapo-generator/pull/857) / integrations [#858](https://github.com/evanroden/msapo-generator/pull/858) | **Merged** | Documentation and inert external-integration readiness, not cutover/served authorization. |
| [A07 #859](https://github.com/evanroden/msapo-generator/pull/859) / portability [#868](https://github.com/evanroden/msapo-generator/pull/868) | Open drafts | Separate proposed IaC/checker and provider-neutral scaffolding; neither proves runtime ACA/App Service deployment. |

Status records are **point-in-time**, not authority to merge. Recheck exact PR heads, CI, review and combined-tree acceptance before any integration. P20 is sole release/integration owner. This one-file, documentation-only submission has no runtime, tests, workflow, secrets, infrastructure or release-file edits; keep it a draft for review.

## 7. Missing facts and handoffs for follow-on prompts 13–17

These are **evidence requests, not assigned owners or permission to access production data**. In each handoff, an authorized owner can store raw detail in a restricted ENFRA record and return only a redacted finding, timestamp, evidence-reference ID and PASS/FAIL/UNKNOWN. No Azure queries were executed for this document.

| Follow-on | Specific missing fact | Required bounded evidence | Blocking consequence |
| --- | --- | --- | --- |
| **13 — Image/source provenance** | Both ACA *currently active* digest(s), tag→digest resolution, exact build/source SHA and source patches; Render image digest and served About SHA | Read-only registry manifest/attestation, revision image snapshot, source build ID, timestamp, compare against current GitHub refs without extracting secrets | Cannot claim Eric's dev patch is in GitHub or identify equivalent release build. |
| **14 — Durable-data isolation** | Exact ACA dev/prod backing share and subpath equality, RW grants, effective identity permissions, DB/files and concurrent-writer authority | Private storage mount/ACL crosswalk, scoped access review, synthetic isolated lock/restore test plan; hash/equality only in public | **No dev writes or cutover** until data safety is established. |
| **15 — Access/network/revision** | ACA revision mode/weights, ingress/target port/TLS, Entra/tenant role enforcement, networks/egress, effective identities and current revision set | Read-only per-app resource exports with value redaction; authenticated synthetic access and health/WebSocket checks only when approved | No security or traffic-equivalence assertion, no implied App Service Easy Auth or ACA traffic split. |
| **16 — Traffic/data authority** | Which endpoint users actually use for each of Monthly/PO/Expense; which store has authoritative reports/history/submissions; Render–ACA synchronization and rollback owner | Approved traffic/usage/ops change records, no raw user identifiers; written one-writer/freeze ownership and rollback decision | Do not treat an app named production as authoritative; prevent divergent live writable stores. |
| **17 — App Service readiness/qualification** | Explicit destination endorsement if changed, actual approved resources, storage/DB design, owner roles/RPO/RTO, final pinned release SHA+digest and combined-tree/served acceptance | A01 decision register plus #859 checker/IaC review, A04/A05/A09/A10/A11/A12 gates, signed restricted approval and synthetic target results | **Provisioning/cutover not authorized**; retain App Service as recorded target unless revised expressly. |

Crosswalk to A01: M13 requires two-browser history/CAS acceptance, M14 physical/mobile and performance, M15 immutable CI/CD plus operations, M16 fenced release/rollback. See [A01 acceptance table](MIGRATION_MANIFEST.md) and [#270](https://github.com/evanroden/msapo-generator/issues/270); do not close acceptance issues on a documentary handoff.

## 8. Present conclusion and decision boundary

**Continue operating existing resources without changes, while preparing the recorded App Service target in source control.** This is a statement of the current documented plan, **not** an instruction to maintain any particular unknown Azure live traffic assignment. ACA prod/dev ownership, write access and serving roles remain unverified. Confirm the actual Azure control-plane state in a restricted environment **before** any future resource modification, staging setup, storage migration, AI/provider switch, user sign-in replacement or release.

**Decision only if new evidence or owner intent differs:** “Does ENFRA intend to retain Azure Container Apps as the *destination*, superseding the A01 Linux App Service decision, or are the existing ACA apps interim/as-is environments while the previously recorded App Service migration remains the target?” Changing to ACA requires an explicit dated A01 replacement and downstream storage/security/IaC/acceptance requalification; absence of a new decision means **no platform flip**, not approval to deploy App Service.

**Not done:** Azure control-plane/ACR/image inspections, production authorization tests, site output or source-file reads, new Azure resources, secrets, migration, cutover, Render changes, or any deployment. This file is safe to publish only because it contains abstract resource roles, public repo links, nonsecret image-tag suffixes and evidence status—not restricted infrastructure identifiers.
