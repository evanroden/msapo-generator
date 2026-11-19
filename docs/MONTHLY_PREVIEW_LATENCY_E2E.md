# MR-021 / #491 — first useful evidence and section-preview latency

Status: **measurement harness; target PROPOSED, not approved.** Tracker #270;
integration owner P20. This work does not change production hosting, application
resource allocations, original bytes, cache semantics, the preview lifecycle or
the thumbnail gallery. It deliberately avoids P02/P18 preview-lifecycle files
and P06 issue-gallery files.

## Existing current implementation / attribution

The earlier warm PreviewStore optimization is already on main through #614;
fully warm raster requests no longer reopen PDFs. PR #810 (now merged)
introduced bounded, owner/revision/source/asset-scoped native section assembly
reuse. Do not reimplement these repairs or claim the ~20-second reported cold
preview was fixed by the ~0.2–1 millisecond raster optimization.

Older measurements are **historical and not this run's measurements**:
the 512 MiB/0.5 CPU resource run in issue #491 reported 15.606 seconds
for the first synthetic 13.6 MiB native section and its initial two images,
and 9.796 seconds for another visitor. These are *two samples*; the
29 October local phase probe saw 2.672–6.097 seconds spent in native assembly
in three calls but ran under different CPU/memory and LibreOffice versions.
Neither establishes production browser first paint or a distribution.

## Proposed acceptance target (not approved, not an SLA)

On the real production-image runtime restricted to **512 MiB RAM and 0.5 CPU**,
with the supplied synthetic workload and an empty prepared-source cache:
median **server-received-bytes → first verified thumbnail URI** no more
than 3 s for a 2-page PDF, 8 s for a 24-page PDF, 15 s for a bounded 96-page
PDF, 12 s for a four-image DOCX and 25 s for an eight-image DOCX. The first
two decoded native section preview pages should be available in a median
15 s, and same-owner/same-revision retries should reduce median repeat
time by at least 25% versus bypassing assembly reuse, with unchanged
native DOCX bytes, page geometry and first-two raster hashes.

For the **headless CI browser with the backend capped at 512 MiB / 0.5 CPU**,
propose median 15 s from
native known-value report-load press to the first decoded section image,
and median 8 s from native source upload selection through requested
decoded thumbnail. Headless Chromium/WebKit are *not* Render or physical
Safari. These browser targets require a full baseline and enough samples
before they can gate CI. Five samples per source workload and three per
browser engine are insufficient for a meaningful p95; only min/median/max
and each raw sample should be reported. Do not label these numbers as
owner-approved or retroactively treat the reported 20 s as a requirement.

## Reproduction and boundaries

All generated assets are invented. No client data or paid reader is used.

1. Build the repository at a **recorded exact SHA**, using the existing Dockerfile.
2. Run the capped backend experiment on that SHA:

   ~~~sh
   docker build --build-arg APP_GIT_COMMIT="$(git rev-parse HEAD)" -t msapo-491-latency .
   for part in sources native; do
     docker run --rm --memory=512m --memory-swap=512m --cpus=0.5 \
       -e RESOURCE_REQUIRE_512_MB=1 -e RESOURCE_REQUIRE_HALF_CPU=1 \
       -e ANTHROPIC_API_KEY=test-key-not-used \
       --entrypoint python msapo-491-latency scripts/qa_monthly_preview_latency_e2e.py --part "$part"
   done
   ~~~

   The source and native workloads run in separate fresh processes with
   identical 512 MiB/0.5 CPU caps: the first initial attempt mixed them in
   one process and the correct production headroom guard returned RenderBusy
   after the source trials. Benchmark contamination is not a reason to weaken
   this guard or increase service resources. Two JSON receipts are emitted.

   Six workload families: 2/24/96-page PDFs and 1/4/8-image DOCX files.
   Each uses five independently cold **profile namespaces**, with the
   identical raw source immediately rerun warm, and captures SHA256,
   byte length, page/item count, actual thumbnail dimensions, and separate
   extraction/thumbnail/total times. PDF first/middle/last pages are
   distinguishable by text; DOCX page numbers are **item identifiers**,
   not presumed physical Word pages. Two simultaneous 24-page PDF source
   visitors and same-name PDF byte replacement test source isolation and
   immutable revisions. The real eight-4800x3200-photo/ten-table native
   fixture is rendered three times with assembly reuse bypassed and three
   times with its owner/revision cache enabled, within the *same code,
   fixture and resource caps*. Capture generation-to-PDF, ticket storage,
   first-two-raster times, native assembly counts/SHA, image hashes and
   page geometry, process elapsed/CPU/RSS, cgroup OOM events, software
   version, source SHA and exact commit. The bypassed control is **not**
   a checkout of an earlier code revision.

