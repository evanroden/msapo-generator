---
document_type: implementation_checkpoint
date: 2026-10-10
base_commit: 715bf2a4715fc034a05a2f440965acd1c03ec0c7
workflow: monthly_report
change_type: usability_guardrail
status: candidate_pending_exact_ci
---

# Soft review before an empty monthly report is generated

The owner's October 9 novice review confirmed that an asset manager could
skip all twelve sections and immediately export a report skeleton, mistaking
a successful download for a client-ready report. A report with no monthly work
may still legitimately be needed as a draft. This change makes that choice
visible rather than inventing mandatory content or another inclusion checklist.

At Review & download, a quiet informational line reports how many selected
section editors contain substantive non-stock monthly input. The count is
explicitly **not a completion or quality score**: approved standing chart,
contact, branding or thermal data can be present without a new monthly entry.
The count ignores empty table schemas, stock text and shared library defaults.
An imported/edited monthly section with current text, populated rows, pictures
or events counts as present; untouched source furniture never counts.

If there are **zero** monthly sections with input, clicking Generate first
shows a short warning about a mostly empty draft and a separate "Generate
anyway" action. This is a *soft* editorial check. It neither fabricates
zero activity nor blocks a deliberate draft skeleton. If at least one monthly
section contains input, the existing single-click Generate path remains.
One-section reports receive a neutral warning to check other sections but
no additional confirmation step.

The pending empty-report request is tied to the exact report fingerprint.
Editing content before confirming invalidates it; no old confirmation survives
a different draft or reporting month. The existing preflight, proposal-price
protection, client page/picture review, current-warning acknowledgment and
concurrent-save conflict gates are still mandatory. Generate anyway never
bypasses them. The same generation/save/export function is used after either
valid path; no duplicate output implementation is introduced.

Synthetic unit and real Streamlit AppTest controls verify the current-month
count, empty-report first-click result, explicit Generate anyway, single-click
populated report, invalidation after edits, and non-bypass of blocking
preflight checks. Exact full-suite and production renderer/container/resource
checks belong to the final PR, not earlier release test counts.

This is a focused P4 remedy, **not** the complete final-review redesign or
a determination that any particular section is required by contract.
It does not implement auto-retention through Render restarts, source
classifications, progress truth from real finished reports, or site-picker
click acknowledgment. Do not describe a sparse generated file as client-ready.

There are no stored-schema changes, data migration or deletion, new sources,
shared asset writes, or changes to immutable design pins. Roll back code
without touching historical monthly reports or standing contract data.
