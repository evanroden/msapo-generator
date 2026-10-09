# Monthly report builder: next-LLM handoff

Updated October 9, 2026, America/New_York. Read this before changing the report
builder. This is a testing release, not a declaration of complete PDF fidelity.

## Latest owner instruction and release decision

The owner explicitly asked us to stop expanding the work, deploy the completed
changes for their testing, and preserve a detailed handoff because weekly usage
was running low. This supersedes the earlier decision to hold PR #91 for every
authentic-PDF discrepancy. Remaining defects below are accepted as documented
testing-release limitations, not solved or waived long-term requirements.

- Repository: `evanroden/msapo-generator`.
- Public app: https://msapo-generator.onrender.com/
- Release PR: https://github.com/evanroden/msapo-generator/pull/91
- Feature branch: `feat/monthly-report-ordered-workflow`.
- Previous production release: PR #90, merge `a26c691c0b427c2373a902a72c3f4b728b3c595c`.
- Final merge/check/public verification evidence belongs in PR #91 and the release
  addendum to this handoff; do not assume deployment merely because code was pushed.
- Unfinished prototypes are preserved separately on
  `wip/monthly-report-fidelity-handoff-2026-10-09`; do not merge that branch wholesale.

The owner has authorized ordinary fixes, commits, PRs, merges and production
updates. Do not ask again for routine permission. Do not use private Render
workspace/log access. Deployment is through GitHub main auto-deploy, followed by
public app checks. Keep private reports, contacts, runtime objects and QA evidence
out of Git. No persistent QA report was saved under the maintenance actor.

## Product requirements that must survive the next iteration

1. Generated Word and PDF reports must eventually be visually and functionally
   indistinguishable from the actual ENFRA designs. Same-converter equality alone
   does not establish this. Test completed source reports and real authored PDFs.
2. Starting without an uploaded report must retain the master design. New master
   versions should be easy to install, while existing report pins remain immutable.
3. Contract, reporting month and multiple sites come first. The inline directory
   shows those sites together; a deliberate save also updates the working report.
4. Use one agnostic starting-report upload for old, other-site or half-finished
   reports. Do not restore separate resume/import upload flows.
5. One scrolling page follows report order, with clear sections and adjacent,
   automatically updating, sharp, scrollable section previews. All core sections
   remain; designs can include their RFI/Accounts Receivable appendix.
6. AMs should not manage shared logos, inclusion checklists, equipment tags,
   memory choices, or standing-information confirmation checkboxes. Retain shared
   workflows/data automatically where appropriate.
7. Activity is upload-first, with grounded first-pass writing, visible Copilot,
   a work-order checkbox, protected manual edits and improvement photos.
8. Capital and proposals accept source documents/tables/images. Proposal prices
   must never reach the final report. Training is a matrix plus monthly events.
9. Thermal capacity uploaded for a contract should propagate relevant sites;
   reusable outage diagrams and standing data should not require repeated uploads.

The owner deferred a passcode during testing. Entering a name provides attribution,
not authentication. Do not describe that gate as authenticated access control.

## Completed work included in the testing release

- Ordered report workspace, selected-site directory, one starting upload, removed
  AM logo controls, all sections, per-section previews and the requested input flows.
- Current contact saves refresh the working report; resumed imports reuse Prepared
  by and name gates cover saved-team/source-review displays.
- Malformed-photo decode failures are contained; stale preview results are discarded.
  The exact originally reported valid-photo crash was not independently reproduced.
- Shared conversion serialization spans threads and processes, including Word page
  rendering. Foreground/calibration waits are bounded; preview contention retries
  automatically rather than becoming a cached permanent error.
- Native source geometry, mixed image/table placement, link preservation and current
  content proofs. Source content cannot survive solely because adjacent logos remain.
- Both Eastern/RGH SmartArt branches retain their complete closed diagram graphs.
  Removing current chart text removes stale diagrams; unsafe dependencies are rejected.
