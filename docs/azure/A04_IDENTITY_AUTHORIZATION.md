# A04 — MSAPO Entra identity and authorization (preparation only)

**Status: NOT APPROVED FOR DEPLOYMENT, NOT PRODUCTION READY.**
**Baseline:** main 57c5cd87e3e441dfea3cddbc666248f8e469d986; A01 draft PR #849. No root AGENTS.md on inspected main. This public repo contains no ENFRA tenant IDs, group IDs or private documents. No live Entra policy was inspected or changed.

## 1. Sign-in and trust boundary

- A03 owns the Linux App Service runtime, HTTPS ingress, redirect URI, separate environment credentials, Key Vault settings, corporate network restrictions and connectivity. Use one approved ENFRA tenant (not common or organizations) and a single-tenant Entra enterprise application. Distinct nonprod/prod service principals may be required by IAM.
- A04 provides infra/azure/a04-appservice-auth.bicep using Microsoft.Web/sites/config authsettingsV2. App Service Easy Auth requires sign-in, redirects to the Entra provider, has an explicit tenant issuer and app audience, HTTPS-only requests, and no excluded paths. Never exempt the Streamlit WebSocket, uploads, source previews, downloads, the old PO bookmark or health on a public route.
- The ENFRA Entra application owner must set enterprise app **Assignment required? Yes**, define approved application roles and assign only intended groups/users. App roles are additive to assignment and per-record scope checks. Entra Global Administrators may bypass assignment rules, so MSAPO's role requirement must still reject them absent explicit user role.
- App Service strips/replaces client-injected X-MS-CLIENT-PRINCIPAL headers and injects its verified claims. The application reads tid + oid as a stable principal key, plus app roles; it does not verify JWTs directly. Never trust X-MS-* from an independently exposed container, user-supplied HTTP headers, an arbitrary reverse proxy, UPN/email, entered requester, device cookie, Streamlit session state or URL as proof of authorization.
- Easy Auth authenticates ingress, but application authorization must check each resource. Current repo does not yet do that. app/azure_identity.py provides synthetic-testable primitives and a hard-coded _resource_boundaries_implemented() = False. Azure entry is **deliberately blocked** until A03/A05 integrate every data boundary in reviewed code. No environment flag can unlock it.
- st.context.headers on Streamlit represents the WebSocket handshake, not continuously updated claims. The current synthetic 600-second rerun-age gate does not guarantee immediate token revocation on an idle WebSocket. Expiry, logout and reconnect require actual A10 browser testing before access can be unlocked.

Microsoft references:
https://learn.microsoft.com/azure/app-service/configure-authentication-user-identities
https://learn.microsoft.com/en-us/azure/templates/microsoft.web/sites/config-authsettingsv2
https://learn.microsoft.com/azure/app-service/monitor-instances-health-check
https://learn.microsoft.com/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users

## 2. Proposed role matrix (ENFRA approval pending)

Every action requires MSAPO.AppAccess **plus** its action app role **plus** an exact server-resolved active contract/site grant. Names are proposals, not currently provisioned enterprise roles. Contract-wide operations require an explicit matching contract-wide grant; never infer one from a site grant.

| Action | Required app role | Data scope / notes |
|---|---|---|
| Open report and history | MSAPO.ReportReader or MSAPO.ReportEditor | Report's exact canonical contract/site |
| Edit/save/reopen report | MSAPO.ReportEditor | Exact contract/site write, revision check |
| Read original/source pages | MSAPO.ReportReader or MSAPO.ReportEditor | Derive scope from original's parent report |
| Preview thumbnails/PDF | MSAPO.ReportReader or MSAPO.ReportEditor | Ticket, owner and report scope |
| Word/PDF/download | MSAPO.ReportReader or MSAPO.ReportEditor | Authorize every byte-serving route |
| Publish default designs/contacts/templates | MSAPO.DefaultsPublisher | Explicit contract/site publication grant |
| Administer learned data | MSAPO.LearnedDataAdmin | Approved scoped data steward operations |
| External Smartsheet/API submission | MSAPO.ExternalSubmitter | Exact contract/site plus existing approval |
| PO operation | MSAPO.POOperator | Quote originals and outputs follow site grant |
| Expense operation | MSAPO.ExpenseOperator | Approved account/contract and director route |

Ordinary editor rights do not imply publish, learned-data-admin, or external submit. Do not grant every tenant member access, use the display name as an owner, or define blanket tenant-wide administrators. ENFRA IAM must determine app role assignments, group object IDs, guests, nested groups, temporary access, and revocation mechanisms.

## 3. Required A03/A05 storage/authorization integration

Current report libraries, directories, memory, Smartsheet claims, preview caches, source files and Word/PDF serving code do **not** yet enforce Azure record-level entitlements. The application cannot be opened safely by ENFRA users until the following reviewed changes exist:

