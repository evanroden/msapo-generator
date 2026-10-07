---
document_type: implementation_notes
date: 2026-10-07
base_commit: 544e7d59b3274f8ffa9defc7b52a932f857c23b6
workflow: Monthly report
change_type: visual_editing
status: tested_for_publication
---

# Contact fields, editable charts and photo pages

Asset managers should edit people, contacts and captions directly and see the
result. The guided site-information step now provides individual contact fields
and editable org-chart positions with names, roles, teams and explicit reporting
lines. A supplied chart/contact image is retained until the operator explicitly
chooses a replacement. Nothing claims to reconstruct an arbitrary image chart
as editable people. Original imports and prior snapshots remain unchanged.

Structured charts are immutable model data, included in snapshot/library JSON.
Old records deserialize with empty defaults. Managers must be existing positions;
cycles and empty/oversized positions are rejected. Larger teams split into
readable pages rather than shrinking every person into an unreadable chart.
Chart text passes normal pricing/placeholder preflight. A partial-report import
cannot silently supersede an existing structured chart with a different image.

Progress photos can be added in a bounded batch, captioned, excluded explicitly,
and arranged one to six per page. Duplicate normalized images are suppressed.
Caption/layout edits update the selected page preview immediately. The exact
same generated image is embedded in DOCX and converted PDF; image proportions
are preserved. Original photo assets and captions remain editable. Photo layouts
carry to the next month while the old monthly photos are cleared. Existing
client-content review gates still apply to every selected source image.

Contact edits preserve independent table schemas. Removing/adding rows clears
only the contact editor's stale widget mirrors; it must not resurrect a removed
person into the next row. Directory replacements reset the new field editor as
well as the older table editor. Shared-directory changes still require their
own confirmation and do not follow report edits implicitly.

Validation: full local suite **845 passed, one CI-only skip**, with real
LibreOffice. After a small advanced-editor preservation fix, 15 focused editor,
visual and public-hygiene tests passed. Ruff F/E9 and diff checks passed. Tests
cover cycles, pricing in chart text, immutable serialization, large-team page
coverage, preview/DOCX image identity, deterministic bytes, editing across steps,
contact removal, progress saving, photo captions/layout/removal and review gates.
A synthetic six-page DOCX/PDF was rendered and visually inspected, including
the chart and six-photo grid. QA files remain outside git. Exact-head CI and
public deployment verification remain before release.

Next: finish M5 source-review/carry-forward hardening in draft PR #61, integrate
these model/UI changes, add an incomplete-report preview PDF and remaining
layout/size polish, then final acceptance. Physical phone/iPad and completed
private-client output acceptance are not claimed.
