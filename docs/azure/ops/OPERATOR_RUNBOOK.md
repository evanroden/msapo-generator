# MSAPO Azure — operator quick reference (A11)

**Proposed only. No production on-call assignments, backup commitments or alert routes are approved.** Detailed policy: OPERATIONS_HANDOFF.md. Source and image MUST match P20's accepted release SHA and immutable digest. Never put quotes, receipts, prompts, customer contacts, signed URLs, file paths or free-form exception text in tickets/logs.

## Triage (first five decisions)

1. **Identify build:** capture environment, observed UTC time, full APP_GIT_COMMIT, deployed image digest, safe correlation ID, workflow class and error code. Do not copy request/response payload.
2. **Separate liveness from readiness:** Streamlit /_stcore/health is only process HTTP health. Check approved authenticated readiness to read/save/generate against the actual store and renderer. A responding app can be unsafe.
3. **Protect data:** if readiness, database, source-integrity or Smartsheet submission-store trust fails, BLOCK writes/generation/submissions; preserve current drafts/originals and the last-good output. Never create a new empty store.
4. **Determine blast radius:** Monthly, PO, Expense; one release digest or all; one store or all; one region or all; recent config/image/schema changes; backup recency.
5. **Assign role:** SRE/Platform for startup+capacity; DBA/storage for durability; app engineering for save/conversion; AI owner for 429; PO owner for external uncertainty; business owner for acceptable outage/data loss. Names, contacts, escalation and coverage are **TBD**.

## Response table

| Condition | Immediate safe action | Verification before close |
|---|---|---|
| Startup/deploy/5xx | Freeze promotion; compare exact digest, health, WebSockets, app settings, identity. Roll back only if old image and current schema are compatible. | authenticated smoke, safe readiness, save/reopen and PDF |
| Save/database/object failure | Fail closed; halt accepted-record changes; check service/permissions/locks/quota and backup manifest. Restore ONLY to empty isolated target first. | record counts, source SHA256, revisions, no duplicate submissions |
| LibreOffice timeout/invalid PDF | Preserve accepted DOCX/draft; inspect safe exit class, slot, RSS, temp space, pinned font/renderer versions. No stdout/stderr central logging. | PDF magic + page order/geometry/tables/fonts/grayscale |
| AI 429/unreachable | Preserve originals and draft; use approved bounded retry/manual review; never switch providers silently. | synthetic fake + approved isolated connectivity check |
| Smartsheet uncertain | **Do not resubmit**. Reconcile remote row and attachments with local submission lease/fingerprint in secured operator tools. | prove single row, no repeated attachment; owner signoff |
| Backup overdue/corrupt | Block any destructive action; confirm last good matched DB+file checkpoint and restore authority. | isolated restore and verified hashes/relations |
| CPU/RSS/temp pressure | Capture metric trend, conversion activity, scratch free%, restart/OOM data. No automatic scale-out of stateful SQLite. | stabilized p95/peak + no save/data loss |

## DR quick drill (synthetic isolated target only)

Freeze **all** source writers including slots and externally triggered submissions; record cross-store checkpoint and release image; verify archive SHA256, schema, counts and object versions; restore to empty nonprod with external egress disabled; run synthetic Monthly/PO/Expense save/reopen/export/duplicate prevention; record actual RPO and RTO; never promote recovered data until DBA, SRE and business owner approve. Existing live per-file SQLite backups do NOT establish a cross-store consistent point.

## Change and cost gates

No approved region/SKU, budget, backup retention, staffing/coverage or RPO/RTO was available. Proposed higher-availability targets: RTO <=4h, RPO <=1h ONLY if proved by actual cross-store recovery and signed; lower-cost option: next-business-day RTO / 24h RPO, also unapproved. Model all App Service, ACR, managed database, objects/Azure Files, monitoring, network, secrets, backup and separate test costs. Current App Service guidance says **do not use SQLite on custom Azure Storage mounts**, and App Service backups **exclude mounted storage**. Review managed PostgreSQL/Blob adapter draft #851, not production-ready.

**Evidence:** 15 disabled alert families; 106 current offline JavaScript policy checks PASS. Azure alerts, App Insights ingestion, Azure resource deployment, capacity tests, and restore drills NOT TESTED. Do not enable action groups or paid resources while this handoff is in preparation.
