---
document_type: usability_remediation_ledger
date: 2026-10-09
base_commit: 63dc18ace500f680811db6c9979cf17b13d6a771
status: focused_training_repair_pending_release_acceptance
---

# October 9 usability audit: implementation ledger

Follow-up: #99 merged the Training-note, revision/comment and Writer-cleanup
repairs; #100 merged contact-table header pagination. Their release records,
not the older status statements below, establish what was merged. Public
build verification remains separate. The current [narrative-flow checkpoint](COMMIT_NOTES_2026-10-09_MONTHLY_REPORT_NARRATIVE_FLOW.md)
addresses the reproduced F16 body-placement and empty-list paths, not its
unresolved original footer-change observation. Supplemental novice feedback
P1-P12 is tracked in issue #101; no automatic-retention expiry is implied.

The owner supplied a 54-page usability audit, including three real downloaded
Word/PDF pairs and bounded comparisons with an authentic authored reference.
Its observations are evidence about those runs, not universal feature passes.
The original audit and customer illustrations remain outside this public repo.
The original files are unchanged. Figure/page references below use the audit's
printed page numbers, not output-report page numbers.

This supplements the existing code-review and fidelity handoffs; it does not
replace their unfinished work. **F01-F16 below are usability-audit IDs**, distinct
from older render-review IDs. PR96 owns revision/comments and PR97 owns Writer
process cleanup. Neither is a fix for the new usability findings by association.
The separate six-commit local review-integrity patch bundle remains separate:
do not discard it, merge it wholesale, or label it deployed from this ledger.

## Current owner decisions (supersede older manual-save instructions)

Keep one scrolling report-order page, one agnostic starting upload, adjacent
automatic previews, and optional writing help. Remove the routine monthly Save
responsibility by retaining active work through ordinary refresh/reconnects.
Do not replace it with a mandatory cloud-draft library, collaboration system or
cross-device recovery project. No abandonment duration has been agreed. Do not
invent an expiry or purge existing saved reports; that policy remains a decision
before the automatic-retention implementation.

Contacts and first-fill thermal requirements are durable standing information.
Validated, unambiguous changes should write automatically to the intended
site/contract scope, not introduce a Save/remember confirmation. Preserve source
provenance, NR and historical snapshots. Conflicting authoritative values or
uncertain site matches can require a specific question. Outage diagrams and
approved logos must not require routine monthly re-entry.

Vendor/Trane reports belong in Activity; Client Services Calls is for ENFRA
onsite technicians. Never infer staffing or "not applicable" from missing input.
Training is hospital/client staff, not the provider's staff. Proposal prices are
excluded across all exported representations. Maintain native schemas, immutable
design pins, source-original safety and separate assembly/conversion leases.
Attribution is not authentication. Private Render/log access is not authorized
by the existing handoff; deployments use the existing GitHub-main release path.

## Prioritized finding ledger

| ID | Evidence and required change | State in this change |
| --- | --- | --- |
| F14 | Validation and matrix changes hid/reset Training notes; preserve sibling fields, accepted events and intentional deletions. Audit pp25-26. | Reproduced against the exact current-main tree; focused repair and regression tests below. Live audit replay still required. |
| F16 | Imported metrics collided with the utility title; empty equipment bullets and changed footer coverage followed import. Audit pp27-28. | Open. Check body placement/wrapping, not just extracted text; preserve intended furniture and meaningful breaks. |
| F12 | Native `10` rendered as `1` on the proposals divider. Audit p24, Figure 8. | Focused, source-proved two-digit geometry correction under validation (`COMMIT_NOTES_2026-10-09_MONTHLY_REPORT_DIVIDER_NUMERALS.md`); broader divider typography/shadows and genuine Microsoft Word acceptance remain open. |
| F13 | Flattened contents branding and a stretched progress image; chart sources fared better. Audit pp24-25, Figure 9. | Partial improvement-photo contain-fit repair under validation (`COMMIT_NOTES_2026-10-09_MONTHLY_REPORT_PHOTO_CONTAIN.md`); client-logo identity/size, cover crops and all photo-page designs remain open. |
| F15 | Contact header stranded after a diagram; following rows lacked repeated headings. Audit pp26-27. | Open. Exercise zero/one/many rows and wide/tall images, then inspect actual page transitions. |
| F11 | The original Activity TXT failed twice with a raw JSON/parser error; no suggestion was accepted. Audit pp22-23. | Focused native-first upload/reader recovery implemented under validation (`COMMIT_NOTES_2026-10-09_MONTHLY_REPORT_ACTIVITY_READER_RECOVERY.md`): synthetic TXT/cached/invalid/no-key AppTests pass. Public browser and real-model acceptance remain unverified. |
| F01 | Unsaved work was lost on reload; manual-save recovery did work. Audit pp8,13-14. | Open. Active-work retention and failure/ordering protection required; no TTL or history deletion in this change. |
| F02 | Maintenance upload accepted the vendor technical page under Maintenance, while Activity contained only manually typed vendor prose. Audit pp14-15. | Open. Correct the upload route, processing and final placement together, not labels alone. |
| F03 | Finish area emphasized page estimates, not remaining decisions. Audit pp15-17. | Open. Link actionable content checks to sections without recreating a mandatory inclusion checklist. |
| F04 | Long scrolling page lacked section jumps. Audit p17. | Open. Add nonblocking navigation without duplicate inputs or a Save toolbar. |
| F05 | Copilot mechanics preceded the direct editor. Audit pp18-19. | Open. Optional, compact copy/use/paste/review flow; never overwrite manual edits. |
| F06 | Collapsed contact labels lacked enough site/role context. Audit p19. | Open. Do not merge matching names. Durable contact promotion remains separate from the already-merged shared-copy refresh. |
| F07 | Empty tables showed None placeholders and generic columns. Audit p20. | Open. Intentional empty states plus native-schema fidelity; NR must remain distinct. |
| F08 | Global master updates sat inside routine monthly editing. Audit p21. | Open. Separate administration, preserve old pins; a disabled button is not a permissions test. |
| F09 | Waiting preview looked like a blank report page. Audit p21. | Open. Truthful preparing/updating/empty states; retain last good preview and stale-result rejection. |
| F10 | Cloud automation showed pointer/keyboard site-selection differences. Audit p22. | Verification needed. Not established as a universal pointer defect; test actual mouse/touch/keyboard and report identity. |

