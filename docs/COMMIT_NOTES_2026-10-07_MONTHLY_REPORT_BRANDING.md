---
document_type: commit_notes
date: 2026-10-07
status: deployed
commit_intent: Add reviewed runtime logos and visual monthly report setup
base_commit: d7f1d0df33cfb9438d5058a7da9109923b124270
---

# Monthly report: reviewed branding and visual starting choices

## Why

Asset managers should recognize their contract and choose a starting report
visually. They should not need to find client logos themselves or interpret
identical generic controls for very different report sections.

## Current implementation

- PNG-only reviewed logo bundles carry explicit contract mappings, source URLs,
  review dates and content fingerprints. Parsing has compressed, expanded,
  member-count, image-byte and pixel limits. No external resources are fetched
  by the app; SVG/scripts/extraneous ZIP members are rejected.
- Atomic shared manifests have revision guards, entered-editor attribution and
  append-only history with explicit restoration. Artwork is stored only under
  EPC_DATA_DIR/monthly_reports/branding. No artwork is committed.
- Contract cards use shared client logos, with saved-profile logos as fallback.
  New designs fill empty ENFRA/client logos and copy those bytes to the report's
  own library. Existing custom logos, explicit omissions and snapshots stay
  pinned. Site information offers a visible, deliberate replacement.
- Starting choices are cards: another same-contract report when available,
  ENFRA template, or an older/unfinished Word report. Nothing is saved merely
  by selecting a card. Site selection, original report retention and free
  navigation remain unchanged.
- Section review uses specific action labels, text/picture fields and guidance
  for organization, activity, scorecards, MBCx, maintenance, vendors, water,
  issues, capital, proposals, training and RFI. Organization replacements can
  target the chart, either outage workflow or facility contacts. Existing
  review-plan action values remain compatible.

## Validation and publication

The full local suite passed **886 tests, one CI-only skip**, including real
LibreOffice. Ruff F/E9, compileall, dependency consistency and diff checks passed.
The initial full run caught missing notes metadata and a test still using the
previous starting control; both were corrected before that final full run.

A local AppTest installed the reviewed public bundle through its confirmation
flow, checked all 37 contract mappings, created a general-template report with
both client and ENFRA logos, and exposed the same-contract starting card only
after a report existed. A five-page synthetic DOCX/PDF was rendered, the cover
was visually inspected, and identical inputs produced identical DOCX bytes.
The new logos correctly required image review before finished output.
A subsequent header inspection found card padding made the printed ENFRA mark
too small. Screen cards now use a separate presentation canvas while print
assets retain their natural proportions and clear space. After that fix,
**56 focused tests passed**; the installation/first-use/render walkthrough was
repeated and the corrected header visually inspected. This is full run plus
focused follow-up, not a combined full-suite count.

PR review found two integration edge cases: seeding another site's design could
lose an explicit logo omission, and first-time DOCX setup did not fill missing
logos. Both are corrected with regression coverage, including persistence,
custom uploaded logos and subsequent imports. Contract grids now load the
branding manifest once and decode each shared asset once per render. After
these corrections, **78 focused tests passed**; Ruff F/E9 and diff checks passed.
The preceding head abcd42bd47b02669b364fc55c3303d1830a7fe73 passed Actions
37698370119; that is not the corrected head's CI result.

The supplied private Glendale report was walked through locally again using
the upload card: 265 extracted items became 13 section cards, every card opened,
and a text edit survived closing/reopening. Existing drawing/content blockers
remained. Original files were unchanged and no private production upload was
used. Hardware phone/iPad acceptance remains unclaimed.

PR #70 final head `95be0a338be3fc0a366da02f401c317bc1d4b40e`, tree
`9843c459efbc22e2d1e95ec6cd59a8d87a73c250`, passed Actions `37699022024` /
job `113057727580`: **893 passed, zero skipped**. Logs verified that head
merged into unchanged main `d7f1d0df33cfb9438d5058a7da9109923b124270`.
All changed blobs and the assembled tree were hash-verified; a fetch and
zero diff proved local/remote equality. The PR merged with expected-head
protection at `21d1c27122a3f355565eb5cb4b19e9518bc5015c`.
Public production showed the new shared-logo controls after deployment. The
reviewed bundle was installed through the confirmation UI as collection version
**1**, entered actor **Codex (owner-authorized logo setup)**, at
`2026-10-07T22:58:54.142195+00:00`. The save confirmation and history were visible.
All 37 contract cards then showed their mapped logo. The public first-report
flow showed site checkboxes, September 2026 as the suggested period, the ENFRA
logo card and upload card; an unavailable same-contract choice was absent.
Nothing was saved by selecting a site. Public health returned 200;
an initial connection error during rollout cleared after reconnecting.
No private report, persistent QA profile or private Render access was used.

## Reviewed logo collection and recovery

The collection contains 30 marks (including ENFRA), explicitly covering all 37
listed contracts. Original colors/proportions are preserved, empty margins are
trimmed, and clear space is added. Screen cards use consistent frames while
printed logos keep the appropriate shape for their document positions. White marks use a dark
background. SVG/animated originals are not executed by or uploaded to the app.
A static official Memorial Health image avoids the incomplete first frame of
its animated header. PNG pixels are bounded and fingerprinted.

Source dates and URLs are stored with each runtime logo. Current official pages
verify newer identities including Powers Health, Manning Family Children's,
LSU New Orleans and FMOL Health. System logos serve relevant contract groups;
they never infer report membership or overwrite a site-specific logo. FMOL's
official download service returned 502 errors; its current mark was checked
against the official company page and rebrand announcement, with the matching
artwork taken from its public employer profile. That exception and artwork URL
are explicitly recorded in the collection, not labeled as a direct official
download. No brand artwork is committed to git.

Local research, provenance manifest, reviewed logo contact sheets and bundle:
`/workspace/scratch/monthly-report-branding-research`.
Final bundle: `enfra-client-logos-2026-10-07.zip`.
AppTest/renderer proof: `flow-result.json`, `synthetic-branding.docx` and
`synthetic-branding.pdf`. These are QA intermediates outside git.

Installed bundle SHA-256:
`155dee58f39e42d253e7d23b5523ec2a07dbb46f0be09c07ca86ffd65262c7a1`.
Public installation/card screenshot proofs are outside git at
`/workspace/scratch/monthly-report-logo-install-r1.jpg` and
`/workspace/scratch/monthly-report-contract-cards-live.jpg`; the complete
starting-choice proof is `/workspace/scratch/monthly-report-start-cards-complete.jpg`.
The collection is now persistent under EPC_DATA_DIR/monthly_reports/branding;
the UI retains source links and restoration history. This was the authorized
shared public branding update. No private logs, workspace selection or disk API
was used. The reviewed bundle can be installed again after runtime recovery;
existing report snapshots retain their pinned assets.

## Previous release now verified

First-use PR #69 head 69228f39844d6fe1d827c8b740ddd01c3438d646 passed Actions
37693409691 (job 113038952193), 881 tests with zero skipped, and merged with
expected-head protection at d7f1d0df33cfb9438d5058a7da9109923b124270. Public
production showed the new site-matching column after a synthetic workbook
upload/read; no persistent directory/profile was saved. The screenshot proof
is outside git.
