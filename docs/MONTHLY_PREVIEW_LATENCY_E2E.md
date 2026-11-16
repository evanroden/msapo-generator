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
