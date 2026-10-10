---
document_type: implementation_checkpoint
date: 2026-10-10
base_commit: 675cf5df122035156e1af73de4a65ab5fe0eeff3
workflow: monthly_report
change_type: usability_guardrail
status: candidate_pending_exact_ci
---

# Generate button: visible readiness gate and request feedback

The owner's second novice review observed a bright-green Generate button
that was disabled until a specific-warning acknowledgment checkbox was checked.
Clicking the disabled button gave no feedback. This is a presentation problem
with an existing output-safety gate, not evidence that safety validation is absent.

The Review & download action now uses a muted secondary appearance while
disabled and immediately displays the actual reason next to the button:
a concurrent saved-version conflict, the number of required blocking issues,
or unacknowledged current warnings. When ready, it becomes the normal primary
action. Its single-button request displays a brief "Preparing the Word and PDF
downloads…" spinner until the result is available.

These are derived from the **same** conflict, preflight checks, and fingerprint-
scoped warning acknowledgment used by final export. No safeguard, approval,
required field, quote-price filter or conflict gate is bypassed or made optional.
When there are no warnings, no new checkbox appears and Generate is enabled
without an extra click. Editing after acknowledgment makes warnings require a
fresh check, as before.

Synthetic unit and Streamlit AppTest regressions cover required issues, warning
acknowledgment, re-disabling after an edit, and the no-warning path. The actual
Streamlit button invocation is inspected for `type=secondary` and
`disabled=True`; user-facing text is checked in the real report workspace.
The tests do not claim a browser animation/ARIA-tree inspection.

This is intentionally limited to P3. It does not satisfy the separate soft
empty-report review (P4), automatic retention/reconnect (P1), site-click
feedback (P2), or final review's full missing-content inventory (F03).
A checked warning is not a completed factual/editorial review. Progress
and readiness cannot be determined solely from page counts or clicks.

Run full locked tests and production renderer/font, container health and
512 MiB/0.5 CPU gates before merging. Verify public deployed behavior
separately. No changes to saved reports, source files, standing capacity,
contacts, uploaded photographs or immutable masters. Rollback is code-only.