1. Store server-owned principal (tid, oid), action, canonical contract ID, canonical site ID, active/expiry/revocation metadata and audit; map app roles to ENFRA group/user assignment via IAM. Grants are not supplied from a browser.
2. For all list/open/preview/download operations, resolve the canonical resource -> contract/site from persistent metadata and authorize before listing or returning bytes. Filter database listings *inside queries*, not merely in Streamlit UI. Missing/denied results are indistinguishable externally.
3. For saves and other writes, check entitlement and optimistic concurrency inside the transaction, including at commit. Fail closed when grants or canonical site information are missing/ambiguous.
4. For previews and temporary conversions bind job/ticket to tenant + object ID + report + revision + site. Random ticket keys are not authorization.
5. Protect all stored originals, source bundles, images, PDF pages, downloaded DOCX/PDF, contact/directory management, defaults, browser recovery, and Monthly/PO/Expense admin/test routes. Query switches such as monthly_qa or monthly_admin must not grant privileges.
6. Enforce submit permission before claiming a Smartsheet idempotency key or making external requests; preserve existing keys, mappings, attachment retry rules, and approval routing. Denied attempts produce zero external side effects.
7. Replace the hard-coded code lock only after a separate reviewed A05 integration and tests cover every path. No MSAPO_AUTHZ_DATA_BOUNDARY_READY-style environment bypass.

A05 must provide the approved transactional storage model and one writer consistency plan; A03 must provide authoritative tenant, ingress, DB, environment and secret setup. A01 calls the CI/CD identity workstream A08 (not A06); reconcile this task's A06 CI designation before assigning tests or deployment permissions.

## 4. Legacy anonymous data transition

- Preserve original report IDs, revision history, timestamps, sources, provenance, submissions and audit fields. Existing browser cookie epc_device_id and entered requester names are *preferences/attribution*, not ownership.
- Data steward builds a restricted crosswalk: legacy record ID -> verified contract/site -> eligible user/group/role grant, records approver and date, and quarantines ambiguous/orphaned records. No automatic adoption by the first person who signs in.
- Keep old author names as historical attribution, distinct from new verified actor ID. Provide reversible manual correction/rollback and record every changed entitlement.
- Browser-only unfinished Monthly work does not migrate between origins. Employees must Save shared version before cutover. Personal preferences are not automatically merged with Entra identities.
- Saved report sources/templates/directories and Smartsheet submission state retain scope and original identities during A09 migration. Never expose legacy reports to all authenticated users just to simplify claiming.

## 5. Evidence plan and test matrix

Synthetic isolated commands:
    python -m pytest -q tests/test_azure_identity.py tests/test_azure_auth_config_check.py

For a restricted nonproduction App Service configuration, after IAM approval:
    az webapp auth show -g APPROVED_RG -n APPROVED_APP -o json > restricted-auth.json
    python scripts/azure_auth_config_check.py restricted-auth.json

Do not commit or upload the raw auth JSON. This read-only check validates authsettingsV2 only; not service-principal Assignment required, groups, browser behavior, proxy reachability or store grants.

| Scenario | Synthetic coverage | Required A10 nonprod evidence |
|---|---|---|
| Signed out | Missing claims denied | HTML/download/WS return redirect or 401, no bytes |
| Wrong tenant / unassigned | Tenant and AppAccess check | Entra blocks sign-in, including admin exception assessment |
| Insufficient role | Exact per-action role and grant | UI and direct endpoint denied |
| Cross-contract/site | Canonical scope matching | Report/history/source/preview/download denied |
| Forged headers / bypass | Parser rejects missing/malformed identity | Client X-MS-* ignored, direct container ingress unreachable |
| Reconnect, 2 users, 2 tabs | Synthetic state switch/age | No state or cached bytes crossover; logout expires |
| Session expiry | 600s rerun guard | Active WS and in-flight/idle requests handled safely |
| Health | Bicep no exemptions | Health checker works, public request has no app data |
| Smartsheet/Expense | Role primitive | Denied operations have no side effects in dry run |

**Authenticated browser QA:** Use IAM-approved assigned synthetic users in an isolated staging environment. Separate reader, editor, publisher, learned admin, external submitter, unassigned and wrong-tenant identities. Interactive Entra login on an approved private runner may create short-lived browser state. Keep tokens/cookies and Playwright storage state out of public logs and artifacts, destroy after each job. GitHub Actions OIDC identity for Azure deployment does not authenticate a browser employee. Never disable production Easy Auth for CI. Require exact release SHA and image digest, redacted test outcome and QA signoff.

**Unresolved go/no-go:** tenant/client/service principal policy and app assignments, grant ownership and site scopes, guests, Global Admin behavior, sign-in session lifetime, approved private/public ingress, storage authorization hooks, health integration and authenticated WS browser evidence. A01 M05 stays OPEN. No live tenant settings, repository transfer, DNS, production or Render changes authorized.
