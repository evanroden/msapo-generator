---
document_type: section_experience_design
date: 2026-10-08
base_commit: f685aaa10285bce9587a4998ff0462894c5741ab
status: design_direction_not_completion_claim
---

# Section-specific monthly report experiences

## Why this document exists

The owner clarified that each report section needs a dedicated designer exploring
its simplest possible experience, rather than broad reviewers fixing generic
controls. Thirteen dedicated section reviews cover the cover/design plus eleven
numbered sections and Appendix G. This document preserves their proposed designs,
functional findings and acceptance criteria. A design here is **not** a claim
that it is implemented, deployed or accepted with client output.

The app should show recognizable report content first and actions beside that
content. Advanced extraction/mapping settings appear only when a real ambiguity
requires a decision. Every section owns its relevant work; a manager should not
coordinate separate upload, classification, preparation, application and review
systems. Sections remain accessible in any order.

Research reference: Nielsen Norman Group's [Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
and [form cognitive-load principles](https://www.nngroup.com/articles/4-principles-reduce-cognitive-load/)
support showing the necessary task first and revealing secondary controls when
needed. These principles guide layout; section findings below come from repository
inspection, synthetic walkthroughs and retained private samples outside git.

## Shared behavior

- First report: show an intentional empty state and the few inputs needed. Do not
  infer “nothing happened,” “not implemented,” or an agreement/issue status merely
  because an attachment or value is absent.
- Partial upload: retain colleague text, tables, pictures and uncertain content.
  Compare specific differences; never classify every page from the cover date.
- Returning month: reuse exact-site design and standing information. Distinguish
  monthly evidence from historical ledgers and ongoing matters. Carry prior facts
  with their period/provenance, never relabel them as this month's work.
- Preview: show the section's actual output beside edits when possible. Clearly
  label any approximate preview; use the same renderer for final-layout previews.
- Memory: stable record IDs and explicit site memberships, attributed versioned
  saves, immutable originals, conflict guards and recoverable history. No silent
  cross-site contact/agreement copying or shared-default replacement.
- Client output: no prices, commercial-only, blank or signature-only pages.
  Relevant facts need actual evidence; a proposed price-free summary does not make
  its priced original page safe to attach. This extraction improvement is proposed,
  not already implemented.
- Review: content-bound confirmation of affected parts; avoid repeatedly confirming
  unrelated unchanged content. Unknown is distinct from false, zero or complete.

## Cover and report design — dedicated review: design_cover

Start with the assembled cover, confirmed sites, report month and current preparer.
Three actions: **Change client logo**, **Change cover photo**, **Edit report details**.
A logo action opens a short visual tray of current/saved/relevant imported choices
plus upload. A photograph action shows its actual position, a replacement choice
and remove. Photo is optional. Address/footer and divider styling are secondary.
Contents are generated from included sections in their actual order.

Delete per-extracted-image role radios, cover OCR/date controls, raw asset/source
editors and a universal cover assertion about vendor prices/signatures. An old
cover month updates only the cover label. Unknown meaningful artwork stays visible
for review; decorative drawing failures must not create an unexplained blocker.

Integration: shared `monthly_report_cover_ui` for import and saved drafts; existing
asset keys; pure confidence-aware candidate resolver; cached cover preview using
DOCX composition. Never assign artwork by image order alone. Reusing another site's
design may copy contract branding, not its building photo, address or contacts.

Acceptance: (1) new template produces a complete cover without required images;
(2) partial upload with old cover preserves current evidence and colleague text;
(3) next-month cover changes month, remembers design and offers shared-logo changes
without changing earlier reports or impersonating their authors.

## 1. Organization — dedicated review: design_organization

One workspace with four recognizable parts: **Team chart**, **Daytime outage
procedure**, **After-hours outage procedure**, **Facility contacts**. Each shows
its actual content, missing/ready status and Keep/Change. Returning users normally
review the four previews and confirm that they remain correct.

Automatically prepare bounded complete pages when native drawings require them;
rendering mode is not a user question. Preserve complex two-organization branded
contact charts by default. The current simple hierarchy cannot reproduce every
existing chart: editable conversion must be optional with before/after previews,
organization groups, approved business contacts and explicit reporting connectors.
Unreliable rendered labels require a clear replacement/repair state.

New sites reuse reviewed exact-site contact suggestions; no leadership workbook
establishes outage steps or reporting relationships. Procedures can be uploaded or
entered as steps with responsible roles. Directory changes are suggestions beside
current values. Replacement substitutes that part, preserving the other three.

Acceptance: (1) unchanged imported chart/procedures/contacts require no renderer
choice; (2) new-site contacts produce an editable chart without invented lines;
(3) a partial report updates one after-hours procedure and one contact while
preserving the chart/daytime procedure and prior versions.

## 2. Activity — dedicated review: design_activity

Three task cards: **Work completed**, **Work-order totals**, **Progress photos**.
Show report wording grouped by confirmed site, suggested additions beside evidence,
and Add/Edit/Skip. The user should not manually coordinate extraction, retained
facts, drafting, attachment preparation and application.

Work-order uploads show a suggested/remembered mapping and three interpreted rows;
ask only unresolved questions. Coverage is explicitly confirmed. Preserve verified
historical site/month figures with provenance; advance the reporting window and
leave unsupported figures blank. Current rollover clears the entire work-order
block and therefore needs a ledger-aware change before this design is complete.

Photos belong to a work item with site, title, description and thumbnail captions.
Pictured layout choices use the actual renderer. Imported layouts can contain
multiple half-year tables; preserve unknown structures for review.

Acceptance: (1) work can be entered without CMMS setup or invented counts;
(2) next month retains confirmed historical totals but starts fresh monthly prose;
(3) partial text/captions survive source additions; (4) evidence citations point to
the actual supporting page and recommendations remain distinct from completed work.

## 3. Scorecards — dedicated review: design_scorecards

One **Utilities & capacity** workspace, rather than splitting the section across
tabs. Show utility-result period/site and reusable heating/cooling capacity in two
cards. Actions: **Add updated results**, **Edit summary**, **Update capacity details**.
When results are absent, offer a confirmed neutral availability note; do not assume
M&V approval status. Prior results are visibly dated reference, not current results.

Keep required/available capacity and units only where supplied. Unknown values stay
blank. Preserve imported schemas; not every scorecard table is thermal capacity.
Uncertain native charts need complete-page preview, not dozens of drawing fragments.
Price-bearing bills/rate/savings material stays out; supported physical consumption
or performance may remain. Historical-chart exceptions apply to that chart only.

Current gaps: utility text can carry unchanged into the next month; stock-text UI
cannot upload updated charts; shared page destinations omit utilities; the importer
routes all scorecard tables to capacity. Dedicated UI and conservative period/schema
adapters are required, not label changes.

Acceptance: (1) pending results require no fabricated reason or zero capacity;
(2) mixed regional current/history/unknown charts are decided independently;
(3) next-month capacity persists while new results are dated and reviewed.

## 4. MBCx — dedicated review: design_mbcx

**System performance checks (MBCx)** explains ongoing building-equipment checks,
usually supplied through ENFRA Connect. Show the exact status note and included
pages first. Actions: **Add this month's report**, **Write or change the update**,
**Leave this section out**. Do not assume pending implementation from missing files.
Offer confirmed sentence starters and an unfinished state.

Separate reusable `mbcx_status` wording from monthly `mbcx_report` pages. Migrate
legacy wording on detached working copies; retain originals/references and author
instruction gates. A current status carries for review; prior monthly pages stay in
history. Section-local uploads should have a fixed destination and one apply action.
Date/site findings belong to pages; MBCx findings are not automatically completed work.

Acceptance: (1) manager explicitly confirms reporting has not started;
(2) mixed technical/priced/legal pages produce only reviewed useful output;
(3) partial upload preserves current content despite an old cover and flags scaffolding.

## 5. Maintenance — dedicated review: design_maintenance

Two visible parts: **Work completed** and **Supporting service reports**. Primary
actions add service files, a work-order spreadsheet, or entered work. Show the
editable service table, selected-page thumbnails, targeted questions and output
preview together. One **Add reviewed work and pages** action applies confirmed
service rows, attachments and proposed Activity Summary additions.

Only reporting-month completed rows enter the monthly completed-work table. Retain
ongoing/undated rows for an explicit status decision, not silent discard. Detect
merged table titles above actual headers. Duplicate work-order conflicts show
existing/new descriptions and Keep/Update/Both. Source pages retain originals,
page-level dates and evidence; unreadable pages cannot be called reviewed.

Remove destination menus within the section, page-number multiselects and the
Read/Prepare/Add/Approve/Add chain. Show already excluded pages with reasons and
use page previews. Keep twelve-month coverage questions in Activity's totals task.

Acceptance: (1) mixed six-page vendor packet needs no destination selection;
(2) partial old-cover report preserves current rows and ongoing work, with real
headers; (3) regional returning format/mapping persists and unknown-site/conflicting
work-order rows produce narrow questions.

## 6. Subcontractors — dedicated review: design_subcontractors

**Vendors & service contacts** shows the report matrix and vendor cards. Each card
has company, service, sites served, contacts, when-to-contact instructions and
agreement status. Actions: **Everything is still correct**, **Add a vendor**, and
**Review suggested changes** when present.

Agreement states: Confirmed in place / Not in place / Needs confirmation / Not
applicable. A blank or unchecked legacy MSA is not automatically no agreement.
Single-site membership is prefilled; multi-site associations use checkboxes.
Vendor identity may be shared while service scope, contacts and agreement differ
by site. Leadership directories do not establish vendor relationships.

Preserve cross-tab and combined-contact notes until their meanings are confirmed.
Use vendor-specific fields instead of generic contact/table editors. Shared changes
name affected sites; report saves normally affect only this exact-site report.

Acceptance: (1) same-contract design reuse does not copy agreements;
(2) partial upload compares changed phone/new vendor/unknown agreement separately;
(3) next month needs one unchanged confirmation; adding a site never silently assigns
it the other site's vendors or agreements.

## 7. Water — dedicated review: design_water

Organize by **service visit**, then confirmed site/system, rather than extracted
objects. **Add water-treatment reports** opens this section's upload. A visit card
shows useful-page thumbnails, supported work/findings, out-of-limit concerns and
open follow-ups. Add reviewed wording to Activity without replacing existing text.

Native text/table reports and full-page scans require assembled-page review. Tiny
Word fragments are not meaningful report pages. Establish period/site per page or
visit group, not once per source PDF. Unknown values remain unknown. Flag explicit
vendor concerns or compare only against confirmed unit/system-matched targets;
never invent chemical limits. Next month retains supplier/system/layout and open
issues, not old readings or attachments relabelled as current.

Acceptance: (1) useful pages/actual readings only in output;
(2) partial multi-site packets preserve current visits and separately review old ones;
(3) next month remembers associations and follow-ups while starting new monthly pages.

## 8. Equipment issues — dedicated review: design_issues

One issue register, grouped by site. Each card shows equipment/tag, short title,
current status and latest update. Actions: **Still open**, **Add an update**,
**Resolved**. An update opens one field and supporting evidence; unchanged items
need no new prose. Resolution stays in the report unless explicitly omitted.

Remove duplicate global follow-up plus generic section text editors. Keep stable
issue identities. Preserve unparsed imported text/tables until manager-confirmed
conversion; splitting every line can turn headings into issues. Ask whether an
ambiguous item is an equipment problem or planned replacement beside its source.
An explicit No issues statement cannot coexist with unresolved carried items.

Acceptance: (1) imported candidates preserve equipment/site meaning;
(2) returning open/update/resolved actions produce one coherent client list;
(3) partial evidence additions preserve colleague updates and do not auto-merge,
resolve or delete similar-looking issues.

## 9. Capital renewal — dedicated review: design_capital

**Equipment replacement plans** has **Needs replacement or major renewal** and
**Expected replacement timing**. Item cards show equipment/tag, site, needed work,
reason, known priority and status. Optional timing/evidence stays under more details.
Timing accepts a year, month, exact date or unknown without inventing precision.
No current recommendations is an explicit operator statement, not automatic stock.

Returning plans carry unchanged; completion/removal are explicit and recoverable.
Preview price-free tables beside cards. Mixed merged headers must never cause the
equipment-description column to be mistaken for a price column and discarded.
Keep ambiguous tables intact, block output and ask for column names before removal.

Acceptance: (1) unknown replacement timing stays blank with no cost field;
(2) merged import headings preserve all recommendations until price mapping is known;
(3) next-month plans retain statuses and only explicitly omitted items leave output.

## 10. Proposals — dedicated review: design_proposals

Cards show scope, vendor, site and the actual decision: Pending / Approved /
Declined / On hold / Not confirmed. **Still correct** or **Update this proposal**
reveals changed scope/decision and evidence only when needed. Alternative/Option B
is separate from decision status. Approval does not mean completed work.

Quotes remain reference-only by default; propose a checked price-free scope rather
than attach commercial pages. Partial conflicts compare saved/uploaded decisions.
Stable proposal records persist separately from equipment issue resolution. Never
produce contradictory “Ongoing ... Status: Declined” by flattening every proposal
into an issue-style follow-up. Archiving is explicit and reversible through history.

Acceptance: (1) quote creates price-free checked scope/status without attachments;
(2) saved Pending vs uploaded Declined gets a meaningful choice;
(3) next month retains true decisions and nothing disappears or becomes completed
solely because it was approved/declined.

## 11. Training — dedicated review: design_training

**What training happened this month?** uses event cards: topic, optional roles,
site only for multi-site reports, known hours and optional captioned photos. Unknown
hours stay blank. Do not confuse duration with person-hours or calculate annual
totals from incomplete records. Exact day is evidence detail, not a required input.

Separate current events, confirmed earlier training, uncertain entries and explicit
examples/scaffolding. Preserve annual history; next month starts fresh additions,
not a destroyed year-to-date ledger. Confirmed No training this month is explicit
and must resolve conflicts with existing events. Keep legacy narrative until a
structured conversion is accepted. Add optional training photo grid separately.

Acceptance: (1) known topic/roles plus photo and unknown hours renders without zero;
(2) partial annual ledger retains real work while examples/future scaffolds are
reviewed separately; (3) next month retains history and an explicit no-training
statement does not erase it.

## Appendix G — dedicated review: design_rfi

Requested information belongs in a site-by-request checklist, not a Complete
Boolean alone. Preserve at least Not confirmed / Not received / Partly received /
Received / Not needed, with original symbols retained until their meaning is
confirmed. Show progress and a report preview; repeated header/footer branding is
not an appendix item. New general reports leave this optional appendix out until
real requests are supplied. A directory establishes sites/contacts, not requests
or completion. Open requests carry until an explicit decision.

Acceptance: (1) a new real request is associated only with checked sites;
(2) an imported partial/unknown symbol is not converted to complete;
(3) returning requests retain status and evidence, and an empty appendix stays omitted.

## Implementation sequence and limits

1. Correct data-loss and semantic defects uncovered by section exploration, with
   synthetic regressions. Deliver a first dedicated MBCx status/pages editor while
   preserving current output gates and legacy data.
2. Build the shared section shell (preview, direct task actions, targeted questions,
   content-bound save status) and finish cover/organization import-to-return parity.
3. Integrate section-local evidence ingestion and one reviewed apply action for
   Activity, Maintenance, Water, MBCx and utility results. Reuse existing bounded
   parsing, deduplication and policy gates; do not build duplicate parsers.
4. Add structured issues/proposals/vendor/request records and training/work-order
   ledgers with conservative adapters for legacy narratives/tables. Never silently
   force unknown content into a guessed schema.
5. Run the three first/partial/return cases for each section, including actual
   retained report layouts, then production checkpoints and owner output acceptance.

Runtime directory/sample population, storage expansion decisions and copied workbook
membership ambiguity remain separate outstanding work. None is claimed complete by
these section designs.
