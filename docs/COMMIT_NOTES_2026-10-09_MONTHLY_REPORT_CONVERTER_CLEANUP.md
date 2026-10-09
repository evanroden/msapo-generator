---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 63dc18ace500f680811db6c9979cf17b13d6a771
status: implementation_under_validation
---

# Writer conversion lifetime and output publication

## Findings and scope

CR-render-6: Writer's subprocess timeout killed the launcher but left its child
running after the shared conversion lease was released. A late PDF could then
appear after the caller's cleanup. The same failure path could return a stale
same-name PDF; a file with a PDF extension but non-PDF bytes was also accepted.

This change is scoped to the shared Writer path, including Monthly report and
the existing MSAPO caller. It does not change purchase-order routing, expense
policy, render geometry, fonts, image quality or source-document content.

## Implementation

The new office-process helper starts a dedicated process group, terminates its
descendants even if the launcher exits first, waits for termination, and captures
only bounded diagnostic text. Exceptions and cancellation use the same cleanup.
Linux zombies do not hold the lease: they cannot run code, consume image memory
or write output. Unrelated process groups are never signaled.

Cleanup has a five-second wait budget. If a killed process remains active, its
small transient marker remains under the existing shared render-jobs directory.
Every conversion lease checks the marker before admitting new office work, even
from another Python process. Once the old group exits, the guard clears itself.
A changed boot/PID namespace clears an obsolete marker; invalid metadata fails
closed. No operator/business record is written or migrated.

Writer renders into a private temporary directory, separate from shared output
names. A complete PDF-signature-checked result is atomically linked to a unique
output name without overwriting an existing file. Same-named uploads from two
visitors return independent current results. Failure removes this job's
partial/HTML output, not another job's existing result. Normal timeout cleanup
stops the process tree before discarding the temporary profile. If cleanup cannot
finish, no shared PDF is published and the marker blocks further conversions.
Monthly report retains its completed editable DOCX and reports the PDF timeout.

## Regression evidence

The initial five tests ran against the unmodified relevant baseline modules:
four assertions failed (Writer orphan, Calc orphan, stale PDF, invalid output),
and the real normal Writer conversion passed. Calc's adjacent launch path is
not changed here and its reproduction remains private follow-up evidence, not a
passing claim. The public tests cover Writer orphan/late-output cleanup, current
output preservation, invalid output rejection, actual LibreOffice success and
timeout, bounded diagnostics, a stalled-cleanup guard and cross-process guard
visibility, unrelated-process survival, and completed-DOCX fallback.

The existing isolated-profile test now intercepts the process helper rather than
subprocess.run and writes into the actual private output directory. Its profile
isolation/headless assertions remain; actual process-tree tests are not mocked
at the cleanup boundary. Existing native-reflow render tests now place output in
their own temporary directory instead of leaving fixed-name PDFs in shared
output. Exact run counts belong in the PR and JUnit evidence.

Local Python 3.12 and dependencies are restored from the production image and
requirements-dev.lock; Streamlit remains 1.61.1. The local source archive predates
contact/training PRs #94/#95; affected module blob hashes are checked against main.
Local full-suite results are not mislabeled exact-current-main results. Local
LibreOffice 25.2 is not production 24.2 or authored-PDF parity evidence. Required
PR gates remain the full locked suite with production fonts, container health,
and the inherited 512 MB / 0.5-CPU synthetic resource probe.

## Limits and rollback

The independent Calc launcher and advanced Word-page worker do not yet share
this helper. Calc timeout cleanup is still open. No changes to Gotenberg or
Windows/docx2pdf behavior are claimed verified; production and CI are Linux.
This does not close the privacy/content review, large-upload memory use, cover,
thermal/default reuse, or all concurrent-user resource issues.

Rollback is a code revert. Do not delete business records or terminate a process
identified only by a generic soffice name. Preserve a live cleanup marker until
its recorded group exits; a normal application restart after the group is gone
needs no data migration.
