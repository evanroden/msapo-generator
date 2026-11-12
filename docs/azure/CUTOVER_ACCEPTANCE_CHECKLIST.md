# MSAPO migration acceptance checklist — A01 M01–M16

**State:** PREP ONLY / **BLOCKED** (2026-11-11). Controlled evidence location: ENFRA restricted change record **TBD**. This checklist is a **completion gate**, not evidence by itself. Do not mark a box PASS based solely on a PR, a 200 response, a unit test, or a synthetic fixture. Date, release SHA, image digest, schema version, target environment, dataset class, operator and evidence URL are mandatory for every accepted row. Attach restricted artifacts outside public GitHub.

**Signing persons:** Change commander ______; P20 release ______; GitHub owner ______; Azure/platform ______; IAM/security ______; DBA/data custodian ______; AI/external owner ______; QA/business testers ______; SRE/operations ______; business/data owner ______. All unassigned at preparation time.

## Before any cutover scheduling

| Gate | Measurable PASS and required evidence | Owner | Current state |
|---|---|---|---|
| **M01** Release inventory | 100% active release PRs mapped to reviewed merge commits; reconciled #844/#828 drift; exact `S` and required CI results/approvals, 0 unwaived blockers. Attach ledger + CI and `S` hash. | P20 | ☐ OPEN |
| **M02** Enterprise repo | Real destination host/edition/org/repo approved; full collaboration-record preservation/crosswalk; rulesets/CODEOWNERS/runners/OIDC tested; one active production deploy authority. Attach target-read audit + pipeline dry-run. | A02/A08 | ☐ DRAFT #850; target missing |
| **M03** Azure control plane | Approved tenant, subscription, region, SKU/quotas, cost center, owner, env isolation and reviewed IaC; 0 unresolved policy denies. Restricted configuration export. | A03 | ☐ MISSING |
| **M04** Runtime | Identical `S`/`D` stage→prod; app on :8501, /_stcore/health, WebSockets, TLS, long PDF and max supported upload, renderer/font file hash, synthetic restart/overlap. Image provenance + full evidence. | A07 | ☐ DRAFT #859; no Azure execution |
| **M05** Auth/authz | 100% sampled signed-out/wrong tenant/unassigned/underprivileged/cross-site/original-download/WS negative probes denied; allowed cases work; no legacy anonymous takeover. Restricted identity tests. | A04/A10 | ☐ DRAFT #854; boundary interlock off |
| **M06** Network/integrations | Ingress+DNS+TLS and ACR/KV/data/AI/form egress tested from Azure and enterprise runner; restricted secret refs; dry-run Smartsheet mode, no new live API behavior. Network evidence. | A04/A06/A08 | ☐ DRAFT #853 (AI), #858 (external); approvals missing |
| **M07** Persistence | Durable tested DB/file store with transactional semantics and exclusive writer; owner permissions, lock/atomic ops or equivalent reviewed adapters; interrupted save/restart and backup verified. Storage test artifacts. | A05/A07/A09 | ☐ DRAFT #851; adapters incomplete |
| **M08** Migration rehearsal | 100% authoritative stores inventoried; consistent frozen snapshot+all deltas; counts/hashes/links/schema/relationships match; corrupted/partial archive rejected; idempotent isolated import and interrupted reimport pass. Synthetic + target drill logs. | A09 | ☐ DRAFT #852; real target pending |
| **M09** Monthly | AUTH01/AUTH02/AUTH03 authorized original cases; save/reopen, period identity, source links/pages, prepared by, Word/PDF comparison; user accepted every materially relevant change. Restricted test matrix. | P20/A10 | ☐ OPEN; A10 draft #855 synthetic only |
| **M10** PO | Exact original quote hashes; grounded fields; Smartsheet approved mode; uncertain/timeout retry maps to same claim with **0** duplicate external rows in approved sandbox. Business approval. | A06/A10 | ☐ OPEN |
| **M11** Expense | Account→director/recipient validation, receipt edit/reopen, final Excel/PDF/.eml handling, large input/retry and corporate browser; **0** unsolicited messages. Business approval. | A06/A10 | ☐ OPEN |
| **M12** Financial/safety | 100% prohibited vendor totals redacted from both output formats, proper AR audience, stale/unknown and source warning action recovered truthfully. Restricted comparison. | P20/A10 | ☐ OPEN |
| **M13** Multiple sessions | Two-user/two-tab stale-write conflicts, session expiry, correct history/identity, no cross-account leakage or silent overwrite. Browser traces. | A04/A10 | ☐ OPEN |
| **M14** Capacity/device | Physical corporate/mobile browser, wide/narrow/keyboard, 512 MiB intended upload path (or approved lower end-to-end cap), p95 generation/upload/first preview and CPU/RSS/disk at agreed targets. Measured sample & limits. | A07/A10 | ☐ OPEN |
| **M15** CI/ops | Protected promotion of same digest, no personal-repo Azure deploy, synthetic error/readiness/storage/AI/Smartsheet alert tests delivered to named owner; backup coverage/restore within **approved** RTO/RPO. | A08/A11 | ☐ DRAFT #856; alerts disabled/unverified |
| **M16** Full cutover/rollback | Stop both writer paths; demonstrate 0 concurrent writers; exact source→target hashes/counts; exclusive Azure write enable, postcutover save; reverse-migrate/replay rehearsal; signed change/rollback authority. | A09/A11/A12 | ☐ FUTURE ONLY |

### Required postcutover canary metrics

| Check | PASS threshold | Evidence owner |
|---|---|---|
| Serve source and image | `served_SHA == S` and deployment digest `== D`, 100% tests | A03/A08 |
| Active authoritative writers | **Exactly 1 Azure, 0 Render**; no deployable second slot against same store | A03/A09 |
| First new Monthly saved report | 1 approved synthetic record committed, reopened, version visible, output hash recorded | A10 |
| Identity isolation | 0 unauthorized records, originals, previews or exports; direct URLs denied | A04/A10 |
| Persisted imported data | 0 mismatched count/hash/schema relations; 100% required object links resolved | A09 |
| PO/Expense external | 0 real submissions in pre-cutover tests; 0 duplicate/uncertain unresolved attempts on production acceptance | A06 |
| Availability and performance | Within preapproved thresholds from measured staging baseline; **TBD, cannot assume PASS** | A11 |
| Backups and paging | 1 restore drill with actual data store, alerts delivered to named humans, no payload secrets | A09/A11 |

## Go/no-go form (enter only in restricted ENFRA record)

```
Change reference: [TBD]    UTC gate time: [TBD]     Commander: [TBD]
S (full commit SHA): [TBD]   D (ACR image SHA256): [TBD]
Schema/source/export format: [TBD]   Approved origin: [TBD in restricted record]
Read-only Render snapshot watermark / final delta: [TBD]
A01 and A02–A11 handoffs (version + links): [TBD]
M01–M16: [NO PASS CLAIMED in this file]
Business approval: [TBD]  Data owner: [TBD]  Security: [TBD]
Decision: NO-GO unless every mandatory item has evidence and named approval.
```

**Status rule:** checklist boxes start unchecked and remain unchecked until evidence is reviewed. Synthetic tests may support a subclaim but never replace real Azure / authentic-source acceptance. Unfinished change or missing owner = NO-GO; no automatic override when a window expires.