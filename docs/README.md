---
document_type: documentation_index
repository: evanroden/msapo-generator
maintained: manually, pinned by tests/test_docs_index.py
---

# Documentation index

Eighteen-plus documents accumulate quickly and none of them announce which is
still true. This index exists so an agent arriving with no conversation history
knows what to read, in what order, and which documents have been overtaken.

**`tests/test_docs_index.py` fails if a file in `docs/` is missing from this
index.** Adding a document means adding a row here in the same commit.

## 1. Read these first, in this order

| # | Document | Why |
|---|---|---|
| 1 | [`../README.md`](../README.md) | What the application does today, both workflows, the classification matrix, and the project structure. |
| 2 | [`STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md) | Authoritative business policy for the purchase-order workflow. **Its attachment-format section is superseded** — see §2. |
| 3 | [`COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md`](COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md) | The one policy reversal that invalidates parts of older documents. Read it before trusting anything about PO attachments. |
| 4 | [`EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md`](EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md) | The second workflow end to end: form mapping, receipt controls, AI boundary, open policy questions. |
| 5 | [`FAILURE_MODES_AND_CONTROLS.md`](FAILURE_MODES_AND_CONTROLS.md) | The standing failure matrix. Consult before adding a control, so you do not re-derive one that exists. |

Only after those does the change history below become useful.

## 2. Superseding order — what overrides what

Later documents do **not** replace earlier ones wholesale. Each records only
what it changed. Where two disagree, the later date wins, but only on the narrow
subject named here.

```
PO attachment format
  PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06   (quote + MSAPO DOCX)
    -> STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08    (quote + scope PDF)
      -> COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED     (quote + MSAPO form PDF)  <-- CURRENT

PO routing / Object Account / Agreement Type
  STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08         (the matrix itself, UNCHANGED)
    -> COMMIT_NOTES_2026-08-13_ASSET_AND_ROUTING_ACCURACY (which route gets picked, and
                                                           whether the operator sees it)
      -> COMMIT_NOTES_2026-08-14_SCOPE_REGION_ROUTING      (what the rules READ -- scope
                                                           only, not the vendor's terms)
        -> COMMIT_NOTES_2026-08-17_REVIEW_FINDINGS_REMEDIATION
                                                          (mixed-scope signals, explicit
                                                           unresolved choices, reviewed
                                                           artifact values)

Expense workflow
  EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11              (form mapping and controls)
    -> COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF (email/attachment handoff)
      -> COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE_AND_NEEDS_YOU_HIGHLIGHT (step-2 UI only;
                                                           no field or mapping changed)
```

The two superseded documents carry a `PARTIALLY REVERSED 2026-08-12` banner at
the top. Nothing else in either is invalidated.

## 3. Commit notes — newest first

Each is written for an agent picking up cold: cause, fix, what was verified,
what was **not** verified, and what was deliberately left alone.

| Date | Document | PR | Subject |
|---|---|---|---|
| 2026-08-17 | [`COMMIT_NOTES_2026-08-17_REVIEW_FINDINGS_REMEDIATION.md`](COMMIT_NOTES_2026-08-17_REVIEW_FINDINGS_REMEDIATION.md) | — | Cross-cutting remediation of the two-week review: routing and facility accuracy, reviewed MSAPO values, bounded OCR inputs, approver identity migration, mileage rounding, live needs placement, handoff warnings, and locked deployments. Authentication/rate limiting explicitly deferred. |
| 2026-08-14 | [`CODE_REVIEW_FINDINGS_2026-08-14.md`](CODE_REVIEW_FINDINGS_2026-08-14.md) | #48 | Line-by-line review and annotation pass. 23 bugs, 21 dead-code candidates, 16 duplications — **all unactioned**. Records which 12 modules were NOT reviewed. |
| 2026-08-14 | [`COMMIT_NOTES_2026-08-14_SCOPE_REGION_ROUTING.md`](COMMIT_NOTES_2026-08-14_SCOPE_REGION_ROUTING.md) | #48 | Routing was classifying the vendor's terms and conditions — 92% of a real quote's text — instead of the scope. Closes the open question left by the 2026-08-13 notes. |
| 2026-08-13 | [`COMMIT_NOTES_2026-08-13_ASSET_AND_ROUTING_ACCURACY.md`](COMMIT_NOTES_2026-08-13_ASSET_AND_ROUTING_ACCURACY.md) | #46 | Lowest-numbered asset resolution; three separate causes of Object Account / Agreement Type always reading Subcontractor/MSAPO. |
| 2026-08-13 | [`COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE_AND_NEEDS_YOU_HIGHLIGHT.md`](COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE_AND_NEEDS_YOU_HIGHLIGHT.md) | #45 | Expense step 2 collapsed behind one line; unfilled required fields highlighted in both workflows. Includes two reverted attempts and why they failed. |
| 2026-08-12 | [`COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md`](COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md) | #43, #44 | iPad double-tap to focus a field; the generate button appearing to do nothing; LibreOffice profile contention; CI never exercising the renderers. |
| 2026-08-12 | [`COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md`](COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md) | — | Business-policy reversal: the PO attachment is the full MSAPO form rendered to PDF again. |
| 2026-08-12 | [`COMMIT_NOTES_2026-08-12_CORRECTNESS_AND_FAILURE_MODE_HARDENING.md`](COMMIT_NOTES_2026-08-12_CORRECTNESS_AND_FAILURE_MODE_HARDENING.md) | #40 | Cross-cutting: assumption-section inversion, vision payload bounds, transparency turning receipts black, device identity, and more. |
| 2026-08-11 | [`COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md`](COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md) | — | The attached Outlook/iOS expense-email handoff: architecture, invariants, failure matrix, test evidence. |

## 4. Standing reference

Not tied to one change; expected to stay true.

| Document | Contents |
|---|---|
| [`FAILURE_MODES_AND_CONTROLS.md`](FAILURE_MODES_AND_CONTROLS.md) | The failure matrix for both workflows and the Smartsheet handoff, with the control that answers each. |
| [`STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md) | Authoritative PO business policy. Attachment-format section superseded; the routing matrix is not. |
| [`EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md`](EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md) | Expense form mapping, receipt controls, AI boundary, failure modes, open policy questions. |
| [`JOB_NUMBER_CATALOG_AND_UNITY_DISAMBIGUATION_2026-08-10.md`](JOB_NUMBER_CATALOG_AND_UNITY_DISAMBIGUATION_2026-08-10.md) | The verified 87-value job catalog and the Arkansas-versus-RRH Unity rule. |
| [`RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md`](RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md) | The three-step UI, brand-aligned theme, browser matrix, release hardening. |
| [`LINK_PREVIEW_METADATA_2026-08-11.md`](LINK_PREVIEW_METADATA_2026-08-11.md) | Page title, favicon, Open Graph/Twitter card, the build-time patch, and the production verification contract. |

## 5. Historical — read for reasoning, not for current behaviour

These record decisions that were made, and in several cases later changed. They
are kept because the *reasoning* still matters; the described behaviour may not
be live.

| Document | Status |
|---|---|
| [`PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md`](PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md) | Attachment format twice superseded (see §2). Policy reasoning still valid. |
| [`SMARTSHEET_PO_IMPLEMENTATION_HANDOFF_2026-08-04.md`](SMARTSHEET_PO_IMPLEMENTATION_HANDOFF_2026-08-04.md) | The API integration it describes is scaffolded and **off by default**; no API access was granted. |
| [`SMARTSHEET_CUSTOM_URL_PREFILL_HANDOFF_2026-08-06.md`](SMARTSHEET_CUSTOM_URL_PREFILL_HANDOFF_2026-08-06.md) | Prefill route as shipped, plus the manual fallback that assumes prefill may never be enabled. |
| [`RRH_STREAMLINING_AND_HARDENING_2026-08-08.md`](RRH_STREAMLINING_AND_HARDENING_2026-08-08.md) | Earlier quick-path reliability history. |
| [`CORRECTIONS_TO_2026_07_27_WORKFLOW_CHANGES_2026-08-10.md`](CORRECTIONS_TO_2026_07_27_WORKFLOW_CHANGES_2026-08-10.md) | The C1–C8 correction list. C2 and C3d were later found incomplete — see the 2026-08-12 hardening notes. |
| [`PUBLIC_REPOSITORY_AND_RELEASE_AUDIT_2026-08-11.md`](PUBLIC_REPOSITORY_AND_RELEASE_AUDIT_2026-08-11.md) | Point-in-time audit of what the public repository exposes. |
| [`ENFRA_IT_AI_API_REVIEW_EMAIL_2026-08-11.md`](ENFRA_IT_AI_API_REVIEW_EMAIL_2026-08-11.md) | A drafted email, not a specification. Its AI call-path summary was accurate when written. |

## 6. Conventions these notes follow

Worth matching when you add one.

- **YAML front matter** carrying `document_type`, `base_commit`, the
  implementation commit SHAs and subjects, `workflow`, `change_type`, `status`,
  and where known the merge commit and CI run. This is what makes a document
  locatable from a `git log` line and vice versa.
- **§1 "LLM quick context"** — the complaint or requirement in the reporter's own
  words, then the invariants the change must not break.
- **A "what was NOT verified" section.** Absent evidence is stated, not implied.
  Coverage that was skipped, environments unavailable, and questions left open
  belong here rather than being quietly omitted.
- **A "deliberately unchanged" section**, so the next agent does not undo a
  conservative choice thinking it was an oversight.
- **Reverted attempts are kept**, with the reason they failed. Several of this
  project's live behaviours exist because an earlier approach broke something a
  test caught; deleting that record invites the same attempt again.
- **Merge commits, not squash.** Per-fix reasoning stays reachable from history.
