---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 6f65108cb181310a27b60648f06e289e6c3189cd
status: focused_tests_passed_pending_exact_head_ci
---

# Hospital-only training roster

The monthly client report is for hospital staff training, not the service
provider's personnel. The previous automatic enrollment selected ENFRA,
asset-manager, operator and technician roles while excluding an explicitly
identified client contact. This corrects that business-rule inversion.

## Behavior

Only contacts explicitly identified by role as hospital/client personnel are
added automatically. Directory contract identity and a unique active site match
are required. Provider evidence (ENFRA, Bernhard, asset manager, vendor or
contractor) takes precedence within a role. An ambiguous same-name hospital and
provider pair is not automatically enrolled or removed.

An existing or saved matrix is filtered only for provider identities proved in
the same matched site. Unknown/manual people and their recorded statuses remain.
Name matching is whitespace/case normalization, not fuzzy identity inference.
Unqualified role labels such as Operator alone do not prove employment and are
not automatically enrolled. The interface asks editors to check manual names.

A cached session matrix receives the same filter. Its grid generation changes
when provider rows are removed, so obsolete widget deltas cannot restore those
rows. Adding a positively identified provider through the grid is rejected
before a shared write. This is not a general prohibition on manually adding an
unclassified hospital employee.

Read-time filtering affects the working report only. It does not rewrite shared
training history, saved report snapshots, source pictures or narrative/event
records. A normal explicit matrix edit saves the changed standing roster through
the existing optimistic-revision check and selected-site write path. Blank
completion history remains Not recorded; no training date or completion is
inferred from role, enrollment or a directory change.

## Verification

Five new assertions reproduced the original inversion and stale-provider reuse
before the correction. The focused suite now contains 19 passing cases, including
actual Streamlit AppTest coverage of a stale session matrix, provider re-entry
rejection, unchanged shared storage and historical snapshot bytes. Existing
conflict/reload, month/date validation, source-content preservation, unnamed
visitor and native matrix rendering-style controls remain.

Two older positive roster fixtures were changed from provider roles to explicit
hospital/client roles to reflect the owner's requirement. Provider contacts remain
negative controls; the alias, retired-site and ambiguity controls were retained.

Local tests use LibreOffice 25.2, not the production 24.2 renderer. Exact-head
full CI, production renderer/font checks, container health and the inherited
512 MB / 0.5 CPU synthetic resource test are release gates. Record their actual
results in the PR rather than treating these focused counts as a release result.

## Boundaries and rollback

Uploaded training-page images, historical free-text notes and completed event
participants are not silently edited. People without sufficient employer/site
proof require normal review. This does not complete the separate contact-grid
promotion, vendor/capital reuse, private thermal-data installation, native table
schema, cover or remaining PDF-fidelity work.

No persistence schema, authentication, hosting plan, source-original, design pin,
image-approval gate, PO routing or expense policy changes. Revert the code to roll
back; do not delete or roll back saved business data.
