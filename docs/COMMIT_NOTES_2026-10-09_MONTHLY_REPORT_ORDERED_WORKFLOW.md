---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: a26c691c0b427c2373a902a72c3f4b728b3c595c
status: validation_in_progress
---

# Ordered monthly report workspace

The owner's Unity/USH walkthrough found redundant navigation, unrelated directory
selection, prominent logo controls and missing upload-driven workflows. Exact
ENFRA page design remains the first priority. This follow-up retains the native
renderer and replaces the AM navigation with a single page in report order.

## Implemented behavior

- Contract, month and sites precede the inline directory. Selected sites appear
  together; revisions and editor attribution guard shared saves.
- Cover and every section have adjacent native previews. All eleven core sections
  remain present; source designs retain their RFI or Accounts Receivable appendix
  and actual section order. A bounded worker
  serializes conversion, discards stale results and stops fragment polling after
  work completes. Edits do not wait for all sections to render.
- Shared logo replacement and the legacy low-resolution preview download are
  absent from the AM flow. Infrequent versioned master maintenance remains.
- Monthly activity starts with supporting files, grounded first-pass wording and
  visible Copilot. Work-order entry uses a checkbox. Native facts, async reading
  and deduplication preserve AM edits. Reader requests are bounded and cached;
  the explicit bulk-reader allowance is separate from legacy manual OCR.
- Capital and proposals accept native tables and PDF/image reading. Missing facts
  are not invented. Quotes are reduced to price-free editable details; original
  quote images never enter the output.
- Training uses a single editable matrix with colored status indicators and a
  form for dated in-person, virtual or asynchronous events. Standing state is
  versioned per site; monthly events do not carry silently into another month.
- Unreadable photo uploads are caught and staged atomically. Previous photos and
  edits survive a failed batch. Real UMMC/Unity photo-add/caption/native-DOCX
  probes passed; the user's valid-photo crash was not reproduced exactly.
- Legacy imported profiles retain their source design ahead of the global master.
  New profiles use the master; explicit saved design pins remain authoritative.
- Explicit inline contact saves also update the current report's contact table
  and preview. Other report snapshots remain unchanged; normal Save progress
  persists the edited report. Opening the directory does not replace contacts.
- Native continuation preserves linked headers, supported visible JPEG/PNG image
  effects, unchanged cover typography and same-report issue dates. Import
  provenance takes precedence over image proportions when binding cover assets.

Named-editor requirements provide attribution, not authenticated authorization.
Master maintenance remains in its collapsed design/version control; deployment
does not introduce a new authentication system.

## Validation checkpoint

PR #91 checkpoint `8ff301ef1c334bb5dab3d157f67f147e826ad53b` passed
1505 tests with zero skips in Actions `37938836694`; container build/health
also passed. Later cover, training, named-contact display and explicit master
switch fixes require final-head CI before release.

September native continuations now pass against their supplied Word sources
rendered by LibreOffice 24.2 with the verified fonts:

| Report | Source/output pages | Pixel-identical pages | Remaining differences |
| --- | --- | --- | --- |
| Unity/USH September | 39 / 39 | 37 | Three Cost labels on pages 28 and 32 |
| UMMC September | 39 / 39 | 37 | Three Cost labels on pages 29 and 32 |

Both have zero changed pixels outside the intentional label redactions. This
measures source-to-generated fidelity under the same renderer, not equivalence
to a Microsoft Word export. Unmodified Portland, RGH and Central CT sources
already exhibit converter-specific artwork or pagination defects; these remain
documented limitations, not passing evidence of authentic Word/PDF fidelity.

Focused ordered save/resume/generation tests passed, as did extraction/pricing,
manual-edit protection, selected-directory, training and asynchronous preview
regressions. The initial full local run began before all retired-navigation test
adaptations were complete, so any result from that run is a checkpoint rather
than final-head acceptance. Final fresh CI must cover the complete tree.

The supplied September Unity/USH and UMMC reports are the current-month
continuation cases. Other supplied AH and RRH/Central CT reports broaden layout
coverage. Their private source files, prepared replay data and rendered outputs
remain outside Git. Asset review must be based on actual visual inspection;
pricing, standalone signatures and template instructions are separate deliberate
omissions, not excuses for unmeasured layout changes.

PR #90 is already live with the UMMC master installed as version 1 through the
public app. This follow-up is not yet deployed.
