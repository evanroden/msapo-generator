---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 7e2e4d0d1c4df8b415a27b6867283a3353ba5fc4
status: focused_tests_passed_pending_ci
---

# Shared contacts in reopened and rolled-forward reports

A saved report could retain an obsolete copy of the shared directory even after
another editor updated that same site's contacts. Empty first-use reports loaded
shared contacts, but existing directory-backed copies did not refresh.

The working report now refreshes an unedited directory copy. It verifies the
original directory revision, exact rows, canonical columns, contract identity
and explicit site links. It does not infer a replacement from names. Manual
edits, unrelated source references, omitted sections, archived/retired sites,
ambiguous links and missing historical proof stay unchanged. A deliberate
contact deletion from a still-matched active site removes the old person from
an otherwise unedited working copy.

Refresh changes only the current working draft. It clears that contact editor's
obsolete widget delta so it cannot write the old rows back over the refresh.
Saved report files, directory history and unrelated sites are not rewritten.
Save progress remains the action that stores the revised report version.
The existing named shared-directory save still supplies the standing contacts;
no second routine confirmation is introduced to read its latest revision.

## Tests and release gate

Three fresh pre-fix assertions failed for rollover, reopened working copies and
explicit shared deletion. Nine negative controls passed. The corrected pure
suite passed all twelve; the seven existing/new selected-directory UI tests also
passed, including preview refresh after another editor's shared update and
preservation of the saved snapshot. Exact-head full production CI, renderer/font
checks, container health and the inherited 512 MB resource probe remain required.
Record actual final run IDs and counts in the PR rather than extrapolating from
focused or earlier tests.

## Deliberate limits

This does not promote edits made in the lower report-only contact table into the
shared directory. The existing directory-save control remains the shared write
path. Imported/unlinked contacts and unpublished manual edits are not silently
reclassified as directory defaults. No native table-schema change, thermal
portfolio population, subcontractor/capital/training reuse, cover or remaining
PDF-fidelity remediation is included in this commit.

There is no storage-schema migration, authentication/hosting change, deletion,
source mutation, review bypass, PO-routing change or expense-policy change.
Rollback is a code revert, not a rollback or deletion of business data.
