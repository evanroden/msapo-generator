---
document_type: code_review_and_remediation
base_commit: 077c656918688169d3538bdd3d5789c664f60595
date: 2026-09-24
status: verified_release_candidate
---

# September 24 code review and corrections

## Scope and verdict

Reviewed current `main` at `077c656`, including the six commits since `399d258`
(five changed files, 404 additions and 24 deletions). Those commits repaired
freight reconciliation and the PDF scanned-page budget. The review also traced
their surrounding amount parsers, PO context/hand-off validation, draft mirrors,
receipt prefill/item selection, and background-result lifecycle. This was a
targeted correctness review, not an exhaustive audit of every project module.

Five defect groups were reproduced and corrected on
`fix/code-review-2026-09-24`. The owner subsequently authorized publication to
`main` and deployment. This note records the verified release candidate;
post-publication CI and deployment evidence will be reported with the release.
No real financial submission or paid model request was made during validation.
Authentication and public request-rate limiting remain excluded under the
owner's earlier direction.

## Findings and fixes

| Priority | Reproduction and consequence | Correction |
|---|---|---|
| High | `parse_amount("123,45")` returned `12345`; malformed grouping and embedded dollar signs were deleted before validation. A typo or decimal-comma amount could change the payable amount rather than being rejected. | Validate comma grouping and currency-symbol position before normalization. Preserve conventional USD forms, decimals, sign handling and zero. All consumers of the shared PO parser receive the correction. |
| High | A CAD/EUR receipt showing `100.00` prefilled `100.00` into the USD reimbursement field. A visible currency error did not stop the prefill, and item-selection arithmetic reused the unconverted prices. | Known non-USD receipts require manual approved USD entry. Disable unconverted item-selection calculations, label printed tax with its actual currency, and avoid comparing USD split totals with a foreign printed total. Preserve manually entered USD values, even if they precede the delayed result. No exchange rate is guessed. |
| High | A native-text heading above two scanned image strips was treated as a native page because neither individual image covered half the page. The extracted quote silently omitted the scanned scope/pricing. | Measure the union of visible image coverage, using the unrotated coordinate space and page clipping. Count overlapping logos once. Tests cover 0/90/180/270-degree rotations and overlapping decorative images. |
| Medium | Lowering a corrected total below an incorrectly extracted subtotal/tax allowed PDF rendering and then blocked the hand-off. Neither component had an editable UI field. Malformed or negative optional components could also disable reconciliation. | Add optional net-subtotal and sales-tax controls, expose them when invalid, preserve them across workflow switching, and share validation between the pre-render gate and `POContext`. Invalid nonblank values block; legitimately unstated components may remain blank. |
| Medium | A PDF whose already-known native text exceeded the character limit still triggered paid OCR for scanned pages before rejection. Native pages were decoded three times by the pre-count and reading loops. | Build one page plan, decode each native page once, check the known native-text budget before any OCR, and enforce the combined result budget as each part arrives. Stop before later OCR requests when the assembled text exceeds the limit. |

## Important behavior preserved

- The reported Grainger freight example still passes: subtotal 513.45, freight
  209.00, tax 57.80, total 780.25. A total larger than subtotal plus tax is not
  rejected merely because freight or other fees are not separate schema fields.
- Reconciliation still rejects a total smaller than the reviewed net subtotal
  plus tax beyond the existing one-cent tolerance. A subtotal before discounts
  can now be corrected to the net subtotal without changing the approved total.
- Quotes with more than 20 native-text pages remain supported. The 20-page
  vision limit applies to scanned pages, counted before requests begin.
- Original quote and receipt attachment bytes remain unchanged. PDF raster
  copies are only analysis inputs; operators are not told to split a vendor
  quote to satisfy the tool.
- No changes to routing catalogs, agreement types, Object Account options,
  mileage rates, workbook formulas, document templates, dependencies, database
  schemas, or persistent deployment configuration.
- Receipt reading remains bounded and asynchronous. Human-entered reimbursement
  amounts survive delayed analysis and workflow changes.

## Implementation map

| File/function | Responsibility |
|---|---|
| `app/po_rules.py::parse_amount` | Strict grouping/symbol validation; normalize only after a valid complete match. |
| `app/po_context.py::pricing_problems` | Shared optional-component and one-directional reconciliation checks; `build_po_context` uses the same helper. |
| `app/web_ui.py::main` | Seed/render editable subtotal and tax, promote errors to visible questions, block generation before document rendering. |
| `app/workflow_state.py::preserve_po_draft` | Include the active quote's `sub_` and `tax_` values in the scalar draft mirror. |
| `app/expense_ui.py::_foreign_receipt` and receipt render/seed/sync paths | Keep foreign source amounts out of USD prefill and item calculations. |
| `app/ocr.py::_images_cover_half_page` | Union of clipped image rectangles, with rotation-correct bounds. |
| `app/ocr.py::extract_text_from_pdf` | Reusable page plan, native-text preflight, incremental combined-text budget. |
| `tests/test_review_2026_09_24.py` | 34 adversarial cases, including real Streamlit AppTest lifecycles and synthetic PDF layouts. |

PyMuPDF documents that image/text coordinates are unrotated while `Page.rect`
reflects rotation. The coverage implementation therefore transforms the page
bounds through `derotation_matrix` before clipping image rectangles:
[PyMuPDF Page coordinate conventions](https://pymupdf.readthedocs.io/en/latest/page.html).

## Verification

- Clean current-main baseline: **559 passed, 3 expected skips**.
- Initial new adversarial suite: **20 failed, 9 passed**, before corrections.
- Focused money/context/OCR/freight/draft suite after corrections: **159 passed**.
- Expanded regression matrix: **34 new cases**, including rotated scans,
  combined-text overflow and an already-entered USD amount arriving before OCR.
- Full corrected suite: **593 passed, 3 expected skips**, with no deselections.
- Python compilation, `pip check`, changed-file Ruff E9/F checks, and
  `git diff --check` passed.

The skips are the two LibreOffice import-filter-dependent renderer cases and the
CI-only environment assertion. Remote CI and Render deployment are pending at
commit preparation. Existing render/input/state tests use
synthetic inputs and mock network responses; the live model's extraction quality
is not independently measured here.

The extraction performance claim is structural, not a production latency claim:
the four-page regression now observes four native-text decoder calls, versus
twelve before the correction. Actual latency depends on PDF structure and OCR.

## Remaining limits and release handoff

- Image coverage remains a conservative OCR heuristic, not proof that every
  possible document layout has been transcribed completely.
- There is still no dedicated freight/fees/discount schema or complete line-item
  accounting reconciliation. Operators must review the all-in amount and the
  newly editable net subtotal/tax against the original quote.
- Unknown currency retains existing behavior; the no-prefill protection applies
  to currencies explicitly identified as non-USD. No bank-conversion data exists
  in this tool.
- A release should run renderer-equipped CI and then a live smoke test of quote
  price correction, workflow switching and delayed receipt reading.
- Reverting these six application-file changes requires no data migration.
  Existing drafts remain session-only; preserve completed work before deployment.
