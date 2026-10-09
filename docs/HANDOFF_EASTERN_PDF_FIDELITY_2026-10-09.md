# Eastern PDF fidelity handoff

Status at the user's stop-and-deploy request: tested ordered UI and automatic busy-preview retry are ready. Eastern PDF fidelity is **not accepted as identical to the supplied PDF**. No version-five rendering profile was implemented. No conversion is active for this workstream.

## Tested code

- `app/monthly_report_section_preview_ui.py`: a busy shared converter retains the current preview snapshot, retries after the next bounded two-second poll, and never caches a permanent error. A newer edit invalidates the old result. Five focused ordered/busy tests passed in `tests/test_monthly_report_section_preview.py`. Parent has already snapshotted these changes.
- `app/monthly_report_render_headers.py`: isolated, **unwired** header suppression helper. It requires an exact header XML/media fingerprint and rejects shared or inherited content-page headers. It replaces only the approved header part and never body/footer content or native download bytes. Seven tests passed in `tests/test_monthly_report_render_headers.py`. Keep it explicitly experimental; automatic paired-reference calibration and underlying divider geometry binding are unfinished.
- No changes to `monthly_report_render_profile.py` were made by this workstream for version five. The other agent's tested version-four profile is independent.

## Real report evidence

Private scratch evidence root:
`/workspace/scratch/0792453990a9/layout-qa/additional-references/eastern/`

Original Word source:
`/workspace/scratch/0792453990a9/upload/RRH - Eastern Region August 2026  Monthly Report(2).docx`

Authentic PDF reference:
`/workspace/scratch/0792453990a9/enfra-layout-sources/RRH - Eastern Region August 2026 Monthly Report(2).pdf`

The reference has 39 pages. The unmodified stable Word conversion has 41 pages. The latest replay with both restored equipment inventory EMFs also has 41 pages. The earlier 39-page generated result was misleading: two missing inventory pages concealed two extra converter-generated pages. Matching page count alone is not acceptance.

Already verified:

- Both organization-chart SmartArt branches survive the real fresh-inspection replay. Source/current diagram XML parts are byte-identical. The generated organization-chart page is pixel-identical to the same-converter source. This is preservation proof, not complete authored-PDF fidelity proof.
- Equipment inventory image29.emf and image30.emf are restored in source order with exact source bytes. Full raster previews were visually reviewed and contain technical inventory, not monetary values. Their current approval used the real renderer-backed provenance path. CT's wrong PNG logo fallback was never approved.
- Current replay artifacts: `generated.docx`, `draft.pickle`, `mapped.pickle`, `production-render.docx`, and `production-pdf/production-render.pdf`.
- Other agents own divider text/color metrics, issue-heading wrap behavior, fonts, native assembly, and source import coverage. Coordinate before modifying those files.

## Hidden training header: proven defect, incomplete production integration

Actual reference page 35 has neither the ENFRA header overlay nor the blue placeholder overlay. The stable source page 37 has both. Suppressing only `word/header20.xml` removes both while preserving the underlying divider artwork.

Evidence: `header-visibility-evidence.json`, `header-visibility-0.png`, `header-visibility-1.png`, `measure_header_visibility.py`, and `header-line-auto-pdf/header-line-auto-candidate.pdf`.

The two image strips show authentic PDF, original conversion, then header-cleared conversion. At 144 dpi, mean absolute RGB error against the actual reference improves:

- Blue placeholder rectangle: 111.5143 to 1.5689.
- ENFRA logo rectangle: 24.1602 to 0.6851.

Source and current official generated packages resolve the same header fingerprint:
`f8b18e2739e9bac9c13087d09bee0fd215c988fa51c2954932cd110ba52181f6`.

The helper selects only this header in both packages. The next section explicitly uses header21; inheritance protections are tested. However, safe owner-install calibration must additionally bind the underlying divider composition and prove the same improvement against a uniquely matched supplied PDF page. Missing PDF image metadata does not establish absence, because logos can be vectorized.

Prepared but **not rendered or accepted**: `isolated-header-original.docx`, `isolated-header-suppressed.docx`, and `isolated_header_candidates.py`. No v5 schema or rendering hook exists. Do not ship unconditional header suppression.

## Two extra pages: grounded hypotheses, controls not run

Detailed source inspection: `boundary-audit.json` and `boundary_audit.py`. All body indices below are zero-based.

1. Extra blank stable page 24, before equipment divider page 25 (actual divider page 24). Body720 contains four nearly page-height inline water-treatment images. Body721–731 are eleven empty 10-point paragraphs. Divider732 includes an explicit page break and its section boundary. This is already present in unmodified source conversion.
2. Extra blank stable page 34, before proposals divider page 35 (actual divider page 33 after accounting for the earlier blank). Body760 contains many empty floating shapes, all wrapNone except a proven invisible Rectangle50 with wrapTopAndBottom. Its section ends762. The next paragraph763 contains upward-offset proposal background pictures. Existing invisible-frame compatibility only addresses a same-paragraph collision, so this distinct cross-section pattern is not covered.

Prepared but **not rendered or accepted**: `tail-wrap-candidate.docx` changes only that proven invisible frame to wrapNone; `water-empty-candidate.docx` changes only those eleven empty paragraph line heights, without deleting paragraphs; `boundary_candidates.py` reproduces both. Their serial converter slots were cancelled at the user's stop request. Do not generalize either change without positive page/geometry controls.

## RFI table: quantified converter differences, no fix

Actual pages38–39 correspond to unmodified stable pages40–41. The table's first top border is y92.40pt in the actual PDF versus80.00pt in LO. Its continuation starts at51.84pt versus38.75pt: an approximately13pt origin deficit on both pages. Actual body row pitch is20.45pt; LO is19.95pt, causing cumulative drift.

A scratch border-inclusive row-height candidate partly corrects pitch. The continuation changes from starting at Resiliency Strategy to Temporary CHW/Electrical Plans; the actual PDF starts one row earlier still, at One-Line Diagrams. Therefore the row-height candidate alone is not accepted. Header paragraph explicit line-height controls produced no geometric improvement and were rejected.

Source RFI follows an explicit page break and a continuous two-column-to-one-column section transition. Header distance changes from432 to720twips; body top margin is720twips. Header21 is a floating-image-only, text-empty Header paragraph. Word reserving a line box that LO collapses is a remaining hypothesis, not a proven fix. Do not globally change row heights: an authentic UMMC reference was authored by LO and must retain its validated geometry.

Evidence: `rfi_border_candidate.py`, `rfi-border-candidate.docx`, `rfi-border-pdf/rfi-border-candidate.pdf`, `header_line_candidates.py`, `header-line-auto-pdf/`, `header-line-exact-pdf/`, `geometry_audit.py`, `authentic-generated-geometry.json`.

## Resumption order

1. Preserve tested production release and the user's new acceptance observations.
2. Run the two pending source-only blank-page controls serially with a fresh output directory and the agreed production font profile. Compare all affected pages and confirm no content disappears.
3. Implement hidden-header paired-reference calibration only after isolated original/suppressed divider renders reproduce full-document paint. Add source/divider/media binding and negative ambiguity tests before any profile hook.
4. Continue RFI section/header origin investigation separately from row-pitch correction. Validate actual authored PDFs, not only same-converter baselines.

No broad empty-paragraph deletion, false asset approval, source-specific hardcoded suppression, or global layout offset is authorized by these findings.
