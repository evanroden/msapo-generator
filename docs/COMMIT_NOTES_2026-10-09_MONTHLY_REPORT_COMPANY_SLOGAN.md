---
document_type: implementation_checkpoint
date: 2026-10-09
workflow: monthly_report
change_type: scoped_native_branding_fidelity
base_commit: 5aa0562f0bb42082adc9cba9d1f52e66ed4a4858
status: candidate_pending_exact_ci
---

# Contents-page ENFRA slogan is not a client's logo

## Verified failure and separate issue boundary

The owner's F13 feedback identifies a client logo flattened over the lower-right
contents-page artwork. With a current replacement client-logo bitmap and a fresh
report based on the supplied Unity/USH Word master, the prior native assembler
replaced the separate ENFRA `Create. Sustain. Empower.` company wordmark with
that client image. The source wordmark lives in a very narrow physical frame;
a replacement client logo is therefore visibly squeezed. A real generated
LibreOffice PDF reproduced the problem.

Original UMMC, Unity/USH and Portland Word reference reports independently
contain the same identified ENFRA wordmark, in two slight pixel variants.
These were reviewed privately. The public repository contains only bounded
normalized image fingerprints and source-image size, **not** their artwork or
customer records. The reference Word/PDF files and their original hashes are
unchanged and remain private.

## Narrow fix

The one recognized, historically corroborated company wordmark is treated as
approved static corporate page furniture, not a candidate for the current
client-logo, ENFRA logo or cover-photo roles. User-reviewed explicit current
bindings continue to have priority. Other unbound source images retain their
existing rejection and replacement behavior; no broad ratio-based approval
was added.

Artwork identity is verified by dimensions and SHA-256 of normalized RGBA
pixels from a bounded, valid original DOCX media part. The role cannot be
authorized by naming a file or mimicking its narrow aspect ratio. Malformed,
unknown, oversized or corrupt media cannot acquire this exception. Decoding
is bounded to at most 64 KiB of source image bytes and exactly 409 by 37 pixels;
results are cached by source identity. No external image fetching is required.

Only the disposable generated report copy changes. Native picture geometry,
company logo source bytes, other cover crops, design pins, shared logo state,
report/asset history and source files are unchanged. This is not a replacement
for the general semantic role-binding system for arbitrary source pictures.

## Reproduced before/after evidence and tests

The original source-based two-page contents layout was rendered with a clearly
synthetic replacement client logo. Before this correction, the lower-right
picture was the compressed current client image. Afterward it is the verified
corporate wordmark from the installed design; the legitimate client logo in its
own header slot remains. On the checked page, changed pixels were confined to
the prior squeezed-logo region (approximately x466–600, y667–679 in the
controlled page raster); all other page pixels remained unchanged. Source
DOCX bytes and original PDF references were not modified.

Public synthetic tests independently exercise normalized-pixel identity,
source-part path constraints, unknown artwork rejection, and a full native
master/client-logo replacement with the correct original company frame retained.
The tests **temporarily mock** an allowed pixel fingerprint only for their
synthetic fixture; they do not add fake approved content to production.
Actual private source Word/PDF picture inspection supplies the real business
identity evidence. Existing cover/branding and native-layout regressions must
stay green. The exact final-head full-suite/container/512 MB resource results
belong in the PR; the local targeted run passed 82 tests.

## Limits and rollback

This repairs only the independently identified contents-page corporate wordmark
misclassification. It does not establish perfect contents-page confidentiality
bar alignment, current client-logo fit at other positions, cover typography,
photo-per-page density, authenticated PDF fidelity across every design, or
Microsoft Word native opening. Unknown images must not be approved simply
because they look like corporate branding. These are separate findings.

No storage migration or destructive write. Rollback is code-only; retain saved
reports, uploaded originals, site contacts, company branding store, standing
thermal data, immutable design pins and historical reviews. Public deployment
must be verified separately from merge and CI status.
