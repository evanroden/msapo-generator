# Learned contact memory: current behavior and limits

This describes the learned-memory store and the owner's access and retention decisions for it.

## What is stored

`epc_memory.db` in `EPC_DATA_DIR` contains contract-scoped administrator and
contact suggestions, vendor representative pairs and use counters, and
browser/account-scoped requester and expense defaults. Browser tokens are
hashed before storage. Expense defaults may include employee names/numbers,
approver names/emails, mail choices and legacy coding fields. Report preparer
and report-selection preferences are also retained.

The memory store does not save receipt files, transaction lines, mileage
entries or signature confirmation. It is a convenience store, not a durable
searchable purchase-order audit history. Smartsheet duplicate-prevention state
is a separate database with different failure behavior.

## Access and retention (owner decision, 13 November 2026, #21)

The owner decided:

* **Only the owner views or edits saved contacts.** The app still has no
  sign-in, so an entered name, selected contract or browser token is not
  authentication, and the anonymous Monthly administration is not reused. The
  owner screen (`app/owner_contacts_ui.py`) sits in the purchase page's About
  section and is shown only when the server has a passcode of at least 12
  characters in `MSAPO_OWNER_PASSCODE` (`app/owner_access.py`). Without it the
  app behaves as before and no list is rendered. After unlocking, the owner
  can pick one account, correct or delete a saved vendor representative, and
  read that account's PO history. Five wrong passcodes in 15 minutes lock the
  gate for the rest of the window. There is no database export.
* **Saved contacts are kept for two years after their last use.**
  `prune_stale_contacts` removes vendor representatives, requester and
  approver suggestions and their events last used more than 730 days ago. It
  runs at most once a day per server process, after a PO history write. A row
  whose last use is unknown (0) is never removed.
* **One PO history row per accepted package**: date, vendor, total and quote
  file name, in `po_history`. It is recorded when a PO package passes all three
  readiness checks and is generated, keyed by its context ID, so reruns and
  regenerating the same package never add rows. The app hands off to
  Smartsheet by link and cannot see the final Smartsheet submit, so a row
  means "package generated ready to submit", not "Smartsheet accepted it".
  PO history is not pruned. Frequency counters are still not a submission
  history.

## Failure and recovery

When learned-memory storage is unavailable or corrupt, memory functions return
safe empty defaults or failure values. A PO/expense workflow must continue
without learning. The bad database must not be silently erased or replaced.
A later healthy connection can resume learning without restarting the app.

This rule does not apply to the Smartsheet submission store: failure to read
idempotency state must stop a potentially duplicate remote write. Do not turn
that failure into an empty history.

`tests/test_memory_outage_recovery.py` exercises corrupt storage, a directory at
the database path, a missing parent, a transient SQLite connection failure and
recovery, including contract isolation after recovery. These are synthetic
checks, not a production-database outage experiment.

## Backup and offline restore

Use the existing `scripts/migrate_data.py` export/verify/restore commands and
`docs/AZURE_MIGRATION.md`, section 4. Export uses SQLite's online backup API,
includes committed WAL rows and emits a checksum manifest. Restore requires an
empty offline destination by default and verifies file checksums and SQLite
integrity before installation. Stop the target app before restore and restart
afterward. Keep archives outside the live data folder and treat them as
sensitive because they contain learned contacts and report files.

The backup implementation is already present. This work neither runs a
production backup/restore nor changes deployment infrastructure.
