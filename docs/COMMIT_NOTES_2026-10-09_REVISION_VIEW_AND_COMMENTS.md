---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 63dc18ace500f680811db6c9979cf17b13d6a771
status: focused_regressions_passed_pending_full_ci
---

# Final revision view and comment-safe exports

## Findings and scope

CR-render-1 / F2: the inspector removed deleted runs but still read move-from
text; the native package kept insertion/deletion wrappers and prior property
snapshots. Replacing one paragraph with multiple current lines could duplicate
deleted source text and attribute current content to an old reviewer.

CR-render-3: comment parts were pruned but their body/header anchors remained.
LibreOffice then rejected the DOCX. Both final PDF generation and affected
section previews failed while the UI suggested retrying the unchanged input.

## Changes

A shared current-view normalizer runs before passive dependency traversal and
before inspection chooses compatibility representations. It accepts inline
insertions and move-to content, drops deleted/move-from text and prior property
records, removes deleted table rows, accepts inserted rows and removes tracked
revision display settings. Current run/paragraph formatting remains intact.
Comments and their anchors are excluded in every emitted Word story without
deleting adjacent current text from a shared run. Dependencies used only in
deleted content are pruned, and deleted-only pictures are not offered as
unplaced current import assets.

Uploaded originals and their SHA-256 identities remain unchanged. Inspection
items use a `current-v1-` identity prefix only when revisions affect the view;
legacy ordinal references cannot silently attach to shifted items. Clean and
comment-only sources retain existing IDs. Old saved report payloads are not
rewritten; old revision-affected source bindings require fresh mapping rather
than reinterpretation. Section-preview fingerprints include the new renderer
version. Immutable design/profile identities and their historical schemas are
unchanged. The design screen explains the final-text/comment policy; import
inspection reports the changes without showing deleted text or reviewer names.

## Explicit unresolved structural cases

This is not a universal tracked-structure editor. Paragraph-mark deletion or
move-from marks, cell deletion/merge revisions, and block-level revision wrappers
are rejected before import/export with a specific structural-change message.
Removing only those markers would silently change layout or retain wrong text.
The operator must resolve those structural changes in a copy of Word first.
Originals and saved records remain untouched. Full F2 support for such revisions
remains open; this rejection is not presented as successful content preservation.

Other F1-F8/CR issues, including unauthorized page-chrome artwork, cover handling,
source TOCs, independent pricing and footer controls, training lost updates,
upload races, and converter timeout cleanup, are not closed by this change.

## Verification and evidence boundaries

The original ten failing tests reproduced deleted/moved source retention,
comment-caused PDF failure, revision-colored current text, and deleted-row
retention through actual application functions. New controls cover both
master/continuation final exports and previews, all reachable note stories,
header/footer comments, both compatibility branches, deleted image dependencies,
page fields, deleted-only paragraphs, original-file immutability, versioned
mapping, and explicit structural rejection. A source-geometry assertion uses the
saved Word value (rounded to twips), not the unrounded input float; it also checks
the first nonempty run rather than a fixture's empty run.

The restored local source archive is at 7e2e4d0. GitHub's comparison to the current
63dc18a baseline confirms that the changed renderer/import modules and their
existing tests are identical; intervening PRs touch contact/training modules.
Local Python 3.12.3 and all dependency versions are restored from the locked QA
runtime (`pip check` passes); local LibreOffice is 25.2, not production 24.2.
Local runs are supporting evidence only. Exact current-base CI, production
renderer/fonts, image build/health, and the inherited 512 MB / 0.5 CPU probe are
mandatory before merge. Record exact tested SHA, counts and run IDs in the PR.
No private reports, extracted client text or font binaries enter Git/artifacts.

## Rollback

No persistent data migration. Reverting the code restores the previous behavior
but also restores its known export risks. Do not delete or roll back originals,
contact/training stores, historical report snapshots or pinned designs.
