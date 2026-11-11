# A11 alert and recovery acceptance matrix — all synthetic unless explicitly approved

Status: **PROPOSED**, no Azure Monitor/App Insights environment exists in this preparation evidence. These are required verification steps, not historical passes. Do not inject failures into a real user workflow, production DB, storage, email, Smartsheet or AI endpoint. Do not create action groups, enable rules or incur paid Azure resources during preparation.

## Required evidence record (per test)

Record UTC timestamp, operator role (not personal information), exact build SHA and digest, environment and classification, test ID, protected synthetic ID, expected safe code/threshold, observed sanitized event (allowlisted fields only), KQL evaluation result, evaluated alert outcome, action-group recipient acknowledgment, remediation performed, successful synthetic reread, and a restricted evidence link. Avoid raw HTTP bodies, screenshots of private documents, tokens, signed URLs, provider prompts, contact details and StackTrace/Stdout/Stderr.

| Test | Injected *isolated* synthetic condition | Expected rule / proposed recipient | Required safety/result | Not-yet-verified dependency |
|---|---|---|---|---|
| OPS-01 | Simulated start exception and unhealthy startup | startup_failure → SRE/platform | HealthCheckStatus/5xx rise, 15-minute alert, capture build SHA; old digest rollback compatibility checked | Target App Service and native metric |
| OPS-02 | Three allowlisted sanitized unhandled errors | application_errors → app engineer | Exactly threshold 3 events; no exception text/PII in traces | AppEvents instrumentation |
| OPS-03 | Forced DB write failure on test contract | failed_saves → app+DBA | Save rejected; draft retained; no success receipt; error code and correlation only | Managed DB adapter/auth |
| OPS-04 | Simulated DOCX generation failure | generation_failures → app+workflow owner | No stale/lost output, native retry bounded | Renderer availability |
| OPS-05 | Disable test DB connectivity | database_unavailable → DBA/storage | Readiness false, writes refused, return after recovery | Approved A05 store |
| OPS-06 | Deny test object-store access or corrupt copied synthetic object | storage_unavailable → storage/app | Source checksum failure blocks deliverable, no silent omission | A05 Blob/store integration |
| OPS-07 | Render store read healthy, but commits fail | readiness_blocked → platform/app | Shallow health remains 200 while **safe readiness false**; no writes or submissions | Protected readiness probe |
| OPS-08 | Fail/timeout/invalid PDF in isolated LibreOffice | conversion_failures → renderer owner | Original DOCX preserved; no subprocess stdout/stderr ingested | Emission redaction fix |
| OPS-09 | 5 slow synthetic conversions (longer than benchmark threshold) | conversion_p95_slow → renderer owner | p95 fires; normal sample does not; 30-minute aggregate shows exact sample count | Measured SKU baseline |
| OPS-10 | Artificial high memory against test counters | memory_pressure → platform | Resource metric alert or redacted event, no unauthorized scale-out | App Service SKU threshold |
| OPS-11 | Artificially low temporary free bytes | temp_pressure → platform/storage | Generation/preview safe refusal, authoritative data untouched | Temp volume/quota data |
| OPS-12 | Fake AI HTTP 429 and unavailable provider | ai_throttling → AI owner | Draft preserved, bounded retries, no unapproved fallback | Provider fake integration |
| OPS-13 | Fake uncertain Smartsheet response *after remote-accept-like state* | external_submission_uncertain → PO owner | No second row/attachment; manual reconciliation required | Reconciled transactional store |
| OPS-14 | Corrupt isolated backup manifest and simulate missed checkpoint | backup_failure → backup custodian | Backup marked invalid; isolated restore blocked; no live overwrite | A09 cross-store checkpoint |
| OPS-15 | Independently simulate **missing heartbeat** and native HealthCheck failure | telemetry_gap → SRE | Alert fires without expecting dead process to emit an event; query with synthetic table plus native metric | Independent scheduled evaluation + action group |

**Negative controls for every test:** same rule with 0 events / below threshold, stale events outside 15-minute window, otherwise healthy synthetic app, wrong event code, and safe text that does not identify users or contracts. Confirm non-firing controls and exact 5-minute evaluation cadence. Do not claim Bicep is working from the standalone offline simulator.

## Platform validation sequence

1. **OFFLINE (available now):** `python scripts/check_azure_ops_contract.py --dry-run` verifies disabled routes, allowlisted properties, expected rule mapping, positive/below-threshold/stale synthetic cases. Separately run `az bicep build --file ...` only in a nonproduction, approved build environment; Bicep build/validation itself does not deploy.
2. **ISOLATED AZURE (requires ENFRA approval and existing resources):** verify full safe AppEvents ingestion, metadata scrubbing for automatic tracing, operation correlation and exact release digest, test KQL on synthetic-only workspace. Azure Monitor metric names and units must be discovered from actual SKU; tune thresholds using measured baseline. Test both alert firings and no-alert cases.
3. **APPROVED ALERT ROUTING (not authorized in preparation):** bind action group to named/on-call role and backup, send synthetic trigger, record acknowledgment and escalation path. Prevent action-group configuration through PR untrusted code.
4. **BACKUP/RESTORE (isolated only):** A09 creates matched DB+objects archive with cross-store frozen watermark, then restores to nonempty-rejecting isolated target, reopens with same schema/digest and runs authentic content-preserving checks where legally authorized. No production restore.
5. **OPERATOR SIGNOFF:** SRE/Business/DBA/QA verify actual RPO and RTO, coverage and cost. Only then mark A11 gate accepted and update A01 matrix M15/M16 via coordinator.

## Heartbeat gap: independent KQL evaluation example

The app cannot notify an external service that it is dead. Once a healthy event heartbeat is implemented, run a **scheduled query** independently; example below returns a row **only** when no allowlisted system heartbeat is seen in 15 minutes. Use an absence alert that is triggered on row count greater than zero and tune noise suppression during approved maintenance. Never create an app-side `telemetry_heartbeat_missing` event and claim it proves an actual app outage.

```kusto
let count_15m = toscalar(
    AppEvents
    | where TimeGenerated > ago(15m) and Name == "msapo.op"
    | where tostring(Properties.code) == "telemetry_heartbeat"
    | summarize count());
print missing = count_15m == 0
| where missing
```

A query that finds no rows might mean a cold test environment, disabled ingestion, an unavailable workspace, broken instrumentation or a stopped process. Correlate with native App Service HealthCheckStatus and known deployment/maintenance windows. Do not route based on missing optional traffic without a dedicated heartbeat.

## Performance evidence to gather

- **Historical, not Azure evidence:** PR #653 reports one bounded Render-like synthetic Cover test at 512 MiB container limit, **443.41 MiB peak** with 68.59 MiB margin, without OOM in the qualified run. This is a past branch/fixture and cannot size ENFRA's new target or represent several concurrent users.
- **Historical, not Azure evidence:** draft #833 reports Chromium/WebKit median native first-preview measurements of 7.3327/9.0253 seconds (existing report), 3.4590/4.1789 seconds (issue thumbnail), and 4.9356/5.0311 seconds (Activity refreshed preview). Its own documentation calls this uncapped localhost headless browser evidence, not capped or production.
- **MISSING:** App Service memory/CPU/disk at 1/2/3 users, cold starts, 512 MiB upload through corporate ingress, active Writer/Calc memory and queue, p95/p99 conversion duration, DB/object throughput, Log Analytics GB/day, storage GB-growth, per-tenant concurrency and the confirmed regional SKU and unit costs. Do not fill cost-model numbers from legacy Render or guessed Azure public list prices.
