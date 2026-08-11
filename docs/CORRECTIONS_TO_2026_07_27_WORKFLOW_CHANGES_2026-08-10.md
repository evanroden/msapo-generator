# Corrections to the 2026-07-27 workflow changes (C1–C8)

**Requested PR title:** `Corrections to the 2026-07-27 workflow changes (C1–C8)`
**Correction date:** 2026-08-10
**Branch:** `agent/rrh-unified-brand-mobile-2026-08-09`

## Repository drift and application method

The supplied directive targeted `main` at `5a03b86`. That Git object is not
available in this checkout; `main` is the later snapshot `a67ddaa`, followed by
the approved streamlined workflow checkpoint `b594d76`. The original C1/C4
line anchors therefore no longer matched. Each correction was applied to the
equivalent current path without restoring the superseded step layout.

## Correction commits

| ID | Severity | Commit | Result and acceptance evidence |
|---|---:|---|---|
| C1 | Critical | `c452bde` | Confirmed contract/site are mirrored outside widget state, restored after widget garbage collection, and cleared with the quote. Tests prove a confirmed non-RRH route wins over an RRH detection and first-pass detection still works. |
| C2 | High | `48bebdb` | Normalized HEIC/TIFF/BMP frames are bounded to a 1568-pixel long edge and under 5 MB. Small images are explicitly protected from Pillow upscaling. |
| C3 | High | `c26df61` | Tax/category/assumption hints are normalized conservatively, trailing remarks no longer discard complete JSON, malformed JSON still fails, and one malformed model response is re-rolled. All eight supplied deviations are covered. |
| C4 | High | `612e7e2` | The current analyzed-quote path has no early return after review begins. Package invalidation occurs after all operator-editable fields render. An AppTest confirms a typed total survives a site change. |
| C5 | Medium | `0b822c9` | Blank cost code disables generation and displays a warning. Every RRH site must have an automatic letter or an explicit manual-entry decision; Unity Specialty remains manual pending Appendix A evidence. |
| C6 | Medium | `a502ef2` | Legacy output cleanup runs once per process. The active workflow already stores both attachment payloads as bytes, so its former `exists()`/`read_bytes()` TOCTOU path is absent. |
| C7 | Low | `29604b1` | Webhook-era filtering/default code is removed, reviewed lists are the DOCX boundary, and mirrored contracts are checked against configuration. Testing caught and fixed an invalid-contract site residue. |
| C8 | Low | `299e8dd` | Legacy-removal checks use absolute repository paths. Test imports and all assertions behave identically from the repository root and `tests/`. |

## Related completed changes

- `b594d76` — streamlined three-step workflow, editable Scope field, account and
  vendor-contact memory, 20-character description enforcement, full asset UID,
  neutral ENFRA-aligned styling, and one final generation/Smartsheet action.
- `11f85c4` — all 87 exact Smartsheet JOB NUMBER values, account-filtered
  selection, exact-value validation, and the Arkansas-versus-RRH Unity rule.

## Verification

Automated checks:

```text
python -m pytest -q
232 passed

cd tests && python -m pytest . -q
232 passed

python -m py_compile app/*.py
silent success
```

The HEIC path was additionally exercised with an uploaded receipt image resized
to 3024×4032 and encoded as HEIC. It produced a 1176×1568 PNG payload of 657,050
bytes, below the 5 MB vision limit.

Streamlit AppTest covers the RRH quick path, editable Scope, unresolved-field
placement, vendor-contact recall, typed-field persistence, cost-code blocking,
two downloads, and the native new-tab Smartsheet link. Physical iPhone/iPad and
Windows Chrome/Edge acceptance remains a release-device check; this runtime has
no installed browser binary.

## Non-regression status and release inputs

The following constraints have direct automated coverage:

- RRH site/category/cost-code behavior remains deterministic.
- Memory is scoped by account and device/vendor context.
- Asset selection exports the complete configured UID and remains conservative
  when no unique asset is supported.
- Uploaded quote bytes are retained unchanged in the attachment package.
- Optional Smartsheet API integrations remain inert without environment values.

The production registry has been restored and is protected by a regression
test that asserts all 36 non-RRH contracts, 106 raw site buckets, and 11,368
asset rows are present. The complete selected registry UID remains the value
exported for an asset.

One historical product distinction remains:

1. The current active product creates the unchanged quote plus a reviewed Scope
   PDF; it does not call the legacy MSAPO DOCX generator, and the referenced
   master template is not present. Restoring MSAPO generation would be a product
   behavior change, not a C1–C8 correction.

The production Dockerfile is present and its browser/runtime dependencies are
covered by deployment tests.

## Product-owner questions

1. **Unity Specialty Appendix A letter:** unresolved. No letter was invented;
   the site requires visible manual cost-code entry.
2. **RRH greeting:** the active workflow no longer creates email. If an email
   route is restored, keep the neutral greeting unless personalized RRH wording
   is explicitly requested.
3. **C9:** deliberately not included in the C1–C8 correction series. The visible
   reordering had already been approved and implemented in `b594d76`, where
   routing and all review fields occur before the one generation action.

Do not reopen PR #15; the closed Smartsheet branch remains outside this
correction series.
