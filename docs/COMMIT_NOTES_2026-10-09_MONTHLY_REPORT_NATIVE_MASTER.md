---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: f0e7fa32a20d95a9ae7338060397d9de34fab42c
status: visual_validation_in_progress
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

Visual acceptance remains blocked. The bundled converter identifies itself as
LibreOfficeDev 26.8 alpha. Normal starting-report and fresh-master exports now
produce 46 pages; 44 pages have identical text, with only three intentional Cost
heading removals on the other two pages. Two generated DOCX archives had identical
ZIP-part contents but their converted PDFs differed substantially in divider
backgrounds. This isolates a nondeterministic converter defect; a successful
single render does not establish reliable fidelity. The default graphic cache reproduced mismatches on 20 pages of identical input.
Three isolated exports with swapping disabled were pixel-identical, but a fourth
still differed on 15 pages. Disabling swapping is therefore NOT an established
fix and cannot justify release. A stable official LibreOffice build is being
prepared for a controlled comparison against the bundled alpha.
Controlled package comparisons and both fresh-master and
starting-report replay outputs remain outside Git. Do not merge this checkpoint
or describe its output as identical until every-page comparison passes.

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

## Final acceptance checkpoint for this session

Draft head `23b91f929fe87736d526948f89a6ba6cc30b58c9` preserves the source-data
and native-binding fixes (tree `3bae0dc6bc638be639a0cae99d98a25e249e8363`).
Actions run `37926730104` was started for this exact tree. The next small change
removes the duplicate terminal Word section in active-section previews; its
native renderer suite passes 31 tests and lint is clean.

Actual `run_web.py` AppTest generation produced DOCX/PDF and saved a snapshot.
Inputs came through the real source import pipeline into a new current draft,
then were supplied to AppTest session state. This is not a literal browser file
upload walkthrough. The browser could not reach the local application server.
A separate unmocked section-preview UI run displays an iframe with exactly four
activity pages and no exceptions. Cover plus all twelve section DOCX previews
also generated successfully.

Fresh different-contract blank and changed-input Word packages pass checks for
current identity and absence of source contact emails, site names, client cover
images and hidden drawing caches. Current narrative, photo and caption placement
was visually inspected. Empty native sections require no invented facts.

Exact PDF acceptance FAILS. Best earlier paired normal exports had 43/46
pixel-identical pages and 44/46 text-identical pages before the final TOC variant
fix. A later actual UI export had only 27 pixel-identical and 31 text-identical
pages because native divider/cover content rendered inconsistently. Do not quote
the best render as a completed acceptance result. A stable official LibreOffice
24.2.7 scratch extraction could not start (UNO bootstrap exceptions); no stable
converter comparison was obtained. The speculative image-swapping change was
reverted. Production remains on PR #89, with this work held in draft PR #90.
