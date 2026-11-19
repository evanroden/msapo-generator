# A19 — optional compute scale-up (decision record, 17 Nov 2026)

Refs #270, #491, #941. This change does **not** approve a new billable
service, plan, replica, data writer, Azure deployment or cutover. No customer
inputs or state were accessed for these observations.

## Observed baseline (not a report-generation benchmark)

GitHub main at investigation: `f0af99567223aea3375f60e671450048be2bf0a0`.
No open PRs at the inspection instant. Render workspace service read-only
inspection on 17 Nov showed **one instance, plan `1c-2g` (1 CPU, 2 GiB)**,
with a **1 GB persistent disk mounted at `/test1`** and automatic deploy
from main. Checked-in `render.yaml` still states the *legacy* `starter`
plan; it is **not** reliable evidence of the live plan. Live instance/resource
limits are confirmed by Render's API, not inferred from the YAML.

Render resource telemetry from 16–17 Nov 2026 (nonuniform deployment
instances; do not interpret as a controlled workload):

| Metric | Five-minute sampled p95 | Five-minute max | One-minute max |
| --- | ---: | ---: | ---: |
| CPU, fraction of 1 CPU | 0.0281 | 0.3701 | 0.7531 |
| Memory RSS-like usage, MiB | 393 | 429 | 539 |
| CPU limit | 1 CPU | 1 CPU | 1 CPU |
| Memory limit | 2 GiB | 2 GiB | 2 GiB |

The HTTP p95 latency metric returned **no samples**. There are no observed
CPU-throttling counters, IO-wait/disk-IO saturation measurements, or queue
durations in this read-only data, so none is asserted. A filtered Render
service-event query over the same two days found **no** `server_failed`,
`server_restarted` or disk-usage-high events; this does not rule out
short-lived OOM pressure between samples or client-side stalls. Report preview
latency of approximately 20 seconds in #491 is a meeting observation, not a
reproduced current-main measurement. No real-source, device or served-render
acceptance is claimed.

## Architecture and data ownership

- All three workflows (Monthly, PO/Smartsheet and Expense) share the single
  application instance. `app/pdf_converter.py` enters a cross-process
  LibreOffice filesystem flock at `monthly_reports/render-jobs/.conversion-lock`
  under `EPC_DATA_DIR`; it also uses private temporary export directories.
  **That conversion gate stays exclusive** at every compute setting.
- Report assembly and several report-preview/source-read operations enter the
  in-process `work_slot` gate. Previously it was always one
  `threading.Lock`. A larger host cannot accelerate a first-user
  single-threaded build merely by admitting more concurrent jobs.
- Preview files are disposable, per-owner, bounded by 64 MiB disk/8 MiB raster
  and are **not** durable report history; do not migrate their tickets across
  pods or treat them as shared standing data.
- SQLite and saved report artifacts remain on the persistent share. Azure
  Container Apps mounts an Azure Files/NFS-like share and is governed by the
  **single authoritative writer** cutover plan. Scale *up* one instance,
  never scale *out* multiple active writers over the same mutable path without
  a separately designed ownership/transaction/queue protocol. Render is the
  authoritative writer until M7; Azure rehearsals/copies are not a synchronized
  second writer. No report/store migrations are in this PR.

## Optional resource policy (infrastructure neutral)

`MSAPO_HEAVY_JOB_CONCURRENCY` defaults to `1` (unchanged legacy mutex).
An operator may **separately authorize** `auto` or a positive integer 2–8,
but larger concurrency starts only if **both** finite cgroup CPU quota and
memory limit are readable (v2 or v1), CPU affinity allows it, the CPU quota
has at least that many *whole* cores, and the memory limit budgets **2 GiB
per heavy job**. Invalid, missing, fractional, unlimited or undersized limits
fall back to a single job. Static policy is read once at process startup.

When opt-in permits multiple assembly slots, every *additional* live report
work lease checks current cgroup headroom, reserving
`512 MiB + 768 MiB × (active jobs + 1)`. Under pressure, missing usage
counters, or a runtime scale-down, additional work fails promptly without
starting a second job; the first still uses the original single-worker path.
Review/foreground priority, nested work leases, 130-second bounded waiting
and the independent conversion lock remain. No distributed queue, worker
service or cross-process heavy-assembly coordination is introduced. The
application must retain one serving instance until that design is addressed.

Expected deterministic capacity decisions from **synthetic cgroup fixtures**
(not measured job speed):

| Cgroup CPU/RAM | Flag off (default) | Flag `auto` | Physical benchmark |
| --- | ---: | ---: | --- |
| 0.5 CPU / 512 MiB | 1 | 1 | Existing 512 MiB QA; no A19 cold/warm wall-time measurement |
| 1 CPU / 2 GiB (live Render) | 1 | 1 | Render telemetry only; not a benchmark |
| 2 CPU / 4 GiB | 1 | 2 | Not run; no deployment authorized |
| 4 CPU / 8 GiB | 1 | 4 | Not run; no deployment authorized |
| 8 CPU / 16 GiB | 1 | 8 | Not run; no deployment authorized |

