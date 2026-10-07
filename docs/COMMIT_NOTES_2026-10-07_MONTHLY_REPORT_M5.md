---
document_type: implementation_notes
date: 2026-10-07
base_commit: 99cdd2a688bae623d171bbba53a64ee6e59c8139
workflow: Monthly report
change_type: evidence_drafting
status: in_progress
---

# Evidence-linked monthly drafting checkpoint

This is an unfinished M5 increment on draft PR #61. Do not merge or describe it
as deployed until its remaining review/carry-forward work and validation finish.

The implementation uses compact page-cited facts, strict JSON, exact supporting
quotes and bounded source text. Native extraction caches include source SHA and
selected-page contents. Draft requests reuse compact facts rather than repeatedly
sending raw documents. Existing network-only receipt jobs reserve capacity before
caller-thread preparation. OCR pages share the existing 20-image review allowance.
Runtime caches and original pasted notes stay below monthly_reports/.

Suggested paragraphs cite real fact IDs and source pages, reject prices, flag
unsupported numbers, unknown tags, mismatched sites/months and uncertainty, and
require review. The Copilot prompt fills every placeholder and now prohibits
prices according to the owner's latest rule. The parser retains unmatched lines
for correction and tolerates missing sections, chatter and mixed bullets.

Current UI supports explicit reading, checking facts, suggested wording and
append/replace comparison. Originals and existing pictures/tables remain intact.
This is still being hardened for stale evidence, old unreviewed paragraphs and
returning sessions. Issue resolution/carry-forward and complete acceptance tests
remain. No paid model calls or private data were used by automated tests.

Initial validation: nine synthetic backend tests and a 29-test focused existing
UI/source run passed. New AppTest coverage and the complete local/remote suite
are still being completed. PR #63 and #64 releases are recorded separately in
MONTHLY_REPORT_PROGRESS.md; their green CI does not validate this M5 code.
