# ENFRA MSAPO operator handoff (draft, acceptance pending)

**Status:** DOCUMENTATION PREP ONLY; A11 #856's alert templates are disabled and no App Service backup/restore has been executed; no ENFRA operational acceptance or ownership assignment claimed. **Version:** 2026-11-11. Business system: Monthly/PO/Expense MSAPO. Source: https://github.com/evanroden/msapo-generator. Source-of-truth remains Render until a future separately authorized cutover; not automatically changed by repository transfer or DNS. See `CUTOVER_RUNBOOK.md`, `CUTOVER_ACCEPTANCE_CHECKLIST.md`, `ROLLBACK_REHEARSAL_RESULTS.md`, A01 PR #849, A10 draft #855, A11 draft #856 and #270.

## Handoff register (to complete in restricted ENFRA record)

| Field | Required approved entry / operational proof |
|---|---|
| Business/service owner and deputy | Named person, working hours, incident contact, data approval authority: **TBD** |
| Technical App Service owner and deputy | Named person, service/slot, Azure resource and role entitlement: **TBD** |
| DBA/data steward + backup owner | Named person, store names, retention and legal hold, on-call route: **TBD** |
| Enterprise GitHub/CI owner | Named person, authoritative host/org/repo and protected deploy environment: **TBD** |
| Security/IAM and network owner | Named person, assigned Entra app/group policy, ingress/VNet/DNS and egress: **TBD** |
| Integration (Smartsheet, AI, expense) owner | Named person, provider contracts, safe test destination, claim reconciliation: **TBD** |
| Operations paging and escalations | Schedule, alert destination, primary/secondary, Sev1/Sev2 escalation: **TBD** |
| Exact released artifacts | Approved commit `S`, image digest `D`, renderer/fonts/SBOM, schema id, rollback image `D-1`: **TBD** |
| App and monitoring | Restricted App Service, ACR, Key Vault, Log Analytics, App Insights and dashboards: **TBD** |
| Persistent data / restore | Approved transactional store, objects/files, `/test1` semantics if retained, backup scope/snapshot/version, restore method: **TBD** |
| Service contract | Approved p95 latency, expected peak uploads/users, resource ceilings, RTO, RPO, retention, incident response interval and budget: **TBD** |
| Secure evidence library | Approved ENFRA private location for synthetic and authorized authentic test evidence: **TBD** |

**Do not include** access tokens, signed SAS URLs, document text, employee contact details, private prompts, unknown client data or raw database connection strings in dashboard fields/CI logs/repo.

## Daily operating checks

1. Confirm deployed image digest and served About SHA match approved `S/D` and manifest. Process health **and** readiness to authenticate, save, reopen and generate are separate probes.
2. Confirm exactly one authoritative writer and one approved deployment pipeline. No second slot, worker, private preview URL, old Render app or unfinished workflow can write the same store.
3. Check auth/403 and site isolation, WebSocket reconnect/expired sessions, DB/storage availability and optimistic-concurrency rejects. Investigate spikes by correlation IDs without payloads.
4. Inspect conversion queue/failures and p95, LibreOffice/OpenXML renderer, CPU/RSS/OOM, disk/temp available, large-upload failures, third-party AI errors/429s, external Smartsheet claim uncertainty and Expense director failures.
5. Confirm last successful full backup, cross-store consistency point, object version coverage, restore test history, warning thresholds and approvals. Storage backup without database/files consistency is not a recovery point.
6. Confirm alert delivery health and owners, certificate/secret/key rotation schedule, image/dependency/font security patch queue and reproducible DOCX/PDF fidelity regression. Patch dependencies/renderer in nonproduction with approved fixture comparisons before promotion.

## Alert-to-action matrix (thresholds must be measured and signed, not presumed)

