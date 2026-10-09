---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: f0e7fa32a20d95a9ae7338060397d9de34fab42c
status: stable_renderer_acceptance_passed_pending_ci
---

# Native ENFRA master report design

The prior renderer rebuilt imported reports inside a generic shell. It did not
preserve the source page design despite using that output for live previews.
The owner's correction requires the native ENFRA layout for every report,
including a new report started without an upload.

The native renderer uses the source Word package's page geometry, styles,
positioned artwork, native text boxes, section properties and header/footer
relationships. Source facts are cleared before current report values populate
native content locations. Empty sections remain present. Master reuse removes
source-client logos and site imagery unless the selected report supplies them.

The passive package reader retains closed local dependencies and rejects unsafe
or unsupported visible objects explicitly. No private report, contact values or
runtime master assets enter the repository. Reference documents remain immutable
runtime objects with integrity-checked hashes.

The master registry saves revisions with editor attribution and concurrent-write
guards. New reports pin the current master automatically. Existing saved reports
retain their pinned version; applying the current master is an explicit action.
The infrequent master-update upload is inside collapsed advanced design settings,
separate from the single Starting report upload for monthly content.

Full DOCX output, PDF conversion and active-section preview share the native
renderer. Native previews use actual source section ranges and inherited page
chrome, rather than assuming a fixed pair of Word sections per report section.

Validation includes source-package fidelity, absence of previous source data,
master reuse across contracts, design-version pinning, current-content rendering,
native section preview, and visual comparisons against supplied originals.

## Checkpoint evidence

Draft PR #90 initial head `3071e15bc26c90e13532c4bed18fa865a1241c29`
(tree `13b65d8e60e143e4c0d093d44a8df0a7d1cbe5df`) passed Actions
`37921482195`, job `113790193342`: **1392 passed, zero skips**. This is a
code regression result, not completed-report visual acceptance.

Subsequent UMMC replay found and corrected divider/content routing, photo-grid
tables incorrectly treated as work-order data, missing image captions, and
end-of-life table placement. Source photos now occupy individual native frames.
Only explicitly matched current payloads qualify for retaining their original
styled nodes. Large body pictures cannot become master decorations merely from
their dimensions. The fresh-report UI automatically selects and saves the master
version without requiring an upload or another template choice.

The second draft head `f8b6a36d0332f83d5d705c8541e5e539aeb65ca8` passed
Actions `37923262461`, job `113796046634`: **1402 passed, zero skips**.
Later targeted native/import/start checks passed 71 tests and the passive-package
checks passed 19 tests. These are separate checkpoints, not an additive total.
The complete private UMMC replay records three Cost-column removals from the
existing content policy; they must be reported separately from layout defects.

The alpha-renderer checkpoint below is historical. LibreOfficeDev 26.8 alpha
produced inconsistent divider backgrounds from identical DOCX packages. Cache,
swapping and concurrency experiments did not establish a fix and were discarded.
Stable LibreOffice 24.2 with the correct fonts resolves that blocker; see the
final acceptance evidence below. Private replay fixtures stay outside Git.

The scratch replay uses the normal generation and review gates, with source
pictures visually inspected once. Original report passthrough is not the export
implementation. Blank and changed-input cases and every active-section preview
are separate acceptance probes. An empty native-master section now remains
included without requiring fabricated organization nodes; pricing and review
gates remain active. Hidden Office drawing round-trip caches are stripped without
decoding them; removing all 138 caches from the original preserved all 46 rendered
pages pixel-for-pixel in a controlled comparison.

Independent synthetic review additionally found and fixed two source-data leaks:
pricing redaction must address logical grid columns through merged cells and
row offsets, and page-number fields must not exempt adjacent old client text
from header cleanup. Regressions exercise both merged-cell forms and the mixed
client-label/PAGE case. A local whole-suite checkpoint collected before the final
regressions completed with 1400 passed and 9 renderer/environment skips; exact
final-head CI is still the release gate.

The real different-contract blank-report probe also found old contact addresses
in Word extended-property title indexes. The passive reader now retains only
application/version compatibility properties, removes source-content metadata,
and tests that those private strings do not survive anywhere in output XML.
Latest replay before the TOC tagline correction was 43/46 pixel-identical:
the remaining differences were the three Cost headings on two pages and a TOC
brand variant incorrectly replaced with the cover logo. That variant binding is
now corrected for an unchanged current brand; changed branding still updates it.

## Final stable-renderer acceptance

Head `23b91f929fe87736d526948f89a6ba6cc30b58c9` passed Actions
`37926730104`: 1415 tests, zero skips. The subsequent preview correction at
`c69e772e31086788dfb6a9bf8cc6f7662e984393` also passed CI. The current runtime
and merged-table changes require a new full CI run and production-image check.

Stable LibreOffice 24.2.7.2, with Liberation Sans/Serif 2.1.5, TeX Gyre Heros
Condensed and OpenSymbol, renders the supplied Word reference as **45 pages**.
Two source renders match pixel-for-pixel on all 45 pages. Two generated renders
also match on all 45 pages. Source versus generated output matches exactly on
43 pages. On the other two pages, **every changed pixel is inside the three
Cost-label bounding boxes intentionally cleared by the existing pricing policy**;
there are zero changed pixels elsewhere. The merged-cell fix preserves original
table geometry when the supplied sanitized technical content explicitly matches,
while clearing cells belonging to excluded pricing columns.

Correction to the earlier checkpoint: the supplied PDF is not established as a
different content version. With the correct renderer/fonts, normalized text
matches on all 45 pages. Some text/image positions differ vertically by about
0.8 points between that supplied PDF and the source Word rendering; dimensions
match. All 45 paired pages were visually reviewed with no missing artwork,
missing content or clipping. This is not a claim of byte-identical supplied PDF.

The actual `run_web.py` AppTest Generate action produced DOCX and PDF and saved
a snapshot with no UI errors or exceptions. Inputs passed through the real
source import pipeline into a fresh draft before being supplied to AppTest
session state. This is automated application-flow coverage, not a literal browser
file-upload walkthrough. The cloud browser cannot reach the local server.
Cover plus all twelve section DOCX previews also generated successfully.

Deployment now uses Ubuntu 24.04's LibreOffice 24.2 release line with explicit
font mappings. A build-time check rejects renderer-major or font-file drift.
CI uses the same renderer/fonts, runs the full regression suite, and separately
builds the production Docker image and verifies its Streamlit health check.
The local relocated stable build cannot create the sandbox's CLI IPC pipe, so
local visual QA used LibreOffice's supported in-process Kit API. That scratch
adapter is not shipped; production and CI use the normal LibreOffice CLI.

Different-contract blank and changed-input packages are separately checked for
current identity and absence of source contacts, site names, client images and
hidden drawing caches. Empty sections need no invented facts. Final deployment
and production master installation must be recorded after CI passes.

The stable different-contract blank and changed-input exports each render as 38
pages with all twelve sections, current identity/date/address, and the supplied
current narrative, work order, photograph and caption. The real activity-preview
UI renders exactly four relevant pages in its iframe with zero exceptions.
The stronger whole-package audit caught old client text in an image description;
source DrawingML/VML descriptions, titles and nonvisual names are now cleared
before reuse, preserving frame geometry and IDs. The regression covers body,
header and VML metadata; the native suite passes 34 tests. Final regenerated
privacy and fidelity outputs are checked after this metadata-only change.

The first production-image CI job on head
`c283ac5c50bb3870c938738bd43ddd19131657c5` passed both Docker build and application
health checks (run `37934261469`). A final run covers the metadata cleanup too.