3. On a runner with browser/LibreOffice dependencies installed, run
   the new browser-latency script. It starts a disposable real Streamlit
   Monthly QA fixture on localhost and measures three fresh native
   report-load→first decoded previews and three file-upload→explicit
   page-thumbnail clicks **per Chromium/WebKit**. It also records a
   real edited Activity revision, checks the saved input and waits for
   a current decoded image. It writes JSON and first-failure screenshots
   to the synthetic test-artifacts folder. The workflow repeats the same
   browser journey against the **same production Docker image** running
   the real isolated fixture with 512 MiB memory and 0.5 CPU. The browser
   itself remains on the host. Those receipts are separated into
   browser-uncapped.json and browser-capped.json, with Docker cgroup CPU,
   memory peak and OOM event diagnostics. The capped server serves the
   real application under test; no converted mock page is injected.

4. Opening a PR changing the measurement files triggers
   the Monthly preview latency evidence workflow. Its independent
   capped resource image and native browser jobs publish JSON receipts,
   Streamlit logs and diagnostics as artifacts. Compare raw JSON and
   observed medians **only after both jobs finish on the exact PR SHA**.
   Do not declare CI successful while queued/running. Follow existing
   regressions:

   ~~~sh
   python -m pytest -q \
     tests/test_monthly_report_preview_store.py \
     tests/test_monthly_report_section_assembly_cache.py \
     tests/test_monthly_report_preview_resources.py \
     tests/test_monthly_report_section_preview.py \
     tests/test_monthly_report_issue_page_gallery.py
   ~~~

## Scope of the measurements and remaining acceptance

The backend starts *after* browser upload bytes reach Python: it excludes
network transfer, browser scripting and visual paint. Browser scripts
capture those user-visible ends on localhost. One server uses uncapped CI
resources; one uses the actual production image capped to 512 MiB / 0.5
CPU while browsers themselves run on the host. Never add overlapping
backend phase times to user-visible browser elapsed times or claim
these are measurements from production Render/physical Safari. The browser may spend time in
intentional user-interface navigation between upload and requested image,
so that timing is an actual end-user journey rather than a pure backend
service latency. Warm source samples use durable content-addressed
prepared-image cache, while native section samples measure a different
short-lived assembly cache; do not conflate them.

The concurrent source visitors exercise overlapping server ingestion, not
two simultaneously admitted 512 MiB native LibreOffice conversions.
The backend replacement proves old source SHA and derived thumbnail remain
independent of the new source with the same name; it does **not** establish
the full native UI cancellation/retry, stale queued-result or restored-draft
scenario. Retain the existing targeted lifecycle tests and perform a served
same-session source-replacement/cancel/retry journey before #491 closure.

CI on this branch proves nothing until the exact-head jobs publish actual
results. A measured bottleneck must be identified before proposing another
product optimization. If the bottleneck remains new-revision assembly or
conversion, a warm raster optimization cannot solve it. If outcomes miss
these proposed targets, keep #491 open and route the next bounded fix and
served verification through P20. Do not close it from synthetic benchmark
code or a host change alone.

## A22 synthetic stage attribution (17 November 2026)

At the inspected starting main `f0af99567223aea3375f60e671450048be2bf0a0`,
the existing reproducible harness offered five cold/warm total-ingest and
thumbnail attempts for six source workloads, and three native runs per reuse
mode. **It did not distinguish hash/cache lookup, parse, visual read,
admission, conversion and raster in an ordered trace**. This missing
attribution is the baseline failure A22 exercises; it is not a measured
regression in rendering or proof of a conversion bottleneck.

