---
document_type: engineering_handoff
date: 2026-10-07
base_commit: d649cb8a90dd8382982a6a9c074997b78a152498
status: tested_for_publication
---

# Guided real report setup and mixed month review

Owner-directed increment between M4 and full M5. Removes the synthetic UI and
profile-library toggle, not the synthetic regression builders. The default
experience is contract, month/year and saved report selection, followed by four
stages: report, monthly work, standing information, review/download. First use
starts with a DOCX upload, not a manually constructed empty library profile.

## Preservation and design

Uploads remain bounded at 128 MB compressed / 256 MB expanded. Existing safe
ZIP/XML parsing, inline/floating image extraction and relationships are reused.
Proposed mappings do not auto-pick one of several org charts or tables. Logical
section titles/order, block order and table schemas persist in additive profile
fields. Exact pixel-for-pixel Word reconstruction is not promised. Membership,
scope and aliases remain explicit, never derived from a display title.

Every imported item has a keep/reference/exclude/review decision. Monthly
content, unread images, other-month text and unsupported content need review.
Cover dates cannot classify pages. An optional one-image-at-a-time visual/OCR
reader reuses the existing vision size budgets, retry client and bounded
network-only worker. Its text is untrusted and must be checked visually. The
original file and review decisions remain on the persistent disk. Unmapped
content is retained there; it is not silently copied into output or discarded.

The initial profile manifest is published only after immutable assets and the
original are durable; failures cannot reveal a half-created profile. An existing
profile import never silently changes shared block defaults. Partial text and
pages append rather than overwrite; incompatible table schemas fail visibly.
New-month reset applies only to an explicitly new period, not to an uploaded
document with a stale cover. Saved snapshots and original uploads remain intact.

## Returning managers and monthly work

An additive SQLite table remembers the last contract/profile on the anonymous
browser. Existing device/contract/profile preparer memory is reused. Entered
names remain attribution, not authenticated identity. Save progress supports
incomplete drafts and expected-revision conflicts; same-month reopen resumes the
saved draft. Generation preserves DOCX even when PDF conversion fails.

Reviewed vendor/chemical action fields can append source-linked text to the
activity summary without converting recommendations into completed work. This
is conservative native/manual fact reuse, NOT the full M5 AI drafting engine.
Full source extraction, strict-JSON drafting, Copilot, issue resolution and final
preview/layout polish remain subsequent work. PO/expense business logic is
unchanged. All fixtures and rendered QA samples are synthetic.

## Verification checkpoint

Complete local suite: **801 passed, one CI-only skip**, with real LibreOffice
Writer/Calc available. Compileall, Ruff F/E9, pip check, diff whitespace,
public-repository hygiene and documentation index checks passed. Guided tests
cover upload-first entry, no day
picker/demo toggle, month defaults, step/workflow persistence, save/resume,
placeholder/stale-warning gates and DOCX/PDF-only downloads. Image-reader tests
verify caller-thread preparation, network-only work, hash caching and the
persistent 20-image budget. Single-image and table-schema conflicts cannot hide
an existing version. Imported drafts pin their starting snapshot revision.
Final preservation review added explicit review of unmatched undated text,
resumption of a confirmed import ahead of its older snapshot, and a guard that
leaves the old table schema intact if a monthly table append is rejected.

Six-page synthetic DOCX/PDF output was rendered and every page visually checked.
A stale July cover and a newer service page with an old template date did not
erase September work. Only the explicitly excluded old vendor image was left
out. DOCX bytes were deterministic. QA artifacts stay outside git under
`/workspace/scratch/monthly-report-setup-qa`. No private samples were modified or
used as fixtures. Exact-head CI/merge/public deployment checks are next; do not
claim this increment deployed before those checks.
