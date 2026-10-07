---
document_type: implementation_notes
date: 2026-10-07
workflow: Monthly report
change_type: usability_and_client_output_safety
base_commit: 29476cbc5ec0c43f2b01b19492561e44f24b6cfd
status: local_validation
---

# Monthly report: recognizable sections and client-safe pages

## Context and owner decisions

The owner could not understand the 158-item import queue or the empty identity
grid. The requested experience is report section boxes, existing content previews,
simple keep/edit/leave-out choices, and a clear path to the next monthly step.
An uploaded partial report can contain new work beneath an old cover. Preserve
it and let the operator review each section; never date all pages from the cover.

The owner also requires no prices in client reports, and no legal-only, blank or
signature-only vendor pages. This supersedes the earlier permission to include
quoted amounts. Input evidence stays intact on the runtime disk.

## Implementation

- Group import items by recognizable section; remove punctuation-only UI tasks,
  group repeated design artwork once, and retain original/unmatched content.
- Keep contents-list entries in cover design rather than treating them as report
  bodies. Recognize the short Water Treatment heading found in supplied layouts.
- Select actual contract sites, add a missing site by name, explicitly confirm
  one-site/group/region scope, and make alternate names/report title secondary.
- Keep section text, independent table schemas and images editable. Closing a
  section retains edits and its content-bound approval. Save enters monthly work.
- Strip explicitly financial columns from imported tables; retain zeros/false
  values and independent table headers. Store/render these as additive extra
  tables so a second table is not silently lost or forced into the first schema.
- Block native pricing in output text/tables and detect priced/legal/empty pages.
  Readable technical vendor pages are suggestions; visual confirmation is still
  required. Image/unreadable pages are not automatically embedded. Page review
  binds source hash, page text and caption; page preparation refuses blocked or
  unreviewed pages, and export requires confirmation for included image blocks.
- Original reports, source files and audit history remain intact. New fields
  deserialize with defaults for older saved reports. No passcode, email output,
  private Render access, or PO/expense routing changes.

## Evidence and limits

Complete local suite: 815 passed, one CI-only skip with real Writer/Calc enabled.
Synthetic regressions cover table schemas/zero values, pricing gates, unsafe page
selection, source-bound review, original preservation, mixed-month section review,
regional membership and closing/reopening edited sections. AppTest lacks native
serialization for tracked expanders in this version; the harness forwards their
actual boolean widget state alongside ordinary AppTest widget events.

All eight supplied DOCX samples parsed under existing bounds and grouped into
12–13 section cards. Three actual-report AppTest walkthroughs opened every card
and verified editing survived closing/reopening, including two large packages.
Private preview contact sheets exposed repeated graphics and tiny icons; grouping
now uses streamed image hashes, and small icons/thin separators start unchecked
with an explanation and an option to include them. Native priced tables/text
surfaced blocking messages in these real samples. Actual report generation was
not approved as client-ready; full private-data acceptance remains outstanding.

A four-page synthetic DOCX/PDF was rendered with real LibreOffice and all pages
visually inspected. Both independent table schemas, zero and false values remained;
the financial column and its amount were absent. Private originals and artifacts
stay outside git; no client content is a fixture. Focused regression, compilation,
Ruff, dependency, hygiene, docs-index and whitespace gates follow the complete
815-pass run. Final exact-head CI, merge and public deployment checks are pending.

OCR can miss pricing and does not establish that work was completed. Native Word
vector drawings can require a replacement picture; those are flagged and retained
in the original. Import rebuilds editable content and does not reproduce arbitrary
Word layouts exactly. AI drafting, Copilot, directory import integration and final
layout polish are separate unfinished increments. End-to-end client acceptance
remains the owner's task.

## Recovery and rollback

Use MONTHLY_REPORT_PROGRESS.md for exact branch/release status. Runtime manifests
remain schema 1; extraction caches add an independent page-policy version field.
Existing revision guards and immutable asset references remain in effect. Shared
and snapshot versions can be restored using existing history controls. Restoring
an older image version does not bypass client-output review. A code rollback must
not be treated as permission to distribute prices or unread evidence.