Related unnumbered checks: temporary mixed-month/author state; explicit source
month not detected; dates inside site names and explicitly future follow-ups;
CSV ingestion without accepted derived rows; lower-priority label/footer copy.
The CSV totals appearing later in imported prose are not evidence of CSV parsing.
Neither the navigation observation nor the Training observation proved deletion
of an existing saved snapshot. Preserve those qualifications.

Inherited MBCx numbered-list artifacts and contents-page omissions need a separate
design decision: they also occur in the authentic reference. Do not remove source
content merely to make a synthetic sparse report match an unrelated page count.

## Implemented slice: F14 / D16-D19

The shared-matrix try/except previously enclosed the event form and notes field.
A matrix validation/storage error therefore skipped both widgets. Event
validation also skipped the notes widget. When a note change arrived in the same
rerun, the returned report kept the earlier note instead of the incoming edit.
The event form also cleared input before validation succeeded.

Matrix errors and event errors are now separate. Notes and the event form render
on each authorized Training pass, including a rejected matrix edit. Invalid
form values remain available for correction, with explicit report-scoped widget
keys. Repeated identical valid submissions use the existing deduplication rule.
An explicit empty note is honored, not reconstructed from saved prose.

A proposed new matrix column becomes current only after its standing write
succeeds. A failed matrix read is represented as unavailable, not an empty matrix
that deletes the report's accepted table. In that case monthly events/notes can
remain editable while the prior matrix is retained. Provider filtering, selected
site checks, stale-write conflicts and matrix-reload behavior remain in place.

No automatic monthly retention, storage migration, saved-history rewrite,
provider-enrollment change, native-layout change or renderer change is included.
Do not close F01, F10, F11-F13, F15 or F16 on the strength of these tests.

The new tests exercise real Streamlit AppTest reruns, including pending note
changes and intentional deletion, invalid events/hours, first/later requirements,
missing sites, read/write failures, stale-write recovery, event removal, source
asset/provenance retention and the full ordered report save/reopen path. Saved
history is checked independently of the current editor. Preview rendering is
stubbed only in the existing whole-page navigation harness; this is not a
rendering or authentic-PDF comparison claim. Final counts and build/CI run IDs
belong in the PR and the private evidence record, not inferred from old runs.

## Release and remaining acceptance

The restored baseline's full Git tree equals
`c9913498215a0d723e954c5dca3f02aadfae8000`, the tree of current main `63dc18a`.
This is not the older partial source archive. Dependencies remain locked; no
workflow or release gate is relaxed. Record exact final-head tests separately
from focused or earlier test runs.

Public deployment has not been verified by this ledger. A code commit, PR,
passed unit suite or successful container build is not live acceptance. Required
release checks remain the production renderer/fonts, container health and capped
512 MB / 0.5 CPU workload, followed by public app verification. For layout fixes,
inspect actual Word/PDF output with the correct source/pin, not text matches alone.

Rollback is a code revert only. Keep all saved reports, originals, standing
records, installed designs and test-site history intact.

## Deferred owner testing modes

X01-X10 require a separately agreed task. A tester name, hidden button or query
parameter does not isolate writes. A real QA mode must separate all report,
standing-data, upload, cache and external-side-effect paths, with no fallback to
production records. Completed-report prefill and source replay are distinct
checks. Keep independent expected data and authentic source/reference hashes;
never label a prefilled rendering run an extraction pass.
