# A04 — ENFRA identity and authorization for Azure App Service

**Status:** PREPARATION / DRAFT as of 2026-11-11. No Azure provisioning, tenant-policy changes, assignment, data migration, deployment or production access approval. Follows A01 migration manifest in draft PR #849, not yet on main. Source main SHA: 57c5cd87e3e441dfea3cddbc666248f8e469d986. Root AGENTS.md was absent. P20 owns functional-release integration under issue #270. This is an App Service design, **not** the legacy Container Apps plan.

## ENFRA decisions required before enabling sign-in

ENFRA IAM must confirm the approved tenant GUID, separate development/staging/production application registrations, enterprise service principals, app role IDs/values, exact security-group assignments, whether guests and service principals are allowed, MFA/Conditional Access requirements, and an owner for changes/revocation. None of these values has been discovered. Never commit tenant identifiers, directory data, live role memberships or secrets to the public source repository.

Proposed configuration: a **single-tenant** Entra workforce application with the enterprise application's Assignment required set to **Yes** (service-principal appRoleAssignmentRequired = true), explicit user/group assignment, and the application roles below. ENFRA IAM must enact and verify these outside this PR. Tenant membership alone is insufficient; even a successfully signed-in user without the required application role is denied. Group claims are not interpreted as general privileges; group overage, nested membership and role claims need browser QA. Tenant Global Administrator is not an MSAPO data permission.

The un-applied app_service_auth.bicep fragment configures Microsoft.Web/sites/config/authsettingsV2 on an **existing App Service**: enabled Easy Auth; tenant-specific Microsoft Entra OpenID issuer; only Entra; HTTPS required; redirect unauthenticated clients to sign-in; empty excludedPaths array; cookie expiration derived from identity provider; an app-setting **name**, not a secret, for the Entra client secret. A03 supplies the actual Key Vault reference, resource name, approved networking and per-environment parameters. The official App Service Health Check integrates with platform authentication; no publicly exempt Streamlit health route is required.

In Azure configuration, require MSAPO_AUTH_MODE=app_service, ENFRA_ENTRA_TENANT_ID and ENFRA_ENTRA_CLIENT_ID. Azure itself supplies WEBSITE_SITE_NAME/WEBSITE_INSTANCE_ID. The application guard fails closed if any required setting or identity claim is absent. Render/local behavior does not change when these Azure markers are absent.

**Critical release block:** MSAPO_AUTHZ_DATA_BOUNDARY_READY=verified must **NOT** be set until A05 has implemented and audited server-side authorization for every report/library/source/preview/download/submission operation and A10 has accepted it. The new Azure UI entry guard refuses **all Azure UI** without this condition. It exists because the checked-in legacy application uses shared server storage and user-visible input fields, not Entra-scoped storage. A string setting is a deployment interlock, not an authorization control or release approval.

## Proposed least-privilege role matrix — not ENFRA policy yet

| Action | Entra application role value | Required separate scope/permission |
|---|---|---|
| Open app | MSAPO.AppAccess | Verified tenant/object identity and enterprise application assignment |
| List/open a report | MSAPO.ReportReader or MSAPO.ReportEditor | Exact contract and site read grant |
| Create/edit report, revisions or sources | MSAPO.ReportEditor | Exact contract/site write grant plus existing revision protections |
| Open originals, previews, DOCX/PDF downloads | MSAPO.ReportReader or MSAPO.ReportEditor | Derive report's authoritative contract/site, check a fresh read grant for every byte |
| Publish contract standing defaults | MSAPO.DefaultsPublisher | Explicit contract-wide grant, audited published revision |
| Administer learned/device data | MSAPO.LearnedDataAdmin | Explicit contract/namespace grant; no arbitrary cross-user claims |
| Use PO workflow | MSAPO.POOperator | Authorized contract/site |
| Use Expense workflow | MSAPO.ExpenseOperator | Authorized contract/site |
| Execute Smartsheet or other external submission | MSAPO.ExternalSubmitter | Authorized contract/integration, fail-closed claim/idempotency and approved destination |
| Manage tenant role assignments | None | ENFRA IAM control plane, never delegated to MSAPO UI |

The assigned MSAPO.AppAccess role does NOT imply any action role. An editor may satisfy a read-role check but still requires a separate exact-scope read grant. No role is an unrestricted superuser. Permissions are evaluated at the operation, not only the page. An unknown contract/site, no grant, deleted/inactive grant, wrong tenant, wrong identity, stale preview or guessed download ticket always yields denial without revealing whether the object exists.

