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

## Validation checkpoint

65 focused branding/storage/start/UI/section/hygiene/docs tests passed. Ruff
F/E9 and git diff --check passed. Full-suite, real-report walkthrough, final
logo collection, exact-head remote CI and production installation are pending
at this checkpoint. Do not describe this as released.

## Logo research and recovery

The official-source research and originals are outside git in
`/workspace/scratch/monthly-report-branding-research`. Source discovery has
identified newer names/marks including Powers Health, Manning Family Children's,
LSU New Orleans and FMOL Health. Coverage and rendered-logo review are still
in progress; no missing brand should be invented or silently substituted.
SVG originals are converted outside the app to reviewed PNGs. The app accepts
only the final bounded bundle. Never add source artwork, private client files
or runtime contents to git.

After validation and merge, install the reviewed public-logo collection through
the public app UI. This is the owner-requested shared branding update, not a
private report smoke test. Public Render verification only; no private logs,
workspace selection or disk APIs. The collection can be restored in the UI.

## Previous release now verified

First-use PR #69 head 69228f39844d6fe1d827c8b740ddd01c3438d646 passed Actions
37693409691 (job 113038952193), 881 tests with zero skipped, and merged with
expected-head protection at d7f1d0df33cfb9438d5058a7da9109923b124270. Public
production showed the new site-matching column after a synthetic workbook
upload/read; no persistent directory/profile was saved. The screenshot proof
is outside git.
