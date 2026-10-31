# Warm preview raster-cache measurement — 28 October 2026

Related: #491, #469, #270. This is a bounded optimization, not closure of the
reported roughly 20-second first-preview observation.

## Reproduced work and repair

`PreviewStore.pages` reopened and parsed the temporary PDF even when all requested
page rasters were already cached. It did not rerasterize those pages. The repair
opens the PDF lazily on the first actual raster miss and closes it on both
success and failure. It retains the same lock, ticket/owner validation, expiry,
backing-file existence check, LRU order, byte accounting, resolution, image
encoder and one/two-page request bound. No new persistent or session cache is
introduced. A failed request does not keep an open document.

An expired, discarded or missing-file ticket still returns no cached images.
A changed report uses its existing replacement-ticket path, not old page bytes.
The implementation does not change upload, source inspection, Word conversion,
preview scheduling, final export, hosting or the direct Review feature.

## Proposed target and method

Engineering target for this **warm-cache slice**, not an owner-approved SLA:
zero PDF opens for fully cached page requests, identical requested image bytes
and geometry, and at least 75% lower median warm-request time for the local
24-/120-page workloads. Timing is observational and is **not** a CI threshold.
The deterministic no-open/content/lifecycle assertions are the regression gates.

The reusable command is:

```sh
python scripts/benchmark_monthly_preview_cache.py --output /tmp/preview-cache.json
```

Use the same benchmark on the baseline and candidate. It creates only synthetic
PDFs: distinct page labels, separate vector streams and rotated pages. Each
workload has seven independent caches, one cold-raster request for first/last
pages at 120 DPI, then 60 warm requests per cache (420 warm samples). It compares
all returned bytes/order to that cache's cold response, verifies identical cold
raster hashes across repeats, and records PDF/raster hashes, wall/CPU
distributions, PDF-open counts, cache byte counts and process peak RSS. The
PDF-open counting wrapper is inside the measured interval in both runs.

“Cold” here means an empty **raster cache** after validated PDF insertion. It
does not mean cold OS/file caches, upload-to-thumbnail, queued conversion,
DOCX-to-PDF assembly or browser paint. This serial benchmark is not a device,
load or concurrency benchmark. A separate controlled four-thread regression
checks only warm-owner isolation, not throughput or PyMuPDF concurrent parsing.

## Local before / after results

Baseline repository: `a1b2aa61aa92c596d424c95dba29be66135f3441`.
Environment: Python 3.13.5, PyMuPDF 1.28.2, Linux x86_64; locked runtime wheels
were verified against the baseline requirements. No CPU/RAM cgroup cap was
established for this timing comparison. Values below are milliseconds.

| Pages | Vector marks/page | PDF bytes | Cold median before / after | Warm median before / after | Warm p95 before / after | Warm median reduction |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 8 | 3,210 | 163.992 / 153.138 | 0.2164 / 0.0059 | 1.5016 / 0.0164 | 97.3% |
| 24 | 80 | 259,233 | 143.467 / 149.034 | 0.2712 / 0.0059 | 1.6955 / 0.0143 | 97.8% |
| 120 | 120 | 1,940,993 | 157.284 / 219.116 | 1.0283 / 0.0059 | 2.6747 / 0.0160 | 99.4% |

Each baseline workload made **420 warm PDF opens**; each candidate made **zero**.
Both versions made seven cold opens per workload. Every PDF hash and both
first/last raster hashes match between runs. The largest workload retains
1,940,993 PDF bytes and 196,246 raster bytes, unchanged. Process peak RSS was
225,656,832 bytes before and 228,409,344 after; these are cumulative process
peaks, not isolated request allocations or a memory improvement claim.

The absolute warm saving is approximately 0.21–1.02 ms per request. It must
not be described as eliminating a 20-second delay. Cold timings varied and the
120-page cold median was higher after the change; no cold-speed improvement or
production latency guarantee is established by this local measurement.

Recorded implementation SHA-256:

- Before: `a48755dbbba3709e6eb47a12852ffa5f071e3538004f38981248995e02e65c45`.
- After: `42a5ef7c12e100b22c0c1ccab6d6c94bfa3d36eeef2af390c6c861a454b29939`.
- Unchanged benchmark: `01f6414590a75378a5d0b34829dd590cbb3ab0d36d4929ae802ba8626d1532d1`.

The JSON output includes the complete timing summaries, CPU values and image
hashes for independent repetition. No client source files or credentials are
used or included.

## Verification and release boundary

The initial new-test subset reproduced 12 failures / 7 preservation passes on
the baseline. Final focused results, including the benchmark smoke case, are
recorded on the implementation PR. Tests exercise all three supported DPIs,
one/two cached pages, partial hits in both orders, raster eviction/accounting,
noncacheable pages, missing/expired/discarded tickets, wrong owners/forged
tickets, changed-preview replacement, exception cleanup and four simultaneous
warm visitors. Existing reference and preview-lifecycle tests remain unchanged.

Local Python/pytest differs from hosted Python 3.12/pinned pytest. Required
exact-head CI, independent review and served/native-browser acceptance remain
mandatory. Keep #491 open for cold source/conversion/queue measurements,
representative DOCX and larger/image-heavy workloads, device/browser paint,
resource-capped concurrency and an agreed end-to-end target. No merge or
deployment is authorized by this benchmark.
