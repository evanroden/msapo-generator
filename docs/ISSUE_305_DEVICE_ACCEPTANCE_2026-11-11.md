# Issue #305 — device/accessibility acceptance ledger (11 November 2026)

Parent #270; integration through P20. The exact inspected main SHA was `57c5cd87e3e441dfea3cddbc666248f8e469d986`. This is **not** an independently verified served About/build SHA. `AGENTS.md` is absent from main's complete Git tree.

## Original acceptance scope

Issue #305 names J01–J06 and QA-ADAPTIVE-A01–A20, but its current body does not enumerate the full acceptance text of each individual key. It requires Monthly/PO/Expense book/tabletop/wide and source/output journeys, sticky/empty/long content, zoom, real posture, unequal/malformed segments, touch/pointer/keyboard/IME and unblurred input, workflow return, reconnect/two tabs, standing scope, late/evicted previews, capped resources, accessible labels/states/announcements/dialog focus, and exact served revisions and outputs. No individual key is marked Verified on the basis of an inferred mapping.

## Exact-main automated evidence (not a physical-device pass)

- [Adaptive run 43016840241](https://github.com/evanroden/msapo-generator/actions/runs/43016840241), `synthetic-dom` job `130677612915` **success** on inspected main. This ran the existing `qa_adaptive_workspaces.py`, `qa_monthly_adaptive.py`, `qa_po_adaptive.py` and `qa_expense_adaptive.py` synthetic localhost browser journeys, plus other native checks. [Retained browser artifact](https://github.com/evanroden/msapo-generator/actions/runs/43016840241/artifacts/13855035694).
- Hosted GitHub Ubuntu 24.04 x86_64 VM, Playwright 1.58.0, Chromium 145.0.7632.6 and Playwright WebKit 26.0. Scripted pointer/keyboard actions, role/label DOM assertions and injected segment geometry are **not** native touch, assistive listening, physical folding or shipping Safari.
- Same-main [Tests workflow 43016840706](https://github.com/evanroden/msapo-generator/actions/runs/43016840706): pytest, container and `monthly-report-resources` completed successfully.
- Local development: metadata helper **2 unit tests passed**, Python compilation passed, and helper itself ran with Chromium 144.0.7559.96 on Debian 13 x86_64. **No MSAPO browser journey** was run from that container, and local WebKit/Firefox executables were absent.

This PR adds an explicit machine/OS/engine/version/automation-method receipt to **each existing browser engine group**. The receipt declares physical-device, physical-Safari, screen-reader listening, native IME and native browser zoom **false**. It collects browser-reported pointer capabilities and viewport dimensions as emulation observations only. No production UI, report assembly, external call, data or rendering semantics change.

## Coverage matrix

| Surface | Engine/method | Status | Limits |
| --- | --- | --- | --- |
| Monthly wide/book/tabletop + synthetic outputs | Hosted Chromium 145 and Playwright WebKit 26, scripted pointer/keyboard | PASS existing exact-main CI | Not physical, shipping Safari or speech |
| PO wide/book/tabletop + generated form | Same hosted engines and scripted methods | PASS existing exact-main CI | Not physical or speech |
| Expense wide/book/tabletop + packet | Same hosted engines and scripted methods | PASS existing exact-main CI | Not physical or speech |
| Shared geometry/preview resources | Hosted CI synthetic fixtures | PASS existing exact-main CI | Injected segments; bounded tests only |
| Method-attribution helper | Local Debian 13 Chromium 144 | PASS 2 unit tests + real browser metadata smoke | Metadata only, no app |
| Physical iPhone Safari + VoiceOver | Actual hardware/assistive listening | **NOT RUN** | No device available |
| Physical Android Chrome + TalkBack | Actual hardware/assistive listening | **NOT RUN** | No device available |
| Physical tablet/foldable with actual orientation/posture | Native engine, touch/keyboard | **NOT RUN** | No device available |
| Physical desktop 200–400% browser zoom + screen reader | Native browser zoom and audible speech | **NOT RUN** | No accessible host available |
| Native IME composition, offline/reconnect, independent two-tab conflict | Actual device/served browser | **NOT RUN** | Scripted event is not an IME |
| Exact production About SHA + current served artifact fidelity | Production app | **NOT VERIFIED** | Current About inaccessible from this session |

The J01–J06 / A01–A20 aggregate verdict is **PARTIAL**. Successful layout changes alone do not prove zero AI, generation, submission or standing writes; rely on actual relevant server receipts and negative checks. Re-run after P02/P04/P05/P06/P08 integrations.

## Owner-executable physical-device checklist

1. Record device make/model, OS build, actual browser/version, pointer/touch/keyboard method, accessibility method/version, native zoom, date and exact served About SHA.
2. With isolated invented data, enter Monthly, PO and Expense on a real iPhone Safari with VoiceOver: touch labels and listen for names, roles, states, validation, loading/error announcements and dialog focus restoration.
3. On Android/TalkBack if available, repeat label-hit targets and speech. Enter and deliberately clear real native IME text while unblurred, rotate, save and reload to compare the exact text.
4. On a tablet/foldable, try actual portrait/landscape/book/tabletop rotation, asymmetric hinge/gap, focus/caret and meaningful scroll. Record unavailable geometries **NOT RUN**.
5. On desktop, use Tab/Shift+Tab/Enter/Space/Escape/PageDown at 200% and 400% **browser** zoom with an actual screen reader, ensuring all long content remains reachable.
6. Toggle offline/online and use two tabs: verify stale/evicted preview retry, preserved edits, truthful conflicts and no layout-induced business calls.
7. Download synthetic Monthly DOCX/PDF, PO form and Expense packet; inspect content hashes/revisions and exact expected text before/after layout changes.
8. Preserve the **first** failed action and settled state, log hardware/method/served SHA and keep issue open until P20's integrated served checks and hardware-only gaps are accepted.

No genuine files, customer screenshots or secrets belong in the issue/CI artifacts. This QA-only PR should not close #305.
