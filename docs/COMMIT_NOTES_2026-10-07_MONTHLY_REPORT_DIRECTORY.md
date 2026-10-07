---
document_type: implementation_notes
date: 2026-10-07
base_commit: 29476cbc5ec0c43f2b01b19492561e44f24b6cfd
workflow: Monthly report
change_type: runtime_contract_directory
status: local_validation
---

# Optional contract/site directory

## Context

The owner supplied an XLSX whose detail tabs describe contracts, sites and
leadership/contact details. Use it to suggest explicit site identities and help
maintain a report's contacts. A worksheet title alone does not establish contract
membership, and two names for one facility remain aliases rather than two sites.
The directory is optional administration; the primary report flow stays simple.

## Implementation and safeguards

- Parse bounded sparse XLSX XML (30 MB upload, 80 MB expanded, 16 MB part, 50
  tabs, 100,000 cells). Formatting dimensions do not allocate a dense grid.
  Header scoring is linear in populated cells. Cached formula values are read;
  formulas, links, macros and embedded objects never execute or fetch resources.
- Suggest sites across columns and role/contact fields down rows. Preview the
  proposed sites, names, aliases, addresses and contacts before a shared save.
  Mark index/summary/hidden tabs; warn about copied site headers across contracts
  and tabs with no populated contacts. The operator selects the destination.
- Preserve identities when a renamed site is explicitly linked to an existing
  record. Omitted existing sites remain; deactivation retains history. Reject
  ambiguous aliases or two imported columns linked to one actual facility.
- Never attach an outgoing contact's telephone/email to a differently named
  replacement. Retain missing fields only for the same named person; show the
  old and proposed records for review.
- Version directory heads/history atomically with entered-editor attribution,
  explicit confirmation and expected-revision guards. Restoration adds a new
  revision. Store the workbook and directory only below monthly_reports/ on the
  persistent runtime disk. No directory data or private workbook goes into git.
- New report setup offers active saved sites without selecting them. Scope and
  regional membership still require confirmation. Directory updates do not
  mutate existing report profiles or snapshots, PO routing or expense routing.
- Existing reports can explicitly bind each facility to its directory identity,
  compare contact matrices and accept a report-only replacement, with undo.
  Saved reports pin the directory version used; new contacts never follow a
  moving directory head silently.

## Validation and what is not verified

Twelve synthetic tests cover sparse/formula parsing, unsafe XML/relationships,
cell budgets, contact mappings, aliases/identity conflicts, revision/atomic-write
guards, history/restoration, replacement-person details, explicit report bindings,
site choices and AppTest upload/preview/confirmation/save. The integrated complete
suite, including the latest section-review fixes, passed 834 tests with one
CI-only skip using real LibreOffice Writer and Calc. Exact-head remote CI remains
required before merge.

The actual supplied workbook was read outside git: 25 tabs, including 22 detail
tabs; all suggested header rows were located without allocating their formatting
dimensions. Generic warnings surfaced copied headers and an unpopulated contact
tab. These are suggestions, not owner-confirmed directory records. No actual
workbook was uploaded to production or saved as shared data during testing.

No directory PR, merge or deployment has occurred yet. Public deployment checks
and owner confirmation of real contacts remain outstanding. AI drafting/Copilot
and final report layout polish are separate increments. Entered names still do
not authenticate anyone; passcodes remain explicitly deferred.

## Rollback and unchanged behavior

The directory is additive runtime storage; restore a prior directory as a new
revision through its history controls. Reports and their snapshots remain pinned
until an operator accepts a contact-table replacement. Existing purchase-order
and expense account data and approval routing are unchanged.
