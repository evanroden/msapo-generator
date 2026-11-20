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

## A01 extension — critical-path receipts (17 November 2026)

Baseline SHA: `f0af99567223aea3375f60e671450048be2bf0a0`.
The baseline has cold/warm backend phases and real synthetic native-browser
timings, but does **not** export per-request process/thread queue waits,
numeric-only office execution spans, 256-row CSV/XLSX timing distributions, or
initial navigation-to-interactive time. This is the deterministic
**missing-measurement baseline**, not a fabricated slow production run.

The A01 instrumentation is passive and context-local: it records only a
fixed phase name, milliseconds and outcome within an explicit benchmark
capture. No filenames, content, source/site identifiers, API inputs or paid
reader calls are included. Non-benchmark users have no emitted spans.
Work-admission, intra-process office locks and cross-process file locks are
separate. Nested office calls do not double-count lock waits; a rejected
request records `busy`. The native fixture records physical assembly,
office lock/convert and first-two-page raster per run.

For PRs changing the harness, CI runs the **same exact production Dockerfile
and requirements.lock** in three isolated phases: uncapped backend, 512 MiB /
0.5 CPU backend, and browser headless Chromium/WebKit against both uncapped
runner and a capped server. Raw JSON, Docker inspect settings, RSS/peak,
cgroup OOM events, CPU usage and browser samples are artifacts. Do not compare
uncapped and capped data from different head SHAs. Each cold ingest uses a
fresh synthetic namespace; warm re-ingest uses the same immutable original.
CSV/XLSX contain exactly 256 invented work-order rows. Text/tables are
deliberately **not** assigned a raster thumbnail. The mixed case ingests
PDF/DOCX/CSV/XLSX and validates duplicate SHA identity and rejected
empty/unsupported/malformed inputs. DOCX sources contain 1/4/8 photographs
**and** small tables. Backend concurrency covers two distinct source
namespace owners, not two simultaneous LibreOffice conversions.

Benchmark commands on the exact checkout, run both resource modes:

```sh
docker build --build-arg APP_GIT_COMMIT="$(git rev-parse HEAD)" -t msapo-a01 .
for part in sources native; do
  docker run --rm -e ANTHROPIC_API_KEY=test-key-not-used \
    --entrypoint python msapo-a01 scripts/qa_monthly_preview_latency_e2e.py --part "$part"
  docker run --rm --memory=512m --memory-swap=512m --cpus=0.5 \
    -e RESOURCE_REQUIRE_512_MB=1 -e RESOURCE_REQUIRE_HALF_CPU=1 \
    -e ANTHROPIC_API_KEY=test-key-not-used \
    --entrypoint python msapo-a01 scripts/qa_monthly_preview_latency_e2e.py --part "$part"
done
docker run --rm --entrypoint python msapo-a01 scripts/benchmark_monthly_preview_cache.py --output /tmp/raster.json
```

Read each JSON's `environment.commit`, `samples.*.samples_ms`,
`native_section.runs.*.samples.*.critical_path_spans` and cgroup fields.
The standalone raster benchmark now reports raw samples and omits p95 for
under 20 samples. The browser `navigation_to_first_interactive_seconds`
is separate from press-to-decoded-preview and upload-selection-to-thumbnail
elapsed. Its upload clock **includes** UI clicks and localhost transport and
cannot isolate pure transfer from processing. Neither backend phases nor
headless-browser readings constitute a live Render measurement.

### Five critical-path hypotheses and proposed targets, NOT measured results

