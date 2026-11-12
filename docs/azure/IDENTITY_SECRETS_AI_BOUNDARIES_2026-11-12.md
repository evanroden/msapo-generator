# A14 — Identity, secret references, and AI/OCR security boundaries (2026-11-12)

**Status: reviewable preparation only; not an Azure deployment or an authentication/provider approval.**  
**Source baseline:** `main` `64956cabc5aadbfd02bd76df676ecef9bd226ade` (2026-11-12 read-only refresh).  
**Coordination:** #270 and P20 release owner. Existing implementation owners retain #853 (A06 AI/OCR), #854 (A04 Entra/authorization), #868 (portability); this document changes none of their files.  
**Evidence classes:** *observed repository* = read-only source/PR inspection; *owner-supplied, unverified* = 2026-11-12 Azure inventory; *proposed* = future design; *unknown* = no authorized control-plane or tested service evidence.

## 1. Current platform vs future target: do not interchange controls

| Boundary | Current reported ACA prod/dev (*owner snapshot; unverified*) | Proposed App Service target (*manifest on main; not deployed*) |
|---|---|---|
| Hosting | Two Container Apps reportedly share an ACA managed environment and infrastructure dependencies. Running revision/image, ingress, auth and isolation are not verified. | Linux custom-container App Service described by `docs/azure/MIGRATION_MANIFEST.md`. This is a target decision, not a declaration that existing ACA was removed. |
| Browser identity | Inspect **Container Apps authentication** per app: enabled provider, permitted tenant/audience, unauthenticated action, ingress, direct endpoint bypass, session behavior and header provenance. No ACA authorization proof is currently available. | Draft #854 adds App Service `authsettingsV2` and a Streamlit entry gate. Its `WEBSITE_SITE_NAME`/mode-based gate is **not** an ACA security control. |
| Data authorization | Not demonstrated for report list/open/history/source/original/preview/download, PO, Expense, learned data or submissions. | #854 intentionally blocks Azure entry until reviewed storage-boundary integration. `RESOURCE_BOUNDARIES_INTEGRATED=False` is not a complete authorization implementation. |
| Workload identity | Owner snapshot reports managed identity for registry/Key Vault. Actual per-app identity assignments, ACR role, vault permissions and prod/dev separation **unknown**. | Managed identity and Key Vault references proposed; no evidence of an approved deployed configuration. |
| Secrets | Actual per-revision `secretRef` mappings, vault source/version, restart and permission behavior unverified; never read values for this review. | App Service Key Vault app-setting references require separate configuration and verification; do not mechanically substitute ACA revision instructions. |
| Storage | Shared volume/storage family **does not prove shared subpaths or isolation**; verify exact mounts, subpaths, permissions and backup behavior in a restricted record. | Approved transactional database/file-mount design remains gated by A03/A05 and separate acceptance. |

**Critical distinction:** ACA and App Service both offer managed identity and platform authentication, but they have different resource schemas, configuration and revision/deployment behavior. Even valid proxy-injected claims authenticate an actor; they do not authorize a contract/site document. Never trust arbitrary `X-MS-CLIENT-PRINCIPAL*`, `X-Forwarded-*`, cookie values, a requester name, or a browser-selected contract/site as authority. Trust platform claims only after confirming that ingress strips user-supplied identity headers and the application cannot be reached around the trusted proxy.

## 2. Entry points, actors and resource authorization

- **PO / Smartsheet:** `run_web.py` → `app/web_ui.py`; historical bookmark `pages/2_Smartsheet_PO.py`; optional quote OCR/structured AI and form prefill/API submission. The submitted form URL is browser-side, while approved REST submission is server-side and separately gated. Enforce `po.use`, and `external.submit` for actual API writes, with exact server-resolved contract/site plus the established business review/idempotency checks. A disabled API mode must not consume a token or create a row.
- **Expense:** same root entry → `app/expense_ui.py`, receipt analyzer, workbook/PDF and unsent email artifact. The employee-entered name, manager, email recipient and persisted preference are not verified actor identity. Enforce `expense.use`, account/contract entitlement, source/packet/download scope, and director routing independently of an entry login.
- **Monthly report:** same root entry → source imports, standing library, report/history, source-page and image caches, previews, generated DOCX/PDF, defaults and publication. Resolve report ID → canonical contract/site/revision from **server-side persistent metadata**; authorize before listing metadata or serving even one original/preview/download byte. Recheck writes inside their transactions. Do not infer entitlement from a URL, user-supplied selection, document filename, cached ticket or old device ID.