The new app/azure_identity.py module is the **preparatory interface**: its Principal uses stable (tenant GUID, object GUID), decoded from App Service's injected X-MS-CLIENT-PRINCIPAL after trusted ingress; it checks AppAccess and explicit app-action roles; its authorize() function requires exact server-supplied ScopeGrant records. It is not a JWT-signature verifier. Browser cookies, requester/preparer labels, UPN/email/display names, query parameters and client-supplied grants cannot authorize data access. App Service must remain the only path to the Streamlit container; inspect direct container ports, alternate domains, staging slots, components, upload/download routes, Kudu/SCM, forwarding proxies and debug routes. X-MS-CLIENT-PRINCIPAL from the public network is **not** trustworthy.

The module is guarded from both run_web.py and the legacy pages/2_Smartsheet_PO.py bookmark. For a changed (tenant, object ID), Streamlit session state is cleared. A 10-minute WebSocket-handshake-age gate blocks the next rerun, but this alone is not real-time session revocation: an idle open socket can still display content previously sent, and replay protection must be enforced at each data/write operation. Test logout, expiry, existing WebSocket, reconnect, role removal, and two tabs in the actual App Service environment before go-live.

## Legacy identities and data transition

Preserve the old cookie-scoped requester/vendor/expense/employee preferences, shared Monthly report versions, revisions, sources, org charts, standing templates, contacts, previews and Smartsheet idempotency records as a **restricted migration batch**, never under the first Entra principal who signs in. Existing text attribution, such as prepared_by, is not proof of authorship. First sign-in creates an independent profile keyed by (tenant ID, object ID); it does not silently claim browser memory or existing files.

A05 inventories each record's original contract/site provenance and stable legacy ID, producing a reviewable legacy-to-new record crosswalk, owner decision, migration actor and approval. Records with missing or ambiguous scope are quarantined, not globally browsable. A data owner grants explicit access after review. Test duplicate filenames/content hashes, orphan sources, shared bytes, wrong-site links, revisions, and two distinct Entra users. Keep an immutable backup and rollback plan, including Smartsheet uncertain-submission state. Optional recovery of personal preferences requires a separate verified, audited opt-in; email/name matching or old cookie possession is insufficient.

## Synthetic evidence and required authenticated acceptance

Synthetic suite: python -m pytest -q tests/test_azure_identity.py. At preparation time: **18 tests passed locally**. Covers absent/malformed headers, wrong tenant/provider, missing AppAccess, duplicate claims, stable GUID identity despite email changes, different role/action and contract/site/identity, inactive grants, originals/previews/downloads, privileged actions, Azure configuration fail-closed, Azure UI blocked until verified storage boundary, changed Streamlit user and WebSocket-age denial. This proves decision logic only, **not** actual Azure enforcement, browser experience, production data isolation, WebSockets, group assignment or revocation.

A10 must run approved **nonproduction authenticated browser QA** using separate synthetic report/storage data: assigned reader and editor with differing site grants; role-deficient assigned user; unassigned same-tenant user; wrong-tenant user; two users and two tabs; login/logout/expiration/reconnection and revoked role while socket is open. Include root, deep-link, old PO bookmark, files, originals, temporary preview tickets, DOCX/PDF download, uploads and Streamlit /_stcore/stream, plus /_stcore/health. Record only redacted HTTP/WS status, served image digest and synthetic evidence. A signed-out WS must not upgrade; a 101 handshake must occur only for an authorized caller. Verify App Service internal health passes without exempting public requests; public health may expose generic liveness but no data. Check actual output bytes and site boundaries. Do not weaken production authentication or add a CI-only anonymous bypass. Interactive MFA-compliant test users/workload identities and network access require ENFRA IAM approval.

## Coordination and release blockers

- A01/P20: refresh main and #849's manifest/release dependency ledger before merge; do not merge this draft to production.
- A03: approved tenant, isolated App Services, Key Vault reference and networking; compose the unapplied Bicep fragment with App Service IaC (not Container Apps configuration).
- A05: authoritative transactional grants keyed by stable tenant/object identity plus explicit contract/site, checked before listing/reading/saving/source processing/render/export/preview/external submissions. No path-based implicit authorization. Provenance and legacy transition approval.
- A06: per A01 manifest A06 means **AI/external integration**, not CI; A08 means **CI/OIDC identities**. Reconcile the user request naming with coordinator before assigning ownership. External Smartsheet calls need independent authorization and idempotency controls.
- A10: exact-image authenticated browser acceptance, revoked privileges, sessions, storage, Word/PDF, uploads, downloads and error behavior. Keep production cutover blocked until all gates pass.

References: Microsoft [App Service Entra authentication](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-provider-aad), [require enterprise application assignment](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users), [authsettingsV2 template](https://learn.microsoft.com/en-us/azure/templates/microsoft.web/sites/config-authsettingsv2), [App Service health checks](https://learn.microsoft.com/en-us/azure/app-service/monitor-instances-health-check), [Easy Auth identity headers](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-user-identities).
