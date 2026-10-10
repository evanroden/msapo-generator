---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 309eae5b0189d2aa6bb7f6ec873b4579efa6016e
workflow: monthly_report
change_type: source_geometry_fidelity
status: candidate_pending_exact_ci
---

# Section 10: complete the authentic two-digit divider number

## Reproduced finding (F12)

In the original owner-supplied Unity/USH Word file, the proposals divider's
numeral is `10` in both OOXML Choice and Fallback. The 40-page Adobe-authored
source PDF visibly prints **10** on page 31. An independent section export with
LibreOffice 24.2.7.2 instead printed only **1**: the zero wrapped outside the
visible native textbox. This is real visible document content loss, not a
failed text-search heuristic. The private source DOCX and authenticated PDF
are never committed or modified.

The typography is 210 pt bold text with -20 pt character spacing in a 202.7 pt
text box. Its last negative tracking is handled differently by Writer and
LibreOffice, so the two-digit glyph extent is effectively wider than the frame.
In an isolated source-copy render, increasing only the verified frame width
by 20 pt recovers both digits and matches the authored reference's horizontal
PDF text bounds to 0.33 pt, but the visible glyph placement is still wrong.
The paired local correction also shifts the anchor down by 5 pt. Under the same
stable converter this moves the visible glyph's top to within 1 pt of the
Adobe-authored position; the bottom differs by approximately 4 pt. It does
not pretend to fix the separate divider title color/shadow/font metrics.

## Repair boundaries

Only a **single** recognized proposals-divider numeral whose Choice/Fallback
text, original shape dimensions, 210 pt glyph size, -20 pt tracking and
page-anchor position all match the proven source metrics is corrected. Both
Word-compatible representations receive the same width and vertical correction.
A malformed, missing, ambiguous, repeated or differently designed frame
remains unchanged. This is deliberately not a global line-spacing, font-size,
shape-width or report-layout change. It does not rewrite ordinary occurrences
of `10`, headers, other sections or the original asset.

The correction is applied to the in-memory native DOCX **after** current content
and page accounting, before passive-package publication. It does not change
immutable master objects, paired profile identities, saved drafts, approved
pictures, link destinations or existing storage schema. The output remains
an editable DOCX, not a PDF overlay or screenshot. Source reference/provenance
is preserved; no whole reference PDF page resources are imported.

## Executed proof and limits

Private before/after source-based Word/PDF documents were generated. Baseline
visible PDF contained a single `1` with no `10` text span; the corrected PDF
contained `10` as one unbroken numeral. The changed rendered pixels were
confined to the numeral region: zero changes outside a bounded 275 x 280 pt
area on that page. Original image, native title and background did not change.
The source DOCX hash remained identical. UMMC and Portland proposals previews
were separately exported from their authentic source Word files; the corrected
version had all 16 DOCX ZIP members byte-identical to the prior version for
each case, demonstrating conservative no-match behavior.

A synthetic, non-customer Word fixture tests Choice and Fallback metrics,
idempotence, section scoping, ambiguity and malformed-format rejection,
ordinary text preservation and a real converted one-page PDF. No original
Word template image, customer text, report, font file or private QA output is
committed to this public repository. The exact-head full suite, production
font validation, container health and 512 MB/0.5 CPU probe remain required
prior to merge; record their actual numbers in the PR.

The authored Unity/USH PDF uses Adobe PDFMaker and native Arial, while local
LibreOffice uses configured compatible metrics; this is a measured correction
for the verified source design, **not** a claim that all ten reports' dividers
or their title shadows match. The displayed title's black/white rendering,
remaining cover issues and the earlier Eastern RFI/pagination investigation
remain separate. Full Word application and full authentic-report replay are
still needed for broad fidelity acceptance.

Rollback is code-only; do not delete report snapshots, sources, contracts,
training records, logos, approvals or thermal-capacity data.