**Required record-level enforcement contract:** authenticated tenant/object principal + per-action application role + active, exact server-owned contract/site grant; contract-wide rights must be explicit. Missing/malformed principal, tenant mismatch, stale/expired session, revoked/ambiguous grant, unknown site, cross-contract ticket, or unrecognized action must deny with a generic error and no outgoing bytes or side effects. Streamlit WebSocket, old PO page, health, QA/admin flags, backups, cache access, export endpoints, multi-tab and session switching require independent verification. Preserve legacy report IDs/history/source provenance during entitlement mapping; quarantine uncertain ownership, never auto-assign to the first logged-in actor.

**Current implementation truth:** #854 tests the parsing and authorization *primitives* against invented identities, scopes and sessions; A03/A05 have **not** wired every resource call. No current code review, mock or authentication screen establishes end-to-end protection. ACA cannot be declared covered by an App Service-only `MSAPO_AUTH_MODE=app_service` path.

## 3. Nonsecret settings and names of sensitive references (not values)

| Configuration / reference *name* | Use and guard | Classification |
|---|---|---|
| `EPC_AI_PROVIDER` | Azure intended state: explicit `disabled` until independent environment-specific provider approval and a reviewed adapter. `anthropic` is legacy Render-compatible, **not** automatic ENFRA approval. Unknown choice denies. | Nonsecret, security-critical |
| `ANTHROPIC_API_KEY` | Existing Anthropic SDK credential; if specifically approved for dev, supply only through an approved **dev** secret reference, never source, CI or an issue. | Secret |
| `ANTHROPIC_MODEL` | Actual chosen model/deployment must have approved contract, pricing and retention; no model name grants approval. | Nonsecret/restricted configuration |
| `ANTHROPIC_BASE_URL` | Unreviewed override is refused by #853; no generic proxy/gateway fallback. | Restricted destination configuration |
| `SMARTSHEET_API_TOKEN` | Only for a separately approved server REST mode; existing form-prefill and disabled direct API must keep working without one. | Secret |
| `SMARTSHEET_API_MODE` | Preserve disabled/dry-run/live safeguards and no unauthorized POST. | Nonsecret, security-critical |
| `EXPENSE_ACCOUNT_DIRECTORS_JSON` | Restricted approval mapping; not user identity or authorization proof. | Restricted business/personal data |
| `ENFRA_ENTRA_CLIENT_ID`, `ENFRA_ENTRA_TENANT_ID`, Easy Auth client-secret **setting name** | App Service A04 proposed identity settings, never copy actual identifiers into this public repo. | Restricted identity/config metadata, secret setting reference |
| `MSAPO_AUTH_MODE`, `MSAPO_AUTHZ_DATA_BOUNDARY_READY` | App Service draft gate only. Environment variables cannot defeat #854's deliberate hard-coded incomplete-boundary interlock. | Nonsecret, security-critical |
| `EPC_DATA_DIR` | Sources, report history, caches and local state; actual cloud path and storage grants belong in restricted inventory. | Restricted infrastructure mapping |

The managed identity used to **pull the image from ACR** is a workload identity, not an end-user principal; Key Vault secret access is another workload permission. Neither supplies authorization to a report. A shared identity across prod/dev, if confirmed, increases the separation review needed. Record per-environment identities/permissions and least-privilege scope privately, without values or raw output in public CI.

## 4. Reported dev Anthropic HTTP 401: permitted diagnosis and blocked action

**Source of symptom:** Eric reported an Anthropic HTTP 401 in development. This has not been reproduced, and its cause is **unknown**. HTTP 401 is not proof that a specific key is missing, expired, blocked by ENFRA, or bound to the wrong model.

**Read-only, sanitized diagnostics when access is already authorized:**