- Bounded static EMF/WMF review/import restores Eastern's two equipment inventory
  pages. Unchanged reviewed vectors retain their original bytes; changed/removed
  assets cannot retain old vector content.
- Portland's duplicate mixed tables and divider canvases are fixed. Its source and
  generated body now have the same 1,278-element sequence, and pagination is 39/39.
- Production fonts include Carlito/Caladea with explicit Calibri/Cambria aliases.
  Do not replace Arial Narrow globally: that experiment regressed UMMC cover layout.
- Immutable paired Word/PDF design profiles through version 4. Individual corrections
  require reference evidence; PDF producer metadata is audit information, not a switch.
- Scoped alpha-frame transparency and invisible-empty-frame wrapping corrections.
- Passive HTTP/HTTPS links survive only in proven, unchanged, visible current text.
  Rewritten, omitted, hidden or unproved text cannot retain stale links.
- A tested isolated header-suppression helper is present but deliberately unwired;
  it is not a claimed fix for Eastern's training divider overlay.

The original Review A findings were handled in earlier releases. Read the existing
Review A notes before reopening duplicate-widget, directory, rename, second-import
or workbook-reader issues; do not infer they are still open from older user quotes.

## What the comparisons actually establish

| Case | Established evidence | Limits |
| --- | --- | --- |
| UMMC August authentic PDF | Official generated output has 45 pages; all page/image geometry, 18 bookmarks, link targets and link rectangles match. Stable source replay is pixel-identical outside three deliberately removed Cost labels. | Supplied PDF retains embedded-image compression differences. This is the strongest completed acceptance case. |
| Unity/USH September continuation | Source/output 39/39 pages; zero changed pixels outside three Cost-label redactions under the same stable converter. | No authentic September PDF supplied; do not claim Word-export equivalence. |
| UMMC September continuation | Same 39/39-page, Cost-only same-converter result. | Same limitation. |
| Unity/Eastern cover typography | Actual v4 calibration API independently derives the correction; final line baseline errors 0.01/0.14pt with visible lettering intact. | Covers only; full reports still differ. UMMC receives no typography correction. |
| Portland continuation | 39/39 pages; exact body identity order; activity divider pixel-identical. UMMC DOCX ZIP members unchanged by this fix. | Only 19/39 Portland pages pixel-identical overall; remaining differences are not all explained by redactions. |
| New report from master | Current contract/sites/month/author replace source identity; private source facts, contact emails and data images clear; all 12 logical sections remain. | Native table grids are replaced by generic schemas, and empty sections retain blank pages. Not accepted. |

Prior checkpoint `c7e63ca84841d773050e64e1de6556df609a602a` passed 1,600 tests with
zero skips and production-container build/health. `1c7f6fa` passed 65 local profile,
compatibility and color-scope tests. V4 focused runs passed 14 metrics/locking,
41 compatibility/scope and 28 profile tests; these sets overlap and must not be
added into a fictional total. Portland final divider tests passed 15 and its
broader import/SmartArt run passed 52. Header helper has seven tests; preview
busy retry has five focused tests. Final-head evidence must be recorded separately.

The `381c863` test CI job hit its old 20-minute budget while downloading renderer
packages from Ubuntu's mirror, before tests started; its container job passed.
The test job budget is now 45 minutes. Tests/renderers remain mandatory; a network
timeout must not be called a test pass or used to remove the rendering checks.

## Open work, in recommended order

### 1. Fresh-master table schemas and blank pages

This is a real product defect, not merely font rendering. Newly pinned master
reports still initialize generic columns: UMMC thermal tables go 8/7 to 4 columns,
subcontractor 3 to 6, capital 4 to 3, and one proposal 9 to 4. `_table` replaces
the original physical grid. The editor must use sanitized native schemas and map
entered values back into the original columns, retaining merged cells/style/widths.

