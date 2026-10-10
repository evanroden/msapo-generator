---
document_type: implementation_checkpoint
date: 2026-10-09
workflow: monthly_report
change_type: defect_fix
base_commit: 5c67d5f1ce3087d284a0fd245497367f466fd747
status: candidate_pending_ci
---

# Current improvement photos: preserve aspect ratio after replacement

## Owner finding and reproduced cause

The October 9 usability audit reports that a 1400 x 900 current progress illustration
kept its source pixels but rendered at a 4:3 physical frame (approximately 16.7%
vertical stretching). It also reports a flattened contents-page client logo;
that is a **separate unclosed** problem, not resolved by this change.

A new synthetic source report with an old 600 x 450 picture frame and a new
1400 x 900 current photo reproduces the problem against the merged F16 baseline.
Both a DOCX physical-geometry test and a real LibreOffice PDF-ratio test failed
before this code change. This is actual application assembly, not a copied-helper
experiment. The report's old native frame was being relinked to the new asset
without recomputing the 4:3 size or clearing its old crop.

## Scoped repair

Replacement of an **improvement** picture now uses contain-fit into the
existing native frame: compute the new physical width and height from the
current bitmap's dimensions, never exceed the original picture envelope, and
remove the previous image's DrawingML/VML source crop. Current DrawingML inline
and anchored picture frames are handled. Simple ungrouped VML images with
explicit inch/point sizes are handled, including height-before-width styles.
Grouped/ambiguous VML geometry produces a specific safe error rather than
silently stretching a picture or fabricating a layout approval.

Measurement reads the bitmap header and EXIF orientation without rotating or
decoding a second full in-memory image. Previously approved *unchanged* source
pictures still bypass replacement entirely. The intentional cover-photo crop,
original ENFRA design canvas, contracts, monthly state, picture review gate,
other blocks, and conversion locks are unchanged. The new helper is selected
only for current `improvements` replacements. Other branded/technical images
are not silently forced into this fit mode.

## Verification

The two original synthetic regressions first failed against the unmodified
F16 output. The repaired code passes unit and real-render tests for current
source/replacement dimensions, crop removal, output package media retention,
source-original immutability, VML width/height ordering and unmeasurable-frame
rejection. The surrounding native-layout regression suite is run unchanged.

Exact final suite and CI/container/resource metrics belong in the PR. Reference
source documents stay in private QA storage. Synthetic evidence only is eligible
for public tests; no customer assets, personal contacts or font binaries are
included. This is same-renderer proportional-placement evidence, not a full
Adobe-authored ENFRA reference-PDF parity claim.

## Remaining limits and rollback

The flattened **contents-page client logo**, deliberately photo-cropped cover,
photographs whose placement needs a different `photos_per_page` composition,
complex grouped VML, genuine Word compatibility, and broader final-report visual
fidelity remain separate acceptance paths. The active-work recovery, Activity
upload failure and site-picker feedback are also unchanged.

Rollback is code-only; keep saved reports, source originals, standing data,
picture approvals, design pins and history intact. A push or green CI result is
not a public deployment verification; verify the public app separately.
