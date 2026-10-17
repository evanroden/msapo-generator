# RFI entry implementation checkpoint — not ready to merge

Recorded 2026-10-17 23:34 UTC. This branch preserves unfinished work at the
owner's request; it is not an acceptance record. The canonical remaining-work
ledger remains `PHASE1_PHASE2_REMAINING_2026-10-14.md` (SIM-R01).

Base: `7ef068f3d515a327b7312ad658b8b550abc83ba3`.

Implemented locally: route Information requests through the existing native
row-card editor; preserve imported schemas and references; provide the
Requested item placeholder; suppress the empty caption while an entry is open.
An explicit Add action emits a one-shot focus marker.

Still required before integration:

- Implement and test the native focus-marker consumer in the existing layout
  discovery path. No consumer exists yet, so Add does not yet focus Requested
  item. Do not add polling or move/clone business inputs. Cancel delayed focus
  when the user has already moved elsewhere; preserve native caret and nodes.
- Migrate `tests/test_monthly_report_rfi_ui.py` from the former grid to native
  cards while retaining imported continuation schemas, links, unrelated content,
  omitted-state behavior, stale-action rejection, and report/generation isolation.
- Verify blank/canceled entries are neither counted nor exported, pending text
  survives one structural action, durable reload works, and actual editable
  Word/PDF outputs retain the complete request schema and links.
- Run desktop/narrow native browser acceptance and integrated CI. None is claimed
  for this partial branch. Reconcile additive row-helper options with the separate
  contacts work before merging.

Focused existing regression only:
`python -m pytest tests/test_monthly_report_row_cards_ui.py -q` — 18 passed in
3.76 seconds. `git diff --check` passed. This does not establish RFI acceptance;
the RFI-specific suite has not been adapted or represented as passing.

Remove this temporary implementation checkpoint when the missing work is
completed and its evidence is recorded in the canonical ledger.