The A22 collector in `app/monthly_report_latency_trace.py` is activated only
inside disposable synthetic harness calls and uses process monotonic clocks.
It emits allowlisted stage labels and relative elapsed/CPU milliseconds. It
never collects source filenames, contents, report identities, user IDs,
prompts, paths, model secrets or raw images. No collection, log or saved receipt
runs for normal application requests. Source-received is a point marker at the
beginning of the validated upload path. Hash/cache covers the content hash,
scope lookup and cache policy. Parse covers source inspection and derivative
metadata publication on a miss. Optional visual-read covers the actual
first-page derivative request, with raster nested within on a cold PDF miss.
No parse/raster span on a warm hit is correct and does not mean a page was
silently skipped.

Native-section receipts include work admission (`job_queue`), original DOCX
assembly (`native_assembly`), real LibreOffice conversion
(`conversion`) and first-two-page `PreviewStore` rasterization (`raster`).
A cooperative `read_with_capacity_wait` retry records only its actual queue
sleep, not the subsequent admitted read. The headless browser adds
`first_decoded_browser_image` from a real Load button press until decoded
image availability; uploaded-source first-image timing is measured separately.
These are **distinct clock origins and journeys**: server spans may be nested;
do not add them to browser end-to-end wall time.

The CI evidence workflow now runs the *same checked-out SHA and synthetic
fixtures* under both 512 MiB/0.5 CPU and no explicit Docker cgroup caps,
with at least five cold/warm source attempts per 2/24/96-page PDF and
1/4/8-image DOCX, plus three native attempts per reuse mode and three browser
attempts per Chromium/WebKit engine. Production-image CPU and RSS/cgroup OOM
counters, source hashes, native package-member digests, thumbnail hashes,
page counts and geometry remain in the existing receipts. Uncapped is a
CI-runner resource class, **not a larger authorized production instance**.
The synthetic test asserts cold parse/warm reuse, strictly ordered nonnegative
clock spans, disabled-telemetry safety, invalid inputs, independent profiles,
same-source digest, replacement survival and cooperative retry cancellation.

Interpret `dominant_*_stage` only after both exact-head CI artifact families
finish. It is a mean among the listed *nonoverlapping top-level stages*,
not a proof that a specific service is the live-user bottleneck; visual raster
is nested inside visual read and must not be double-counted. If capped and
uncapped artifacts disagree, report both rather than selecting a favorable
sample. No scheduling or cache-policy optimization is justified merely by
adding this trace. Real client documents, a served production writer, physical
Safari and authentic DOCX/PDF report acceptance are outside this harness.

## A89 — Render versus Azure attribution without cutover (17 November 2026)

This comparison is a **read-only assessment**, not a hosting change. Repository
issues #270, #491, and #941 stay open. The existing
'qa_monthly_preview_latency_e2e.py --part sources|native' is the workload
source of truth; do not add a special faster case for one host. It writes to a
fresh temporary namespace, not the application's standing-data directory.
Only run it where a disposable isolated process/container and the host's
resource policy permit it. Do not run synthetic generation against an active
customer workspace, change service replicas, copy private client reports, or
switch the authoritative writer.

**Control-plane baseline (17 Nov, observation only):** Render's service
metadata showed one Oregon Docker instance with a 1-vCPU, 2-GiB configured
limit, deploying from main. Read-only deploy metadata showed its current
build's commit, but neither Render's deploy status nor GitHub's main
SHA independently establishes which build a browser session receives.
Contemporaneous Render CPU/memory samples were idle/low-usage and HTTP
latency samples were unavailable. The Azure served build, active revision,
region, replica count and CPU/RAM limits were **not independently verified
in this A89 run**. The private Azure identifiers, credentials, endpoints,
revision IDs, and container diagnostics must stay outside this public repo.
In particular, do not infer that Azure is slower or faster from these facts.

### Reproducible, synthetic-only side-by-side control

