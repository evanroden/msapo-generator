---
document_type: integration_release_checkpoint
date: 2026-10-09
base_commit: 63dc18ace500f680811db6c9979cf17b13d6a771
status: combined_release_under_validation
---

# Combined revision, conversion and Training reliability release

The owner asked to continue and release the three completed repairs together.
This integrates PR96 (final revision view/comments), PR97 (Writer process and
output isolation), and PR98 (Training-note retention). Their original commits
remain parents of the integration commit; no feature branch is squashed or
replaced. The only overlap is the documentation index, whose links are combined.
Application modules and regression tests are identical to the reviewed PR heads.

## Exact inputs

- Baseline: `63dc18ace500f680811db6c9979cf17b13d6a771`.
- Revision/comments: `bcfa882d2d06219795cbf80ec28d4d2974f480e5`.
- Writer cleanup: `4f5de54984eb810f97ff1de36bdca7a990676847`.
- Training notes: `7d5d819d2adf98e442781b6762e5fb93ac65c0cc`.

The offline checkout was restored to the full baseline tree
`c9913498215a0d723e954c5dca3f02aadfae8000` before applying these changes. Restoring
PR96 alone reproduced tree `23aba05da91394017396dd44cc671f3fba22f7a1`.
All changed application/test blobs are checked against the respective PRs.
The combined focused run passed 49 cases with no failures/errors/skips. Exact
combined full-suite counts, CI job IDs and release SHA belong in the release PR;
independent earlier branch counts must not be reused as combined acceptance.

## Gates and scope

Locked Python 3.12 dependencies and Streamlit 1.61.1 remain unchanged. Local
LibreOffice 25.2 is supporting evidence only; production 24.2/fonts, container
health and the 512 MiB / 0.5 CPU probe remain required CI gates. All original
regression tests remain enabled. No private reports, contacts, assets, runtime
objects or font binaries enter the public diff.

Current text must survive normalization, removed revisions/comments must not
return, and the current Training note/event data must survive validation. The
finished DOCX remains available when PDF conversion times out; the terminated
Writer job cannot overlap the next conversion or return a stale same-name PDF.
The full combined suite exercises these controls in the same application tree.

This is not a completion claim for the usability audit or F1-F8 review. Structural
tracked edits rejected by PR96 still need resolution in a source copy. Calc's
independent timeout launcher remains open. Activity reading, automatic active-work
retention, durable first-fill thermal/contact writes, native schemas and the
visible F12/F13/F15/F16 layout defects remain separate work. The standalone local
integrity patch series and unfinished WIP fidelity branch are not included.

## Verification and rollback

After merge, verify public health, the deployed version and non-destructive
report behavior. A successful merge/CI is not proof of public deployment. Report
any unavailable public-browser or version evidence explicitly; do not use private
Render workspace/log access as a substitute.

Rollback is a revert of the integration release's code. Keep saved business
records, original uploads, shared data, historical reports and immutable design
pins. Preserve an active cleanup marker until its recorded process group exits.