Prototype: `app/monthly_report_master_tables.py` on the WIP branch, untested and
unhooked. Proposed path: seed `ReportTable` entries in existing `extra_tables`
after master pin, using source-hash/item references and no source rows. Retain
different schemas for separate thermal tables. Continuation tables may start
with source row 16 instead of a header; never copy that row as column labels.
Omit price fields from entry/output while preserving blank physical grid columns
if the design needs them. Saved current data must remain authoritative.

Repro and findings: `layout-qa/fresh-master-audit/{audit.py,results.json,HANDOFF.md}`.
The current blank/new PDFs have 38 pages, including blank organization p4, vendor
p17–19 and water p23–27. Fix section/page scaffolding with positive geometry proof;
do not broadly delete every empty paragraph.

### 2. Unity/Eastern divider typography, numeral and shadows

White title fill and divider wrap are calibrated in production code, but Word
and LibreOffice line metrics still differ. Eastern's two-digit numeral 10 wraps
its 0 below the visible box. `wrap=none` failed. Expanding only the invisible box
by the exact negative terminal tracking (20pt) restores both glyphs and matches
horizontal bounds within 0.33pt, but its baseline remains 8.87pt too high. Do not
ship that adjustment alone. Multiline title second baselines are about 5.87pt high.

Prototype module/tests: `monthly_report_divider_metrics.py` on the WIP branch.
Fourteen unit tests pass, but there is no complete paired-reference calibration,
profile hook or final render proof. A prepared 240-to-288 line-spacing trial was
not rendered when work stopped. Reuse the bounded v4 cover-calibration pattern,
binding source anchors, geometry, styles and alternate representations.

Authentic Eastern shadows can be isolated as all-black alpha masks without page
resources or concealed color content. A scratch overlay aligns the first title
line but not the second because typography is still wrong. Fix baselines first.
Never copy an entire PDF page's hidden resources merely to clip out a shadow.
Evidence lives under `layout-qa/ah-audit/`: `number-terminal-spacing-control/`,
`reference-shadow-control/`, `divider-metric-trial-v2.json`, and
`divider_metric_trial.py`. No shadow correction is in production.

### 3. Eastern pagination, training overlay and RFI geometry

Read [the detailed Eastern handoff](HANDOFF_EASTERN_PDF_FIDELITY_2026-10-09.md).
Restored inventory exposes 41 generated pages versus 39 authentic pages; the
earlier 39-page result hid two missing inventory pages and was not a pass.
The two extra-page controls remain unrendered. A training-divider-only header
suppression has strong crop evidence and exact source/generated fingerprints,
but needs independent paired-reference calibration and underlying-art binding.
Missing image metadata is not proof a reference logo is absent.

RFI has an approximately 13pt top-origin deficit plus a 0.5pt row-pitch deficit.
Border-inclusive row heights alone do not fix continuation. Header line-height
controls failed and remain rejected. Do not globally apply Word-specific offsets
to UMMC, whose authentic reference was produced by LibreOffice.

### 4. Remaining designs and production calibration reach

RGH, Central CT and Adventist reports broaden coverage but do not have authoritative
supplied PDFs in this workspace. Source-converter defects still need work. Do not
claim all ten uploaded reports pass. The report-design UI currently installs a
company master with an optional companion PDF; contract/profile paired installation
exists as an API but does not have a matching dedicated UI route. The verified
production master before this release was unpaired UMMC version 1. Deploying v4
code does not silently repin old drafts or automatically calibrate every uploaded
Unity/Eastern report. Inspect actual production pin state before claiming those
reference-specific fixes are active for an AM. Preserve immutable old versions.

## Architecture and safety invariants

- `monthly_report_native_layout.py` binds current text/tables/pictures to source
  positions. `monthly_report_native_package.py` creates a closed passive package.
- `monthly_report_designs.py` stores immutable source objects and paired metadata.
  Paired identity hashes source, PDF and exact versioned profile; both content hashes
  and metadata are checked. V1–V3 schemas/identities must remain unchanged.
