---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 075fa6310f42053d7fd770c51cb8e736fe2da605
status: implementation_under_validation
---

# Current narratives: body flow, not old title or text-box canvases

## Owner finding and reproduced cause

Usability audit F16 reports imported metrics overlapping the utility title and
empty bullet groups surrounding current equipment narratives. The accepted
content existed in the output, but was not readable or professionally laid out.
The associated changed-footer observation remains a separate unresolved path.

On the exact main baseline above, the first nine new tests produced **seven
failures and two passes**, including actual LibreOffice output. A repeated run
with a clarified synthetic cover and independently linked divider header gave
the same seven failures/two passes. This uses actual application modules, not
copied renderer helpers. Source files contain synthetic data only.

The renderer had registered an outline/title paragraph as a narrative prototype.
It also treated an outer paragraph containing an entire multi-paragraph text box
as one text anchor. Extra current lines cloned that entire old canvas, restoring
its otherwise cleared empty numbered paragraphs. Finally, a rewritten section's
body margin did not reserve the page-anchored running title's actual bounds.

## Scoped change

`monthly_report_native_text.py` chooses one substantive body paragraph and copies
its paragraph/run formatting into a clean paragraph. Outline styles are resolved
through the style inheritance chain, including derived styles without their own
paragraph properties. A known utility title/author label is not a narrative slot.
The safe canonical utility title remains when it is not supplied by the running
header. Old author text is not retained.

Changed narrative lines form a contiguous body flow instead of filling arbitrary
old source anchors and cloning their canvases. New paragraphs do not inherit the
old text box's bullet numbering or floating container. Explicit current text,
including any literal bullets or numbers, stays current text. Independently
current tables and other payloads keep their own render path.

The page planner reserves clearance only for a **rewritten text-bearing region**
with bounded, visible, page-anchored header geometry. The new body margin includes
a six-point separation after the measured header boundary. This is not a global
font change, a Word-specific baseline offset or a paired-profile calibration.
Header/title shapes do not move. Unchanged/source-proved regions and dividers are
not adjusted. Ambiguous, paragraph-relative, full-page, empty or hidden geometry
is not used as evidence for this correction. Existing larger margins stay larger.

A new control found that the initial clean-paragraph implementation could discard
an explicitly retained footnote. That implementation was not published. Approved
foot/endnote references now move once with rewritten prose; omitted/source-only
notes do not return. Tests check both package relationships and actual PDF text.
Additional controls corrected two issues in the initial helper: inherited outline
styles with no pPr, and hidden DrawingML header frames. These are follow-up
implementation tests, not additional baseline defect counts.

## Evidence and limits

New tests include short and long utility narratives across continuation pages,
changed versus source-proved unchanged canvases, body typography, header variants,
VML and DrawingML geometry, unambiguous negative geometry controls, notes alongside
tables, explicitly retained/omitted footnotes and endnotes, and both short/long
prose through all twelve report sections. The final `generate_report` path is
exercised after installing an isolated synthetic contract design, not only the
lower-level Word builder. No customer storage or production report is mutated.

The isolated synthetic final-generation comparison keeps the utility title at
its original coordinates. Before repair, the narrative begins inside that title's
bounds; afterward it begins below those bounds. The two current equipment lines
remain once and no empty source-list groups return. Private checks also generated
Scorecards and Equipment sections from two authorized reference Word designs with
synthetic current text. These are bounded source-layout checks, **not** whole-report
replays against the authored PDF, nor Microsoft Word certification.

Proven unchanged synthetic canvas output is checked independently. Source originals
and pinned design hashes remain unchanged. This change does not re-approve any
picture, migrate stored report JSON, rewrite historical snapshots, or change the
conversion locks, rendering profiles, image selection, pricing or review gates.
Preview caches are process-local and are rebuilt on deployment; assembled-document
bytes continue to determine backend rendering inputs.

Local validation uses locked Python 3.12.3 / Streamlit 1.61.1 and restored
LibreOffice 24.2.7.2. The local Arial Narrow mapping does not match the production
OTF mapping; that mismatch is reported, not repaired by changing production fonts.
Required CI still validates the actual production fonts, full suite, image health
and existing 512 MB / 0.5 CPU resource scenario. Exact final-head counts, hashes,
run IDs and visual-comparison measurements belong in the PR and private evidence.
Do not sum overlapping test selections or call the local font environment exact
production parity. No runtime libraries or font files are included in the patch.

## Remaining work and rollback

F16's originally observed post-import footer change has not been reproduced by
this slice; the rendered synthetic PAGE/footer control stays intact. Mixed or
partially source-retained layouts outside the proved rewrite path still require
case-specific output checks. This is not a universal collision detector or a
certificate of complete report fidelity. F12 divider numerals, F13 image/branding
fit, F11 Activity extraction and the supplemental recovery/readiness issue remain
independent work. The historical F14 and F15 fixes were merged in #99/#100.

Rollback is a code revert only. Do not remove saved drafts, source originals,
standing records, designs or QA history. Public deployment requires independent
verification after the authorized main merge; CI and a merge alone do not prove
which build the public app serves.
