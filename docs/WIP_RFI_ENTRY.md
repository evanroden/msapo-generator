# RFI entry implementation checkpoint — not ready to merge

Updated 2026-10-20. This remains the existing draft feature and is not an
acceptance record. The canonical remaining-work ledger remains
`PHASE1_PHASE2_REMAINING_2026-10-14.md` (SIM-R01).

The original draft head `47fc854cf2b58050faa05996abd0aaa0f6eb0c69` is preserved.
The reconciled pre-fix test checkpoint is local
`bc6cc7afa8170059ab8fb55bddec49dd83df95fc`, tree
`2619b1a80af58f55dccc004c77e842e3619c0c8d`, retaining the published contact-row
helpers and source/Training safeguards. It specifies the desired native first
Add, durable reload and real editable Word/PDF journey before the focus fix.

The implementation now consumes an Add focus nonce only after its actual
trusted native action, in the same report and exact row context. A pending
request survives the display adapter's same-report handoff, and is canceled
when the user moves to another control, navigates, hides the tab or switches
reports. The temporary observer disconnects when resolved. There is no polling,
input cloning, value/selection change, click replay, or automatic focus of a
restored draft. This adapter uses the locked Streamlit 1.61.1 keyed wrappers;
remove it when a framework-native version-bound focus request covers these
same acceptance cases.

Recognized request columns use native multiline fields. Imported continuation
tables share the existing one-active-row helper while keeping their separate
schemas, references, pending edits and conflict comparisons. Unknown columns
retain their labels and receive no guessed focus destination.

The bounded October 20 reconstruction recognizes complete content headings
such as Requested item and Question. Requested by, Requested date and Question
identifiers remain metadata; two recognized content columns remain multiline
without guessing which should receive focus. Card summaries use the actual
request content. Delivered trusted paste, dictation and composition events in
the still-focused previous field cancel the delayed focus intent. Untrusted
notifications do not cancel a genuine pending Add.

The recorded before-fix head `8074042232b175018ae06c0074c9d1a24bfe79b2`
produced eight desired failures and 4,091 passes in Tests `39358335282` at the
recorded CI checkout `ac49211b394020a42bfc81aea2cfbf69a308fdcf`. Seven failures
cover content versus metadata/ambiguous headings; the remaining failure is the
trusted-input cancellation model. The full first-failure log is retained.
This reconstruction has not been executed locally or accepted in a browser.

Still required before integration:

- Run the new one-shot focus logic controls and migrated native-row tests,
  including continuation schemas/links, blank cancellation, omission,
  source/report incarnation and pending text across table changes.
- Run `scripts/qa_rfi_entry.py` on the exact candidate in Chromium and Playwright
  WebKit: one Add action, preserved native focus/caret on resize, same-event
  Close, cancellation, reload, and actual editable Word/PDF requests. A generic
  row journey does not satisfy this gate. Preserve the pre-fix failure.
- Reconcile the final source-correction dependency and obtain green integrated
  Tests/Adaptive checks, review, served interaction and required output review.
  No native Microsoft Word, physical Safari or assistive listening is claimed.

Historical 2026-10-17 focused existing regression only:
`python -m pytest tests/test_monthly_report_row_cards_ui.py -q` — 18 passed in
3.76 seconds. `git diff --check` passed. This does not establish RFI acceptance;
the RFI-specific suite had not yet been adapted at that historical checkpoint.

The October 19 changes have not been executed locally. Automatic approval
review rejected the earlier protected-runtime launcher and forbade workarounds;
the existing GitHub CI runner is the authorized validation route. Source
inspection and `git diff --check` are separate from behavioral acceptance.

Remove this temporary implementation checkpoint when the missing work is
completed and its evidence is recorded in the canonical ledger.