## Compute decision matrix

Render public pricing and compute plans (checked 17 Nov 2026):
https://render.com/pricing and https://render.com/docs/compute-plans .
These are **listed service prices**, not a measured user bill; plan prices
exclude incremental storage, bandwidth and other services.

| Option | Listed monthly price (one service) | First-user wall time | Throughput | Constraints/decision |
| --- | --- | --- | --- | --- |
| Existing 1 CPU / 2 GiB | $25 | measured latency unavailable | reference | Stay here until reproducible workload shows bottleneck |
| 0.5 CPU / 512 MiB control | $7 | unknown; resource pressure likely | unknown | control only; not a downgrade recommendation |
| Vertical 2 CPU / 4 GiB | $85 (+$60) | potentially faster on CPU-bound stages, **unmeasured** | optional 2 simultaneous heavy assemblies | first upgrade candidate **only if** benchmark demonstrates a gain and funding approved |
| Vertical 4 CPU / 8 GiB | $175 (+$150) | possibly faster on parallelizable stages, **unmeasured** | optional 4 simultaneous assemblies | require measured contention and memory margin; not currently justified |
| Vertical 8 CPU / 16 GiB | $300 (+$275) | unmeasured | optional 8 simultaneous assemblies | no evidence presently justifies cost |
| Memory-optimized 2 CPU / 8 GiB | $135 (+$110) | unmeasured | at most 2 assemblies | investigate only if memory, not CPU, dominates |
| Dedicated report worker | web + separate billed worker/queue | queue wait may improve, not conversion time | isolation possible | requires queue durability, auth, job ownership, idempotency and *single-writer* design first |
| Prewarm on startup | app cost + warm CPU/memory | may reduce first cold render | unchanged | safe future targeted measurement; do not process private originals on startup |
| Tiered first-page thumbnails | app cost | likely reduces first useful paint | reduces raster load | evaluate in #491 with full-resolution on demand and revised cache keys |
| Cache migration / shared thumbnail cache | storage and invalidation cost | warm-cache benefit only | may reduce repeat work | cannot transfer private session tickets across tenants/pods; source revisions and owner scope must be encoded |

**Do not claim performance improvement from increased concurrency alone.**
First paint for one report depends on parsing, assembly, the exclusive
LibreOffice conversion, raster work and UI updates. Parallel assembly mostly
addresses simultaneous visitors; it may increase foreground latency under
contention. The proposed #491 performance target requires an owner-approved
workload and a measured baseline, not a goal attributed to the meeting.

## Verification and next decision gate

Failing-before case on the main SHA: at any configured CPU/RAM size, the
old single `_WORK_SLOT` cannot admit two simultaneous synthetic heavy report
leases, and no cgroup opt-in policy existed. After: two independently labelled
synthetic work leases can overlap only with the new opt-in capacity; a
third/under-pressure lease cannot overwrite accepted data. Existing default
locking, reentrant conversion, output and crash cleanup remain unchanged.

The repository regression tests cover v1/v2 quota parsing; disabled, malformed,
missing and unlimited flags; 512 MiB/0.5 CPU, 2 CPU/4 GiB and 4 CPU/8 GiB
**simulations**; parallel synthetic work, memory pressure and incomplete
counter fail-closed, exception release and OS-killed conversion-lock owner.
Tests are not a real DOCX/PDF throughput or data-persistence acceptance test.
Existing 512 MiB resource QA and full CI are still necessary.

Before any spend or runtime flag enablement, in a **single-writer isolated
environment** run identical synthetic cold/warm 1-page and 12-page PDF/DOCX
workloads (also scanned-only pages), with 1/2/4 concurrent users, on 0.5
CPU/512 MiB, 1 CPU/2 GiB, 2 CPU/4 GiB and 4 CPU/8 GiB *where provisioned*.
Capture p50/p95 wall-to-first-preview, queue wait, conversion time, CPU usage,
RSS peak, CPU throttle counters, disk IO, first paint, DOCX/PDF SHA/layout,
restart recovery and verified saved/reloaded human edits. Report a real
cold/warm control at each limit; reject extra capacity if OOM, error rates or
data scope regress. Proposed (not approved) acceptance target: >=25% p95
wall-time gain for representative workloads, with identical content and
no higher error rate.

**Funding decision:** changing Render's running plan from `1c-2g` to
`2c-4g` adds a listed **$60/month** per instance; `4c-8g` adds
**$150/month**. Creating dedicated workers or additional storage also adds
billable resources. These require independent infrastructure/funding approval
and must not be inferred from this code PR. This PR intentionally leaves
`render.yaml`, live Render billing, Azure resources, deployment and M7
unchanged. Changing only code on main does **not** authorize turning the
new flag on in Render or Azure.
