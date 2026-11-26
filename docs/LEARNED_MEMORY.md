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

* **Only the owner views or edits saved contacts.** He is the app's only
  user, and on 13 November 2026 he chose not to put a passcode on it. The app
  still has no sign-in, so the screen (`app/owner_contacts_ui.py`) is open to
  anyone who opens the purchase page's About section and ticks "Show saved
  contacts and PO history". It lets the user pick one account, correct or
  delete a saved vendor representative, and read that account's PO history.
  There is no database export. Access is expected to come from the planned
  move to Azure behind single sign-on; until then the link itself is the only
  protection.
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

Failures are swallowed but no longer silent (26 November 2026):

* Every swallowed failure is logged at WARNING by `app.memory` as
  `Learned memory <operation> failed: <exception type> <SQLite code>`, at most
  once a minute per operation and code (the line says how many similar ones
  were not logged). Log lines carry no names, emails, browser tokens, paths or
  exception messages.
* A process-wide counter (`memory.failure_summary()`) is written to a small
  status file outside the data folder (`$EPC_MEMORY_STATUS_DIR`, default
  `<temp>/epc-memory-status/`), and `scripts/host_check.py` reports it as a
  WARN line: run the deploy-time `check` to see it.
* A failure caused only by a busy/locked database is retried twice with a
  short random pause before it counts. On the Azure Files share (rollback
  journal) SQLite's busy handler is not fair between waiters, and under load a
  request could time out after 5 s while others kept winning the lock.
* When the disk is full or read-only and a deploy has added a table or
  column, initialization cannot write but the learned rows are still
  readable: recall keeps working (it used to come back empty everywhere), and
  the refused writes are counted. Corruption or an unsupported schema still
  turns memory off for the request, as before.
* Writers in the one app process take turns (a Python lock, bounded at 10 s)
  before asking SQLite for the write lock, so concurrent browser sessions
  queue in order instead of racing SQLite's busy handler.
* On Azure (`CONTAINER_APP_REVISION` set), the host check warns when the data
  folder is not on a network share, which is what happens if the share did not
  mount and the app created the folder on the container's own disk.

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