1. Read deployment/build identity independently for each environment. On
   Render, reconcile live deploy status and its commit with About's served
   'APP_GIT_COMMIT'; on Azure, reconcile About with the active Container Apps
   revision/image and the reported commit. Record the current writer
   separately. If any of these disagree, mark identity unverified; don't
   silently substitute main or a registry's newest tag.
2. In an **isolated** container built from a pinned SHA, run the existing
   '--part sources' and '--part native' commands via
   'scripts/qa_monthly_host_deterministic.py' in separate fresh processes
   at identical '--memory=512m --memory-swap=512m --cpus=0.5' limits with
   'RESOURCE_REQUIRE_512_MB=1' and 'RESOURCE_REQUIRE_HALF_CPU=1'.
   Capture both JSON files, the exact image/SHA and nonsecret platform
   resource metadata. Repeat using the same pinned image and limits on the
   other host *only if permitted*. The application/renderer image, dependency
   versions and generated input hashes must match. The A89 runner preserves
   the existing benchmark work path but replaces synthetic noise randomness,
   DOCX ZIP timestamps and PDF trailer IDs with deterministic equivalents
   inside its disposable process only. For naturally different
   1-vCPU/2-GiB or other host limits, run a second separate equal-limit
   control before interpreting the observed host configuration.
3. Bundle each host's **synthetic-only** receipts as JSON. The two names below
   refer to private **local files**, never production endpoints:

   ~~~json
   {
     "synthetic_only": true,
     "execution": "isolated",
     "served_commit": "<40-character pinned and independently checked SHA>",
     "region": "<general nonsecret region, or omit>",
     "service_resource_verified": false,
     "sources": "<replace this string with parsed backend-sources.json object>",
     "native": "<replace this string with parsed backend-native.json object>"
   }
   ~~~

   The input's 'served_commit' is checked against **both benchmark receipt**
   commits. An operator must independently verify it against the actual
   served build before claiming served acceptance. Use 'served_synthetic'
   only when the workload genuinely ran on the relevant served environment
   in isolation; use 'isolated' for CI/disposable Docker. Set
   'service_resource_verified=true' only with independently captured
   control-plane evidence; this is a *declaration*, not remote attestation.
   Private identifiers and host URLs should be omitted entirely.
4. Compare the files without making network or data-store calls:

   ~~~sh
   python scripts/qa_monthly_host_comparison.py \
     --render /private/render-synthetic.json \
     --azure /private/azure-synthetic.json \
     --output /private/host-comparison.json
   ~~~

   Exit 0 means matching verified *receipt contents*, not causal proof;
   exit 1 means a confounder; exit 2 means missing/malformed/unsafe receipt.
   The tool shows per-case **five-sample** cold/warm median/min/max times,
   native no-reuse/reuse medians, exact commit and limits, and reported RSS.
   It rejects OOM-tainted cases, missing/duplicate workloads, stale commit
   receipts, absent native control and mismatched page/raster identities.
   Output whitelists only timing, build and resource fields: unrelated fields
   in the private input are never copied to its summary.
5. Keep HTTP client/network/first-paint metrics **separate** from the
   synthetic Python timing boundary. If either host's request metrics lack
   sufficient samples, report no median rather than inventing one.
   CPU quota, RAM, deployment state, region, image digest and active writer
   are independent variables; do not label different-build/different-limit
   results a software or platform regression. An identical artifact on two
   hosts may still differ because of cold starts, noisy neighbors, storage,
   concurrency or network conditions. The comparison never measures user
   clicks, browser paint or real reports.

**Decision rule:** Do not raise the hosting plan or change minimum replicas
from an idle control-plane sample. If equal-image, equal-limit, equal-fixture
cold and warm distributions show CPU saturation, evaluate a separately
authorized 1-vCPU/2-GiB versus 0.5-vCPU/512-MiB capacity experiment, with
per-session RSS and queue/Office child CPU included. If idle latency remains
high, isolate startup, disk/LibreOffice, preview raster, network, and browser
decode before spending. Minimum replicas help measured cold starts, not
slow conversion; a background-worker queue helps only if bounded queue
delay/concurrency is the measured bottleneck. No billing, replica, deployment,
production-write, or Azure cutover configuration changes are authorized by
this evidence.