1. Privately identify the *actual* dev ACA revision/image digest and deployment environment, checking whether it is isolated from production. Capture only a success/failure state, not identities, hostnames, raw env exports or filesystem paths.
2. Review dev's `EPC_AI_PROVIDER` classification as **disabled / approved provider / unrecognized / unset** and `ANTHROPIC_API_KEY` as **reference configured / not configured / reference unhealthy**. Check only reference **names**, source type (Key Vault vs app secret), and whether the revision's env variable points at the expected alias. Never execute commands that print a secret or fetch a vault value.
3. Inspect the platform's managed-identity presence and **permission result**, Key Vault reference health, container/revision restart status and allowlisted provider egress using redacted metadata; restrict findings to categories. Check that the SDK/provider mode and requested model are actually authorized, rather than probing unknown destinations.
4. Use an existing approved dev diagnostic only if that particular outbound call is authorized. Report **status code only** (e.g., `401`), sanitized timestamp and revision digest. Do not capture request headers, raw exception bodies, prompts, API key fragments, raw system logs or customer input. Do **not** run the online `host_check.py` model lookup for preparation; `python scripts/host_check.py --offline` is the safe path.

**Separately authorized operator procedure (not carried out by this document):**

1. Record ENFRA AI/data owner approval for the exact dev provider, account, model/deployment, payload types, endpoint, region, retention, egress, quota and test scope; establish separate dev vs prod credentials and an authorized custodian. If this contract is absent, keep `EPC_AI_PROVIDER=disabled` regardless of whether a secret exists.
2. The secret custodian creates/rotates the approved **development-only** credential directly in the designated private Key Vault workflow. Do not transmit it through chat, source, shell history, CI, logs or public issue text. Verify the *chosen dev application's* managed identity can resolve only the required secret; ACR pull and app-runtime Key Vault access may warrant separate identities.
3. In the ACA application's secret configuration, reference the approved Key Vault **secret URI** and assigned identity, then set the **new dev revision** environment variable `ANTHROPIC_API_KEY` from its application-level secret alias (`secretRef`), not a literal credential. Keep `EPC_AI_PROVIDER=disabled` unless that dev provider has specifically been approved; after approval, provider mode and model must be explicit. Verify revision mode, active traffic, prod/dev shared mounts and side effects **before** any revision activation.
4. An ACA application-secret change alone does not necessarily create a revision. Plan an **approved revision update/restart** to load referenced configuration. Unversioned Key Vault references may refresh/restart active revisions automatically, so the operator must assess rotation side effects rather than assume an inert value edit. All actual configuration writes/restarts require separate permission/approval.
5. After approved activation, inspect only redacted status: secret reference healthy, approved dev revision active, mode correct, no 401, and basic three-workflow functionality with **invented** fixtures. Treat a remaining 401 as unresolved. Keep prod untouched; do not assume a dev successful request authorizes production.

**App Service to-be differs:** app settings can use Key Vault references under the assigned managed identity, and authentication uses App Service `authsettingsV2`; ACA `secretRef`/revision commands are not applicable to App Service deployment slots or configuration. Neither hosting mechanism approves an AI destination by itself.

Official platform references:
- https://learn.microsoft.com/en-us/azure/container-apps/authentication
- https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets
- https://learn.microsoft.com/en-us/azure/container-apps/environment-variables
- https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull
- https://learn.microsoft.com/en-us/azure/container-apps/security

## 5. AI/OCR policy across all three workflows

The existing A06 draft #853 inventories and routes four direct Anthropic call sites through `app/ai_provider.py`: PO image/PDF OCR and quote classification, Expense receipt reading, Monthly fact/draft generation and image reading (via shared OCR). It blocks disabled/unrecognized providers, absent credentials and `ANTHROPIC_BASE_URL` override before SDK construction. Retries, validation, max payloads, source-anchored draft review and numeric/financial rules remain owned by existing callers. The manual/local Monthly and Expense paths remain usable; **PO pasted-text-to-structured-review currently has a documented model-unavailable gap** and must not be presented as fully equivalent manual operation.

**Residual fail-closed gap:** #853 defaults to `anthropic` when `EPC_AI_PROVIDER` is absent; this is intentional Render compatibility but **not a safe ENFRA Azure deployment default**. At a minimum A03/platform must enforce and independently test an explicit Azure `disabled` setting in each revision/site, with a drift check. An application-level Azure-aware default could be reviewed in A06, but must not silently disrupt an already-approved running production workflow. An arbitrary "Azure" flag or a Copilot/Entra login does not approve an endpoint. Never fall back across providers, send real data to an unknown gateway or make an unapproved paid probe.

