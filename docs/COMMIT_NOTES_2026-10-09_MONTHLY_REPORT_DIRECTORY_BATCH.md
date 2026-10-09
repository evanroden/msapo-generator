---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 2131de2a295c97d3b98a0310e79263a464da1db6
status: production_validation_in_progress
---

# Shared contact workbook import

The monthly report directory now supports a reviewed import of all usable
contract and site contacts in one workbook. Contract-wide contacts are stored
separately from site contacts; summary-only contracts do not acquire invented
sites. Existing reports and their selected facilities remain unchanged.

The import uses explicit contract/site aliases, retains source cell references,
preserves existing records, and blocks conflicting populated values. Each save
checks the revision reviewed by the editor and verifies the saved result. A
repeat import of identical content creates no new revisions. Inactive, empty,
unrecognized and ambiguous records are displayed as exclusions.

Literal zero contact cells are treated as empty. Sustainability Sales rows are
recognized alongside the existing leadership and operational contact roles.
Contract contacts participate in history, restore, archive and report contact
suggestions without becoming a site's contacts.

Validation: 76 focused backend/UI regressions pass. The supplied workbook was
also imported into an isolated temporary directory: 40 contracts, 108 sites,
161 contract-wide and 394 site contact assignments. All 40 saved records were
verified; a second import returned 40 unchanged records and no writes.

The workbook and all personal contact values remain runtime data and are not
included in the repository. Production import is a separate UI action after
the deployment is verified.
