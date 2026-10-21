# Isolated source-render diagnostic

This is a source-inspection tool, not report generation, source-role approval,
price approval, or October-report completion. It does not change import gates,
standing assets, draft state, design history, or shared fixtures.

Open the existing Monthly report route with `monthly_qa=isolated` (or retain
`monthly_qa=fixtures` if already there). Expand **Inspect an original or test
derivative with the production renderer**. Select a fresh DOCX of at most
32 MiB, name it as an original or a named derivative, and explicitly choose
**Render source preview only**. No synthetic fixture load/reset is needed.

The raw upload remains byte-identical. The current `passive_docx` safety policy
produces a full-resolution render input: no source images are downsampled and
no report assembly/normalization is applied. Consequently this is a *passive
source-copy baseline*, not proof of how raw original bytes render. Macros,
active/embedded payloads and external resource relationships are rejected;
ordinary passive web hyperlinks follow the existing package policy. Unsupported
visible content still fails closed. The existing package helper remains the
owner of privacy/style sanitation; this diagnostic does not duplicate it.

Per-session downloads provide the untouched source, exact passive render input,
source-inspection PDF if successful, and an immutable JSON attempt receipt. The
receipt includes source/input/PDF hashes and sizes, per-part sanitation changes,
page count, the estimated package-memory admission budget and actual available
headroom/counters, actual LibreOffice version, deployed commit when available, font
inventory and hashes of the production-resolved expected fonts. Bounded Office
stdout/stderr presence, byte counts and hashes are retained without their text;
success does not claim that Office emitted no warnings. No watermark is
added to the PDF, so the file can be used for pixel comparisons. Its download
name and UI identify it as **SOURCE PREVIEW ONLY**.

One fresh request is consumed once. Failure is recorded without automatic retry;
**Clear source-preview files / start a new attempt** is explicit and affects only
this session's diagnostic artifacts. A changed file, label or kind invalidates
the old attempt. Save wanted diagnostic downloads before changing selection.
The raw file can be reselected for a deliberate new attempt. After a browser
reload, **Clear earlier source-preview files in this browser (including other
tabs)** can reclaim old diagnostic owners without resetting the editor. This
explicit action is bound to the displayed owner incarnations and cannot delete
a reopened selection or another browser's artifacts. Active attempts are
protected by a ten-minute diagnostic lease; expired attempts cannot publish. A QA namespace
reset or newer selection cannot publish an older result. These controls do not
clear the report editor or modify an existing Demo draft.

Files live only under the existing browser-isolated QA namespace, not the live
output directory or shared fixture catalog. This adds no authentication or new
confidentiality guarantee. The helper reserves a bounded 128 MiB diagnostic
store per isolated browser, at most 384 MiB disk-wide (also capped at one quarter
of actual filesystem capacity, including pending artifact/scratch reservations),
128 data-bearing/pending attempts, and a free-disk floor of the smaller of
256 MiB or one eighth of filesystem capacity. Empty page visits do not allocate
owners or consume attempt slots. A bounded helper-owned index tracks attempts
without scanning unrelated QA namespaces. Its atomic reservation precedes
source/claim writes, has a finite deadline after crashes, and remains until
payload cleanup finishes. A short cross-process lock serializes accounting
across cookies; index metadata contains only opaque identities and deadlines.
Only diagnostic folders inside marker-verified QA namespaces are eligible for
six-hour inactivity expiry; editor data, shared fixtures and live storage are
never pruned. Downloads renew retention. Package-change and font inventories are
bounded before conversion/publication; over-budget package inventories produce
a small explicit failure receipt with source/input downloads, not a hidden
success. The helper uses the existing low-priority heavy-work admission,
conversion lease and process-tree cleanup, and rejects a non-24.2 engine or
unexpected production font resolution. Each attempt has a 120-second conversion
wall limit, 90-second CPU limit, 1.5 GiB virtual-address limit, 32 MiB file/output
limits and a 150-page PDF limit. Production's existing container memory limit
still applies. Before any XML parser or passive sanitizer, admission streams all
package parts (including renamed XML), accounts two compressed-source buffers,
four expanded-package copies, and conservative markup/attribute overhead, and
limits every expanded part to 24 MiB. Its estimated allowance is the smaller of
actual available memory and 320 MiB, less a 32 MiB margin. This is conservative
admission, not hard process-memory isolation or a universal no-OOM guarantee.
Valid large/dense sources or low-headroom attempts can be refused unchanged;
media are never silently reduced. Immediately before Office, header-only checks
on the exact passive input additionally limit each raster to 16 million pixels
and budget two four-byte-per-pixel copies across all images, with a 96 MiB
renderer reserve. This separate allowance is capped by current headroom and
1 GiB; it is not a claim that every source fits every service plan. Multi-frame
images, decompression warnings, and metafiles without a supported raster budget
are explicitly unsupported by this diagnostic. Receipt evidence records the
actual dimensions aggregate and admission budget, without decoding or resizing
images. Diagnostic conversion does not use another backend or service.

Synthetic unit/UI checks can prove request identity, isolation, safety rejection,
cleanup and command bounds; mocked conversions are **not** render/fidelity
acceptance. A legitimate comparison requires downloading the actual served
receipt and artifacts and inspecting the genuine source/derivative outputs on
the deployed 24.2 engine. No private source belongs in Git or CI artifacts.
