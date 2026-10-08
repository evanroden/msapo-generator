---
document_type: implementation_notes
date: 2026-10-08
base_commit: c9440b067c0bc90628db997d02287e80bacb9093
status: implementation_validation
---

# Explain report memory and first-report requirements

The owner requested repeated novice walkthroughs of blank-template, same-contract
reuse and returning-month flows, plus saved examples and storage visibility.

The guided UI now explains two separate kinds of memory: shared contract/exact-site
reports and anonymous browser preferences. New visitors retain saved content but
must enter their own name; a previous report author no longer silently becomes
the new visitor's editor. Current-session setup/import and remembered browser
names still prefill. Entered names remain unauthenticated and editable.

The selected report says whether it is continuing this month, using the latest
saved earlier month, or starting from its saved design. New-template and
same-contract reuse cards show a plain-language list of first-report inputs.
Same-contract reuse keeps layouts, table headings, logos and dividers; another
site's charts, contacts and work are not copied as this site's facts.

An explicit read-only storage button reports live filesystem capacity/free space
and monthly-report file totals. Scanning is bounded by time and entry count,
skips symlinks, and labels incomplete totals as lower bounds. No filenames are
shown and no storage is deleted. Free space is shared with other app workflows.
Immutable assets and original uploads now enter one global SHA-256 object pool
under monthly_reports/objects. Per-profile paths are hard links for compatibility;
all writes use new digest paths and atomic replacement. No mutable manifest/cache
is pooled. Existing originals and snapshots remain readable. Global pool files
are read-only; no pooled file is edited in place. Streamed originals preserve
source bytes and permissions and bound memory to one copy buffer.

An explicit bounded consolidation action verifies older digest-addressed files
and atomically links them into the pool. Repeating a batch is safe. No historical
record or original path is deleted, and a failed link retains its prior path.
Storage totals count unique filesystem inodes, so links are not double-counted.
Replacements keep the old immutable object for historical reports. Different
encodings of a similar image remain distinct; original DOCX/PDF archives still
retain their embedded media. No automatic pruning or lossy rewrite is added.

Walkthrough regressions cover first-time general-template creation, another-site
design reuse, same-browser resume, a different browser opening shared work,
next-month clearing, and the existing real-LibreOffice regional output flow.
Twenty-one startup/UI/memory checks passed before adding storage tests. Full
validation and deployment pending. Private sample seeding is a separate runtime
action requested by the owner; no private reports or runtime state belong in git.


## Visual upload review follow-up

The owner identified disconnected picture/dropdown controls as confusing. The
upload review now shows bounded groups of four actual previews with plain radio
actions directly below each picture: cover photo, client/ENFRA logo, chart,
outage procedure, contact list, section-title background, or leave out. Previous
and next buttons replace image-ID selectors. Roles remain attached to their
source images across navigation and closed sections; duplicate single-use cover
roles/dividers block approval. Existing per-section signatures invalidate approval
when content choices change. Help reading small text is optional and explained;
no OCR checkbox or "unread drawings" jargon is presented. Rendering failures
remain explicit and cannot silently approve missing content.

Upload intent is no longer a user question. Body text and tables provide current
and older-month findings; cover dates never date work, and image captions never
establish a scanned page's service date. Unknown or mixed content remains subject
to section/page review; this change does not claim full automatic visual dating.

Forty focused upload/UI/Word-page/mixed-month tests passed, including new visual
navigation/duplicate-logo checks. The combined full-suite attempt returned without a final summary; it is not
counted as a pass. A second run and exact-head CI are required before merge. Private
workbook recovered outside git: 25 worksheets, of which three are summaries and
22 are site worksheets. Production directory population remains pending; sheet
warnings and existing saved records must be reviewed before any runtime save.

Private read-only AppTest walkthroughs also exercised 13 sections each of the
retained individual and regional samples, displaying 57 and 29 picture cards
respectively without UI exceptions. Originals were unchanged. This validates
controls against real files, not approval of their contents or final outputs.