| Ordered probe | What to quantify | Proposed improvement goal | Would added CPU/RAM help? |
|---|---|---|---|
| 1. Cold native assembly | `native_assembly` and conversion-independent package SHA | Reduce cold native assembly median at least 30% with equal package parts and scope | CPU/RAM may help large picture processing; reuse will not help a changed revision |
| 2. Writer execution | `office_execution` less `office_*_queue`; generated PDF SHA/pages | Reduce median conversion/execution at least 25% | CPU helps CPU-bound conversion; RAM helps only if currently memory-limited |
| 3. Admission and wait | `work_queue` and `office_thread_queue`/`office_process_queue` (busy rate) | Reduce waiting without increasing OOMs; maintain finite queue and correct priority | Larger resources alone cannot remove serialized file locks |
| 4. Cold PDF/DOCX extraction | cold ingest and thumbnails, separately for 2/24/96 PDF and 1/4/8 DOCX | Reduce cold PDF-24 and DOCX-4 median at least 20% | CPU can help OCR/pixel decoding; no paid AI is invoked in CI |
| 5. First decoded browser image | navigation→interactive, press→image, upload→image, edit→current | Cut synthetic first-use/interaction median at least 25% without stale paint | Network transfer, Streamlit rerun, navigation and browser decode may dominate regardless of server CPU |

These are optimization *hypotheses and candidate targets*, not measured
before/after improvements or owner-approved SLAs. Actual ranking requires
the new exact-head JSON samples. Exports, saved/reloaded state, real AI
response wall time, source mapping versus extraction microspans, cross-site
month acceptance, physical-device first paint and live production speed
are **not** individually measured by this addition. Their absence must
remain visible when routing A02–A05/A19; never infer acceptance from this
harness.

## A88 same-image resource matrix (synthetic-only, pending exact-head CI)

The baseline on main `9f84d829288dca14abb911a86c1c373f63254c34` had
a 512-MiB/0.5-CPU backend measurement, a separate **uncapped host Python**
browser reference, and one concurrent 24-page source intake. Thus a same-image
512-MiB versus larger Docker comparison, 96-page concurrency, and actual decoded
browser pixel-byte hashes could not be recovered from its receipts. This is a
measurement/regression gap; it is not proof of a previously slow production
server or a safe hosting change.

The A88 workflow builds **one** production Docker image at its exact PR head and
runs the existing 2/24/96-page source and 1/4/8-photo DOCX cold/warm controls
plus eight-source-photo/ten-native-table section previews with *two resource
caps*: 512 MiB/0.5 CPU and 1024 MiB/1 CPU. Each part is an independent
container/process; all generated sources and clients are synthetic. Both photo
builders use a fixed-seed texture in the A88 experiment, leaving the preexisting
resource test's stochastic image path unchanged. Three two-visitor 24-page and
96-page cold/warm races, three native section assembly controls and three
two-visitor native-preview admission races run inside each backend cap.
The native race reports admitted image, explicit RenderBusy, and sequential
retry separately. It does not fabricate a queue wait for a **nonblocking**
automatic-preview admission. Source ingestion has no measured application queue,
so its queue-wait field is null, not zero.

The browser job separately repeats the same genuine Streamlit synthetic QA
fixture in Chromium/WebKit with three new browser sessions per engine/cap.
It records load-press to first decoded image, upload-to-requested decoded
thumbnail, edit-to-current decoded image, element geometry, image URL hash,
**decoded PNG screenshot hash**, edit preservation, and native preview revision
identity. The uncapped host Python run remains a reference only and is not one
of the two same-image capped samples. These are headless CI browsers, not
physical Safari, a deployed render service, or real-source acceptance.

The comparator `scripts/qa_monthly_preview_a88_compare.py` fails if resource
limits or cgroup OOM evidence are wrong, raw sample counts are insufficient,
small samples claim p95, synthetic source SHA differs between caps, or native
raster hashes/page geometry differ between caps. It records min/median/max and
all source receipt values; it makes **no** throughput gain claim before real
paired numbers are published. For source concurrency, each visitor supplies
one observation per repetition (six measurements); these are not six
independent server cold starts. Native preview contention is labeled admission
plus retry, never a measured queuing distribution.

Re-run the `Monthly preview latency evidence` workflow at the PR head; consult
the `monthly-preview-latency-capped` and
`monthly-preview-latency-browser` artifacts for the two resource subdirectories,
the `a88-backend-comparison.json` and `a88-browser-comparison.json`, and
cgroup inspect/logs. No renderer, scheduling, client data, source retention,
production resources or hosting billing plan are changed by this experiment.
