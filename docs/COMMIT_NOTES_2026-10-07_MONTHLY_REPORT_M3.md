---
document_type: engineering_handoff
date: 2026-10-07
base_commit: 73915b17cd1d3e5dbbe429719121e5a5400d29a8
status: implementation_checkpoint_not_yet_released
---

# Monthly report milestone 3 DOCX bootstrap

## Scope and restart

M2 shipped through PR #58 after 738 passing CI tests, with public library UI
verification. This branch adds an operator-reviewed DOCX bootstrap on that
library. Read MONTHLY_REPORT_PROGRESS.md for the current release state and next
action. Do not mistake a branch checkpoint for a merged or deployed milestone.

## Extraction and boundaries

The importer reads bounded ZIP/XML parts without constructing python-docx's
whole-package model, fetching URLs, executing macros/embedded objects or running
the original DOCX through an office application. Limits are independent of
receipt uploads: 128 MB compressed, 256 MB expanded, 32 MB per XML part and 64 MB
total XML. Selected raster images are normalized one at a time with the existing
decoded-pixel and 30 MB image bounds; selected normalized assets total at most
60 MB. Review text, item/cell counts, part counts and XML depth are bounded.

Relationships resolve only inside the package. External, missing, unsupported
or unsafe resources are identified without execution. The inspector handles
inline/floating/VML raster references, linked headers/footers, text boxes, merged
table cells and modern/legacy drawing alternatives. Logical headings and Word
section breaks provide context rather than fixed section/table counts. Split
headings are considered; suggestions are never silently saved.

Native Word shapes/charts and unsupported vector/HD-photo images are retained as
review items with a request for an exported PNG/JPEG. Extracted shape text remains
visible, but is not misrepresented as an intact chart. Converted documents can
split visual regions across several package items. Operators choose the actual
asset and destination. Perfect fidelity for every Word drawing is not claimed.

## Mapping and persistence

A session-owned temporary directory lives under EPC_DATA_DIR/monthly_reports/
imports. The inspector and current image preview survive workflow switches in
non-widget state. Temporary staged files do not become shared defaults. The
operator can discard the staged import; normal session-object cleanup removes
its temporary directory. No uploaded file or generated output is mirrored as
an operator widget value.

The operator inspects one item at a time, selects its destination and table
columns, then confirms the mapping set, editor attribution and explicit profile
membership/aliases/scope. Unknown content stays available in the staged review.
No facility list is inferred from a cover title. The existing profile manager
remains the place to create/edit those identities.

Shared defaults are saved as one atomic, revision-guarded manifest increment;
all previous block versions remain. Imported table column definitions are stored
as additive profile overrides, so extra columns are not silently truncated.
Block versions carry their table schema for restoration. A failed head write
may leave an immutable orphan asset/history file but cannot half-update defaults.
Saving a prior report is a separate explicit choice that pins mapped contents,
assets, period and entered editor; it does not silently change the library.
Generation still runs the existing placeholder/stale-month/review checks.

## Validation and limits at this checkpoint

Private sources were read/rendered only outside git. Their structural variations
informed synthetic regression fixtures; no private report text, names, images or
contact details enter the repository. The importer parsed all eight supplied
DOCX packages. Their large-package and layout patterns are not hard-coded.

Focused parser/persistence tests and existing editor tests are being completed;
full-suite and exact-head CI remain release gates. End-to-end real-client
acceptance belongs to the owner. No monthly EML, passcode, AI request, PO routing
or expense approval policy is added or changed.

## Rollback

Reverting code leaves the runtime library intact. New profile fields are additive
and older readers ignore them, but an old editor should not resave an imported
table with a different column schema. Restore the matching table version through
the current UI or restore its profile definition as appropriate. Do not replace
the entire runtime disk to undo a content edit.