**Missing provider contract:** actual endpoint/schema, model/deployment ID, text/image/PDF capabilities, key or Entra auth method, corporate DNS/egress/TLS/proxy, data-use/training policy, region/retention, deletion and telemetry rules remain **unknown**. The operator-mediated Monthly Copilot prompt is separate from an HTTP integration and must have its own data-use review.

## 6. Synthetic coverage, checks and remaining acceptance

| Control | Existing reviewed preparation | Missing or unverified |
|---|---|---|
| Disabled/unknown provider, absent key, custom endpoint, 401/403/400, 429/5xx and deadline | #853 `tests/test_ai_provider_contract.py` uses invented values/mocked calls for PO, Expense and Monthly; local-only OCR still works. | No approved-provider egress, real dev 401 cause, or full manual PO parity demonstrated. Azure **unset** provider test/rollout guard still required. |
| Wrong tenant, missing role, spoofed/malformed claims, cross-contract/site, unauthorized downloads | #854 `tests/test_azure_identity.py`, `tests/test_azure_identity_wiring.py` exercise synthetic principals and an intentional blocked entrypoint. | ACA ingress/header bypass, actual authoritative resource-to-grant lookups, direct downloads and exports, side-effect-free denial, app role/assignment, real revocation and entitlement lifecycle. |
| Expiry, reconnect, two users/tabs | #854 tests bounded synthetic rerun age and principal switch. | Real WebSocket idle-token expiry, logout, reconnect, inter-user cache/preview isolation and two-user browser sessions. |
| Key Vault, registry and secret reference permissions | Existing A04/A06 docs and proposed checks. | Read-only actual ACA prod/dev settings and identity grants, scoped vault ACLs, separate secrets/identities, reference rotation and redacted errors. |
| App Service auth and provider configuration | #854 App Service checker, proposed `authsettingsV2`; #853 provider selection and offline host checker. | All exact-head mandatory CI, approved A03/A05 wiring, A10 authenticated staging validation, App Service deployment/served acceptance. |

**Existing synthetic commands (not executed by this documentation work):**

```sh
python -m pytest -q tests/test_azure_identity.py tests/test_azure_identity_wiring.py tests/test_azure_auth_config_check.py
python -m pytest -q tests/test_ai_provider_contract.py tests/test_ocr_images.py tests/test_pdf_page_budget.py tests/test_receipt_analyzer.py tests/test_monthly_report_ai.py tests/test_analysis_schema.py tests/test_quote_analysis_guesses.py
python scripts/host_check.py --offline
```

No live provider call, key-value read, Azure role/secret edit, production switch, synthetic test execution, deployment or served acceptance occurred in A14. GitHub checks must be evaluated at the **final exact head**; queued or historical successful checks are not release evidence. This document is an independent review artifact, not a substitute for A04/A06 implementation/test and combined-tree qualification.

## 7. Required next owners and stop conditions

- **A04/A03/A05 identity + persistence owners:** verify ACA ingress/auth posture separately from App Service; complete server-owned contract/site grant enforcement on every saved and derived object/bytes route, including PO/Expense, and test revocation, cross-user caches and expiry. Do not bypass the interlock.
- **A06 AI/provider owner:** retain #853's existing scope and tests; add Azure unset-provider/drift and safe redacted 401 regression coverage when coordinated; preserve Render behavior; record approved nonprod and production provider contracts individually.
- **Azure platform/secret custodian:** inspect only reference names/health and app revision mapping in a restricted record; keep identity/secret/version/actual mount details private. No secret or revision mutation until separate authority.
- **P20 integration/release owner:** combine independently reviewed heads and run exact-head required checks, three-workflow synthetic/browser acceptance, source/output access-denial QA, full DOCX/PDF and isolated-prod/dev evidence. This draft does not authorize merge/cutover.

**Stop release if:** any protected byte route is reachable without authoritative per-record authorization; client-supplied identity headers are trusted; Azure has an unapproved active provider; secret values appear in a public surface; dev and prod isolation is unknown for a proposed live change; identity/revision/expiry behavior is not tested; or required review/CI/combined-tree gates are missing. Keep all acceptance issues open until their respective served criteria are demonstrated.