- `monthly_report_render_profile.py`: v1 cover origin, v2 independent divider crop/
  geometry, v3 independently proven white text, v4 measured cover line/anchor values.
  Ambiguous evidence preserves native behavior. Global text-style changes require
  proof across Word stories and distinguish live duplicates from Choice/Fallback.
- `monthly_report_cover_metrics.py` changes only disposable PDF copies; native
  downloadable DOCX is untouched. At most three cover renders, final baseline/ink
  verification, finite bounded records, stale geometry rejection, no font changes.
- `monthly_report_render_jobs.py` serializes only backend conversion, with bounded
  thread/flock waits. Do not wrap native assembly/metafile preparation in that same
  lock or introduce nested-conversion deadlocks.
- `monthly_report_section_preview_ui.py` discards stale work and automatically
  retries contention. Noncover previews clear cover corrections.
- `monthly_report_metafiles.py` and Word-page worker validate passive vectors and
  impose resource bounds. Actual picture review is required; never synthesize
  approvals just to make an export succeed.

## Local environment and evidence recovery

Working checkout: `/workspace/scratch/monthly-report`.
Scratch root: `/workspace/scratch/0792453990a9`.
Source DOCX files: `upload/`; authored reference PDFs: `enfra-layout-sources/`.
Private QA: `layout-qa/`. A compact private evidence archive is saved separately
as `monthly-report-qa-handoff-2026-10-09.zip`; it contains measurements, scripts
and selected proof PDFs, not the full runtime object stores or original uploads.
If scratch is gone, recover the user's original uploaded reports as well.

Only these are authentic supplied PDF baselines:

- `RRH - UMMC August 2026 Monthly Report(2).pdf`: 45 pages, LibreOffice 24.2.
- `RRH - Unity and USH August 2026 Monthly Report (2).pdf`: 40 pages, Adobe PDFMaker.
- `RRH - Eastern Region August 2026 Monthly Report(2).pdf`: 39 pages, Adobe PDFMaker.

UMMC `(4).pdf` is our old 46-page alpha-render artifact, not an authentic baseline.
No authentic September PDF was supplied. Do not promote another agent-generated
PDF to ground truth because its filename looks like a finished report.

Important artifacts relative to `layout-qa/`:

- `production-font-controls/ummc-current-links-final/`: official UMMC functional,
  link and visual comparisons.
- `cover-calibration-controls/production-api/results.json`: real v4 calibration
  results, with seven companion proof PDFs in that directory.
- `unity-september/` and `ummc-september/`: accepted same-converter continuations.
- `ah-audit/divider-all-fixed-control/`: final Portland 39-page replay.
- `additional-references/eastern/`: authentic page, geometry, inventory, header,
  SmartArt and RFI investigations. Earlier files may predate later corrections.
- `ordered-independent-audit.json`: real application selected-site/one-upload/
  all-section/no-AM-logo walkthrough.
- `stable-converter-handoff.md`, `fresh-master-audit/HANDOFF.md`: focused notes.

Use locked dependencies via
`PYTHONPATH=/workspace/scratch/monthly-report-venv/lib/python3.12/site-packages`
and `$CODEX_PRIMARY_RUNTIME_PYTHON`. For Streamlit, that site-packages spelling
matters; using the dependency target directly causes a devMode/server.port error.

Local stable rendering uses
`PATH=/workspace/scratch/0792453990a9/stable-lo/qa-bin:$PATH` with official Ubuntu
LibreOffice 24.2 and verified fonts. System soffice 26.8 alpha is nondeterministic;
do not accept it as a parity baseline. Local IPC restrictions require the QA-only
in-process LibreOfficeKit wrapper, which is not shipped. Production/CI use normal
LibreOffice CLI. Serialize local renders and use fresh output directories; an
existing output target can stall the wrapper. Do not run competing render agents.

No agent or experimental converter should remain active after this handoff. Start
by reading the owner's new production testing observations, then reproduce one
specific remaining defect at a time. Avoid a new broad swarm unless authorized.
