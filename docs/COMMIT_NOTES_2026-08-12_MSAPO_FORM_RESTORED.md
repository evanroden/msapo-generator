---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
base_commit: d89661f64473448db484796ad62aad8d8938f505
date: 2026-08-12
workflow: purchase_order
change_type: business_policy_reversal
status: shipped
policy_source: contract administration, relayed by the product owner
supersedes_documents:
  - docs/PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md (attachment format only)
  - docs/STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md (attachment format only)
---

# Commit notes: the MSAPO form is the PO attachment again

## 1. LLM quick context

Contract administration asked for the **full MSAPO agreement form rendered to
PDF** as the second purchase-order attachment, replacing the simplified
Scope/Inclusions/Exclusions sheet introduced on 2026-08-06.

This is a **business-policy reversal, not a bug fix**. Two earlier handoff
documents stated the opposite as a hard rule, and a test actively guarded
against the MSAPO form returning. Both have been updated deliberately rather
than worked around.

**Only the attachment's format changed.** Routing, Object Account, Agreement
Type, amounts, assets, requester behavior, the two-file package, the Smartsheet
handoff, and the no-email rule are all untouched.

### 1.1 Invariants

1. The second PO attachment is the MSAPO form PDF, produced from
   `templates/Master_MSAPO_Template.docx`.
2. The document must carry the operator's **reviewed** scope, never
   `analysis.scope_of_work` directly.
3. The package is still exactly two files: unchanged original quote + one PDF.
4. Rendering must leave no intermediate files behind.

## 2. What changed

### 2.1 New builder — `app.document_generator.build_msapo_pdf`

Fills the real MSAPO template, converts it, returns **bytes**, and deletes both
intermediates. Returning bytes was deliberate: the caller's session-state key
(`scope_pdf_bytes`), the attachment assembly in `app/po_context.py`, and the
signature/staleness checks are all **unchanged**. Only the origin of the bytes
differs, which keeps the blast radius of a policy reversal to one function.

### 2.2 The reviewed-scope trap

`generate_docx` reads `analysis.scope_of_work`. The UI holds the operator's
edited text in a separate variable, so passing the analysis object straight
through would have silently discarded every edit made in the Scope of Work box
— on the exact document the administrator acts on.

`build_msapo_pdf` therefore takes `scope` explicitly and injects it with
`dataclasses.replace(analysis, scope_of_work=scope)`. A test pins this by
asserting the raw analysis text is **absent** from the rendered document.

### 2.3 Renaming

The generated file is now named `… MSAPO.pdf` rather than `… Scope.pdf`, in
both `po_context._document_basename` and `smartsheet.download_names`. The stem
regex in `download_names` already tolerated either word, so a base string built
before this change still normalizes correctly.

### 2.4 A test that encoded the old policy

`tests/test_smartsheet_handoff_entrypoint.py` asserted
`"generate_msapo" not in source` — a guard written to stop the MSAPO form
coming back. Left alone it would have failed the very requirement it now has to
protect. It is inverted, with a comment recording why.

## 3. New production dependency — read before trimming the image

> **Follow-up:** this dependency produced two production defects within hours,
> both fixed in `COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md`: the
> generate button had no progress indicator (an instant in-memory render became a
> multi-second subprocess), and `_convert_libreoffice` shared one LibreOffice
> user profile across conversions, which fails under concurrency and stays broken
> after any interrupted run. Read that document alongside this one before
> touching the render path.

The former scope PDF was built in-memory with PyMuPDF: no external process, and
it could not fail for environmental reasons.

The MSAPO form is a `.docx` rendered by **LibreOffice Writer**. The purchase-order
workflow therefore now depends on `libreoffice-writer` at runtime, where
previously only the expense workflow did. The Dockerfile already installs it and
`tests/test_expense_deployment.py` already asserts its presence — that assertion
now protects **both** workflows, so do not relax it.

Failure mode if it is ever missing: generation raises `PDFConversionError`, the
UI shows "PDF generation failed: …", and the operator gets no files. The
attachment set is never populated with a non-PDF payload —
`build_msapo_pdf` verifies the `%PDF-` magic before returning, so a renderer
that "succeeds" without producing a real PDF is caught at the source rather than
failing later inside Smartsheet validation.

## 4. What was NOT done

- `app/scope_pdf.py` was **kept**, along with `tests/test_scope_pdf.py`. The
  module is now unused by the workflow. It is deliberately not deleted: this is
  the second reversal of this decision, and the cost of keeping a small, tested,
  self-contained module is far lower than the cost of rebuilding it if contract
  administration changes direction again. Do not wire it back in without a
  documented instruction.
- The DOCX is **not** attached, only the PDF — and this is **settled, not an
  open question**. Confirmed with the product owner on 2026-08-12: *"the PDF
  itself is fine. The editing portion is happening earlier in the process, since
  the scope of work, inclusions, and exclusions in the website are all
  editable."*

  Do not add the `.docx` attachment as a convenience. The editing surface is the
  web UI, deliberately: the operator reviews and edits scope, inclusions and
  exclusions there, and the PDF is the frozen record of what they approved.
  Shipping an editable copy alongside it would create a second, divergent source
  of truth for a document the administrator acts on.

  This is also precisely why §2.2 matters. Because editing happens upstream and
  the PDF is the only artifact that travels, a PDF rendered from
  `analysis.scope_of_work` instead of the reviewed text would silently discard
  the entire review step -- the one the whole workflow is built around.

## 5. Verification

- The rendered DOCX was inspected directly: MSAPO template preserved, reviewed
  scope present, raw analysis scope absent, inclusions/exclusions/vendor/facility
  all present.
- Full suite green apart from two cases requiring LibreOffice, which the review
  sandbox lacks (`libreoffice-writer` and `libreoffice-calc` are absent there;
  the Dockerfile and CI runners have both).
- `tests/test_msapo_pdf.py` covers the reviewed-scope property and the
  invalid-PDF guard everywhere, and adds an end-to-end render that **skips
  itself** when the renderer is genuinely unavailable rather than reporting a
  failure the code did not cause. That end-to-end case runs on CI.