| Signal (safe identifiers only) | Receiver | Action |
|---|---|---|
| Startup/health failure, image SHA/digest mismatch, repeated restart | App Service on-call **TBD** | Hold rollout; verify same deployed digest, container logs without payloads; invoke app-only rollback only if schema compatible. |
| Readiness/save failure, DB unavailable, locks/transaction failures, unexpected writable instance | DBA + on-call **TBD** | Fence writes; verify store consistency and lease, assess report acknowledgements; do not swap source of truth by DNS. |
| Failed export/import/hash/backup/restore age | Data custodian **TBD** | Stop migration/cutover; reconcile full manifest and latest snapshot; do not use a partial backup. |
| Conversion timeout/failure, PDF renderer/font drift, large upload fails | App engineer + QA **TBD** | Isolate converter, inspect bounded CPU/RSS/disk metrics, retry only idempotent safe job; compare actual output to accepted baseline. |
| High memory pressure, OOM, temp/full disk, constrained storage | Azure platform **TBD** | Pause new heavy jobs; preserve submitted state; scale only after one-writer/concurrency design is accepted. |
| AI timeout/429/invalid result | AI + app engineer **TBD** | Fail closed, show truthful review/retry state, never silently switch model/provider or fabricate facts; record provider status and correlation ID. |
| Smartsheet uncertain response/retry or duplicate risk | Integration + business approver **TBD** | Stop external submission, reconcile remote by immutable key/claim before any retry; never infer no side effect. |
| Unauthorized user/site access, token/header bypass or secret leak | Security incident commander **TBD** | Fence access, preserve redacted audit trail, revoke impacted route and investigate under security process. |
| DNS/TLS redirect/WebSocket authorization fault | Network/IAM **TBD** | Restrict old and new writable routes; inspect certificate/origin/auth configuration. Avoid enabling Render on an unverified switch. |

Metrics/logs should contain only request/correlation ID, build SHA/image digest, event type, duration, bounded status category, redacted error code and resource utilization. Exclude document contents, employee contact information, full URLs with query strings, signed links, tokens, generated files and private prompt bodies.

## Runbooks

**Failed deployment:** prevent second write instance; capture `S/D`, schema version and deployment settings; test `/_stcore/health` plus authenticated save-readiness; if only application regression and schema backward-compatible, redeploy last accepted digest against same Azure data and verify. Otherwise hold writes and roll forward. Slots do not rewind DB.

**Data/storage loss:** freeze both possible hosts; inventory last consistency point and Azure committed changes, take immutable incident snapshot; select compatible target, restore all stores together and replay post-snapshot acknowledgements before enabling writes. Verify counts, hashes, provenance, report history, object relations and external claim state. No data-loss acceptance without business approval.

**Converter failure:** stop new conversion requests while preserving report state; inspect memory/disk/temp capacity and renderer/font identity; test synthetic DOCX/PDF and compare semantics/pages/graphics; fix deployment or scale with concurrency reviewed, then release. Do not mark a failed conversion as a successful report save.

**AI outage:** keep deterministic editors/save available where supported, mark extraction/analysis unavailable, preserve originals and structured review state, bounded retries, no provider change or automatic live fallback. Resume with user-reviewed corrections when provider/approved gateway recovers.

**External submission uncertain:** keep original uploaded quotes and receipts; preserve claim and request fingerprints, do not create second row, check remote state with approved sandbox/operations tools before any replay or retry. Recover only after stable outcome known.

**Access/identity incident:** deny unauthorized role/site direct links including originals/exports/WebSocket; invalidate and reauthenticate approved sessions as indicated by security. Do not bulk-attach anonymous historical records to first Entra login.

## Handover acceptance

- [ ] Named business and technical owners accept both daily and incident duties; on-call test alert received by primary and backup.
- [ ] Source/image provenance, architecture/IaC configuration, approved authentication and network diagrams signed and accessible.
- [ ] Data backup **and** restore drill with new writes/replay demonstrated inside agreed recovery limits.
- [ ] Authenticated Monthly/PO/Expense, originals, output fidelity, cross-site isolation and negative cases accepted.
- [ ] Costs and region/SKU, capacity and escalation thresholds measured and signed.
- [ ] Dependency/font/LibreOffice upgrade method regression-tested and supported.
- [ ] Change window, go/no-go, acceptance monitoring and separately approved Render retirement assigned.

**Current outcome:** NOT ACCEPTED. The operator handoff is a prepared checklist; it does not establish ownership, a deployed environment, recovery readiness or permission to retire Render.