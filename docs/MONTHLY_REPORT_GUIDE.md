---
document_type: operator_guide
workflow: Monthly report
---

# Making a monthly report

Choose **Monthly report** at the top of Email Process Control. Select the contract,
the sites belonging in one report, and the reporting month. Several selected sites
produce one combined report. A region or group name is optional.

## Start or continue

Saved work for those sites and that month opens automatically. A new month starts
from the latest saved earlier report for the same sites.

Use the single **Starting report** upload for an older report, a report from
another site on the contract, or a partially finished current report. Word DOCX
files up to 128 MB are supported. The tool identifies the source sites and dates,
reuses appropriate information, and retains the original. It asks about a source
site only when the document does not identify it clearly.

An older same-site report supplies standing information. Current work is retained
when the body has already been updated, even if its cover is stale. Historical
tables remain available. Another site's report supplies layout, headings and
branding; its people, photos and work do not become this site's content.

Without a file, use the ENFRA master report design. Enter your name
and start the report. The tool remembers the design without a separate permission
checkbox. The name records the editor; it is not an authenticated login.

## Master page design

Every new report uses the saved ENFRA Word master, including reports started from
scratch. Its original cover, dividers, page settings, typography, tables and page
artwork supply the document design. Client logos and site photographs come from
the selected report's saved assets; another client's artwork is not inherited.

To update the master, open **Report → Advanced layout, shared assets and history**,
upload the new Word file under **New ENFRA master design**, and choose
**Update master report design**. This saves a new design version for future
reports across contracts without importing that file's monthly facts. Existing
saved reports retain their design version. **Apply current master to this report**
updates an existing report explicitly, retaining its content.

The live section preview and DOCX/PDF downloads use the same master renderer.
Unsupported source elements produce a specific error rather than a generic page
that silently loses the original design.

Deployment uses the verified LibreOffice 24.2 renderer and fixed font mappings.
The build checks both before allowing an image to ship, and CI renders reports
with the same configuration. Updating the renderer requires repeating the
completed-report visual comparison as well as the regression tests.

## Edit the report

Every standard section is included, including sections that are blank or waiting
for data. There is no section-inclusion checklist.

Choose the contract, reporting month and sites first, then enter your name.
The cover and every report section appear on one page in report order, separated
by clear headings. Update them as you scroll; there is no second section selector
or step navigator. Shared logo controls are not part of the asset-manager flow.

Each section has its own scrollable preview on the right. Previews are prepared
in a bounded background queue, so you can keep editing. Only the affected section
is refreshed after an edit; an older preview is not presented as the current one.
Review and download is at the bottom of the page.

### Shared information

The inline **Contract and site directory** shows the selected contract and all
selected sites together, with a row for each site and its editable contacts.
There are no duplicate contract or site selectors. Saved directory contacts fill
an empty report contact table after you enter your name.
Exact site names and confirmed aliases select the relevant site contacts;
contract-wide contacts remain labelled separately. Existing report contacts are
retained until you explicitly choose **Save contacts to directory and report**.
That action updates the current report table and preview; **Save progress**
persists the edited report. Other saved reports keep their contact snapshots.

Upload thermal capacity once for the contract. PDFs, Word files, spreadsheets,
CSV/text and supported images are accepted. Check the extracted values, units and
site matches, then save the capacity tables. All matched sites become available
to their asset managers, including on their first report. Separate steam and
chilled-water tables keep their original meanings and headings. Unclear site
matches or conflicting table structures need a decision; missing numbers are not
invented. Existing reports retain their saved/manual values.

Reviewed outage diagrams saved in the system supply shared ENFRA defaults across
contracts. Procedure changes are under **ENFRA outage procedures**. A different
site's later diagram does not silently overwrite an established standard.

### New files and pictures

Start Monthly Activity Summary by uploading the supporting work files. The tool
extracts supported facts and prepares the first summary, which you can edit.
Copilot analysis is visible in that section. Work-order spreadsheet entry remains
an optional checkbox. Blank, cover-only, standalone-logo/signature and legal-only
pages are excluded from relevant attachments; original files are retained.

Capital renewal accepts spreadsheets, PDFs, Word files and supported images.
Proposal uploads extract scopes and decisions into editable tables; original
quote pages and prices are not included in the monthly report. Missing facts
remain blank. For other source pages requiring a decision, use **Include page
and continue** or **Leave page out and continue**.

Previously reviewed, unchanged pictures stay reviewed. New or changed pictures
receive attention; use the optional all-picture editor when needed. The preview
on the right shows their placement. Keep only the pages useful to the client.

For suggested wording, check the linked facts and source pages before applying.
AI text and unreadable scans can contain errors. Correct unsupported numbers,
prices and outdated statements. Changing reviewed wording or its evidence can
require a new targeted review.

For carried issues or proposals, record whether the item remains open, changed or
was resolved, with the basis for that status. Open items carry forward automatically.
Monthly source files and completed activity start fresh in a new reporting month.

### Training

The training matrix has a row for each team member and columns for training
requirements. Status labels show Completed, Pending, Not required or Not recorded;
completion is never assumed. Changes to standing requirements are remembered for
the selected sites. The monthly training form records the topic, date, participants,
in-person/virtual/asynchronous format and optional known hours. Monthly events
remain tied to their reporting period.

## Save and download

**Save progress** stores unfinished work and editor attribution. Return to the
same sites and month to continue. If another editor saved meanwhile, compare the
versions before saving; neither person's draft is silently discarded.

At **Review and download**, correct specific problems with content that is present:
pricing, template instructions, unreviewed new pictures or AI wording, and
stale-month warnings. Blank sections are allowed. No blanket standing-information
confirmation is required.

**Generate DOCX and PDF** also saves a report version. Aim for files under 15 MB.
If PDF conversion fails, the completed DOCX remains available. The tool does not
send email.

Versioned master maintenance is in **Report design and version**. Asset managers
do not have shared logo replacement controls in the report flow. The directory's
full-workbook import saves usable contract and site contacts together, displays
excluded records, and avoids duplicate revisions on an identical re-import.
