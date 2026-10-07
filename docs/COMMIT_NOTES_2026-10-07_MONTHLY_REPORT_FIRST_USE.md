---
document_type: implementation_notes
date: 2026-10-07
base_commit: 051e627b554d09008168b0fbb7234fd0d2beeb5d
workflow: Monthly report
change_type: first_use_contact_reuse
status: tested_for_publication
---

# Reuse reviewed site contacts during first setup

A partial workbook import previously replaced the entire list of selectable
catalog sites. The supplied workbook omits some sites already known to the app,
so this could make a legitimate site disappear. Directory records now supplement
the catalog. An explicit inactive record suppresses its uniquely matched catalog
entry. Exact identities and unique name/confirmed-alias overlaps avoid duplicate
choices; ambiguous overlaps remain visible. Existing report identities, saved
membership and profile revisions are unchanged.

On first directory import, the editable matching column now includes known
catalog sites. An operator can link a different spelling to an existing identity
and review the alternate names. Proposed matches retain known aliases visibly
in the table. Omitted catalog sites are not silently written to the directory.
Report contact review suggests only unique exact name/alias matches, reserves
confirmed links and does not retarget retired links. It still shows the old and
new contacts and requires an explicit, content-specific replacement confirmation.

An editable org chart can start from this report's contact fields. The operator
chooses people/positions and then supplies reporting lines. The tool never infers
management hierarchy, reads another site's directory, or copies phone/email
columns into chart nodes. Imported extra tables retain independent schemas;
unknown/ambiguous schemas remain editable contacts rather than guessed people.
Identical positions are deduplicated, separate roles/sites stay separate, and the
60-position/100-character bounds remain visible. No contact text is silently
truncated. Replacing an uploaded chart still needs the explicit replacement
checkbox, and original assets/history remain recoverable. Navigating between
steps and saving/resuming keeps the selected people and report contacts.

The full local suite passed **878 tests, one CI-only skip** with real
LibreOffice. After the final picture-read recovery change, **98 focused tests**
passed (import, directory, visual/UI/section flows, public hygiene and docs).
These are separate runs, not a combined full-suite total. Ruff F/E9, compileall,
pip check and diff checks passed. The actual private 25-tab workbook was exercised
through local AppTest: seven reviewed directory sites, nine available report
sites, two explicitly linked spelling variants, four chart positions, saved and
resumed activity/people. No reporting hierarchy was inferred. The original
workbook stayed unchanged and all runtime QA files stayed outside git. A copied
site list on another contract tab remains a visible ownership warning; it was
not imported into production. An additional actual DOCX walkthrough opened all
13 section cards (265 extracted items), retained an activity edit across closing
and reopening, and kept content-review blockers visible. Its extracted-picture
contact sheet was visually inspected outside git. The first attempt hit a
transient staged ZIP read failure; an isolated retry passed. The precise cause
was not established. A damaged/unavailable staged picture now gives an actionable
re-upload message and blocks section approval instead of an uncaught exception;
the original/saved versions and other section controls remain intact. A synthetic
truncated-package regression covers this recovery path.

Rollback: revert this code/UI increment; no schema migration or runtime rewrite
is required. Older code can still read the saved chart nodes, contact tables,
directory records and snapshots. PO/expense behavior and client-content gates
are unchanged. No private Render access, paid model call or production client-data
write is part of this validation.
