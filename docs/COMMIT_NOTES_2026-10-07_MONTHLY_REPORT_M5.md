---
document_type: implementation_notes
date: 2026-10-07
base_commit: d385c43510160388a24a6c76f15db04118bdcba9
workflow: Monthly report
change_type: evidence_drafting
status: tested_release_candidate
---

# Evidence-linked monthly drafting checkpoint

This M5 increment remains on draft PR #61 during final validation. Do not
describe it as merged or deployed until exact-head CI and release complete.

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
Applied paragraphs stay editable with their actual source/fact/page links.
No paid model calls or private data were used by automated tests.

Additional local hardening preserves manual and prior AI citations when adding
suggestions, keeps older unreviewed AI text unreviewed, and exposes every applied
paragraph with editable text and real fact/page choices. Current quotes are
checked before rebinding evidence; any text or evidence change requires review
again. Unsupported numbers remain blocking. Fact/draft field types are checked
strictly, unverified dates/tags are flagged, and Copilot vendor/meeting lines are
findings rather than automatically completed work. The current code integrates
the released site-first and visual-editing changes.

New months preserve old issues and proposals as explicit carried items. Each
item has ongoing/updated/resolved status, update text, current source pages or
an entered evidence explanation, and period/content-bound confirmation. A
resolved item is only left out after an explicit decision; prior snapshots
retain it. The output shows confirmed statuses in the corresponding sections.
Source changes invalidate confirmation. Old monthly vendor pages still clear;
standing issue/proposal pictures remain available for explicit visual review.
Same-month starts do not clear work. Fields, sources and carry-forward records
round-trip through snapshots, and the advanced editor retains their provenance.

Equipment tags are directly editable in Site information with confirmed,
attributed profile saving. Copying another site's design never copies its tag
list. New report designs omit price-entry columns; existing snapshots retain
their pinned schemas. A regression fixes reuse of a saved design: ordinary
text/image blocks must not be serialized as imported table overrides.

The final complete local suite passed **865 tests, one CI-only skip** with the
new-design/advanced-editor/tag-control refinements. Ruff F/E9, compileall,
dependency consistency, hygiene/docs and diff checks passed. An eight-page synthetic report with
reviewed AI text and confirmed carried issues/proposals rendered in actual
LibreOffice and was visually inspected; DOCX bytes remained deterministic.
An additional supplied large DOCX walkthrough opened all 13 section cards and
retained activity edits; expected content/unsupported-drawing decisions remained
unapproved. This was local only and did not use a model or produce an accepted
client report. Exact-head CI must establish the released total. Earlier PRs' CI
is separate. Public UI/health verification is limited to independently visible
controls; no persistent synthetic/client profile was created for deployment QA.
