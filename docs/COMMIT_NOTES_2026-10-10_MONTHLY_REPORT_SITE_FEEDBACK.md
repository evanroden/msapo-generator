---
document_type: implementation_checkpoint
date: 2026-10-10
base_commit: 35ac8bd025158709e9f0306480ef956a02c66034
workflow: monthly_report
change_type: interaction_feedback_and_bounded_ui_cache
status: candidate_pending_ci_and_manual_pointer_verification
---

# Site selection feedback and report-start responsiveness

The October 9 novice test reported site checkboxes and the Start button
appearing to ignore clicks, sometimes requiring repeated attempts while a
0.5 CPU / 512 MiB Render instance was under load. This is a user-observed
symptom, **not** a reproduced universal pointer/touch input defect. The
previous test was made through cloud-browser automation, which can have
different pointer and keyboard event timing.

The selected site count and exact names now appear directly after the
checkboxes, updating on every normal Streamlit rerun. Each site's checkbox
has consistent, specific help text including aliases if known; native
checkbox labels and focus behavior remain unchanged.

Starting a new report displays an immediate server-side preparation spinner.
A session-scoped pending latch prevents a duplicate Start while the current
request is processing. Failed starts leave the form enabled for retry and
do not claim that the report was created. Existing validated account/site
membership, one starting-report upload, design version and optimistic
library checks are unchanged.

Logo cards are expensive for a contract grid: each rerun previously decoded
and re-encoded a 480 x 192 PNG canvas for each displayed client image.
The pure **screen-only canvas** operation is now cached by its exact source
bytes with a maximum of 32 cached entries. This does not cache original
image verification, change asset identities, or modify the native report's
printed brand assets. The cap limits its memory footprint on Render, while
avoiding repetitive resizing on the UI thread.

Automated synthetic Streamlit AppTest checks verify selected-site feedback
on check/uncheck and rerun, Start's spinner and single resulting profile,
failed Start retry behavior, and content-keyed bounded canvas caching.
These are not a replacement for the owner's real iPad/mouse pointer test:
P2/P12 remains open until checkbox-square, full-label, touch, and keyboard
input are exercised on the deployed commit.

No access control is inferred from the operator name or browser cookie.
No private contacts, logos, report images or stored data appear in the
public tests. No report source files, history, design pins or thermal data
are modified. No new validation or review gate is added.

Exact-head GitHub CI must run the full pinned pytest suite, production
LibreOffice/font checks, container health, and 512 MiB / 0.5 CPU synthetic
resource test before merging. A passing AppTest is not live browser evidence.
Rollback is code-only.
