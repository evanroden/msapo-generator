# Learned contact memory: current behavior and limits

This describes the existing store, not a new retention or access policy.

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

## Access and retention limitations

The current internal-testing app has no authenticated administrator identity.
An entered name, selected contract or browser token is not authentication.
Existing anonymous Monthly administration must not be reused to expose learned
contact CRUD. Contact management remains disabled until real server-side
identity and contract permissions can be verified. No contact list or database
export should be rendered by a disabled management route.

The existing learned-contact store has no automatic age-based deletion policy.
This change does not create one, delete old entries, change who can see existing
suggestions, or authorize a new audience. A retention period and optional PO
history fields remain unresolved product decisions. Do not treat frequency
counters as a complete submission history.

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
