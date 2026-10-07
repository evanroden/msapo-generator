---
document_type: implementation_notes
date: 2026-10-07
base_commit: 99cdd2a688bae623d171bbba53a64ee6e59c8139
workflow: Monthly report
change_type: site_first_setup
status: tested_for_publication
---

# Site-first report setup

The owner found a dropdown containing only an upload option confusing. A new
asset manager should choose a contract and the actual sites in one report, then
choose a starting design. Returning users should resume the same site combination.

Contract cards replace the contract dropdown, with a search field and confirmed
runtime client logos when available. No unverified logos or private workbook data
are added to git. Returning browser preferences keep the chosen contract visible.
Site checkboxes explain that multiple selections combine sites in one report;
separate reports require separate runs. Optional names and explicit regional
scope are remembered with the saved profile. Membership uses identity keys,
not titles. Group renaming preserves identity and requires an attributed,
revision-guarded confirmation.

New membership offers a report design from the same contract, the general ENFRA
section template, or an older/unfinished DOCX upload. Reusing a design preserves
section order, titles, table schemas and saved contract branding. It deliberately
clears other-site contacts, org charts, photographs and monthly narrative/pages.
This is a new report design, not permission to treat another site's facts as this
site's facts. Existing source reports remain unchanged.

New design heads are published atomically only after immutable assets and the
working seed are durable. Confirmation and entered-editor attribution are required;
a concurrent creation produces a revision conflict. Latest earlier snapshots
are used even if reporting skipped a month. Standing information and one-off
standing images carry forward; monthly attachments/text are cleared for a new
period. Site setup lands in the standing-information step, with direct logo,
cover/footer controls. Workflow steps remain freely selectable and preserve edits.

Validation: 22 initial focused backend/AppTest cases passed, including group
creation, general template, original upload, naming/aliases, retained partial
work, revision conflict, asset integrity, and interrupted reporting. Final full
local suite: **840 passed, one CI-only skip**, with actual LibreOffice. Ruff F/E9,
dependency consistency and diff whitespace checks passed. A regression also
checks that standing review invalidates for logo changes without invalidating
merely because the same image received its client-content review.

Two supplied large DOCX reports were walked through locally using the actual
new contract-card/site-selection/upload flow. All 12 and 13 section cards opened;
an activity edit survived closing/reopening. Expected content-review blockers
(including unsupported drawings) remain visible, not silently approved. The
originals and private preview sheets remain outside git and production. These
walkthroughs do not claim a completed client output or owner acceptance.
Exact-head CI and public deployment checks remain before release.

Structured org-chart editing, clearer contact fields, live page/photo layout
preview and final mobile/tablet verification are still to follow. M5 drafting is
checkpointed separately in draft PR #61 and is not part of this release.
