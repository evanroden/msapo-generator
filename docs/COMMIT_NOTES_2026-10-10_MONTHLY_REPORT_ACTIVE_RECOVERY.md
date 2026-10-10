---
document_type: implementation_checkpoint
date: 2026-10-10
base_commit: bc4e915975f853011c0ada6bf27ea5fe6d7520bb
workflow: monthly_report
change_type: active_work_recovery
status: candidate_pending_exact_ci_and_browser_acceptance
---

# Keep current monthly work through a browser refresh

## Owner requirement and prior failure

The October 9 novice test observed that a Render 502/reconnection reset the
Streamlit editor and lost a Prepared by value that had not been manually saved.
The saved report snapshot survived. PR #109 remembers the **selected workflow**,
not the current report's unfinished text. The owner wants ordinary active
monthly work retained without a routine Save progress chore and accepts
manually restarting abandoned work; no arbitrary inactivity TTL was approved.

## Scope and behavior

This change introduces an atomic **browser-scoped working journal** on the
existing EPC_DATA_DIR monthly_reports disk. The existing random 128-bit
anonymous device cookie is used only after strict format validation; its raw
value is never stored, only a SHA-256 directory key. The journal is scoped to
the exact contract, selected-site report profile and reporting month. It
contains the current ReportDraft and separately stored, hash-validated
working pictures. It does **not** write contract standing contacts, capacity,
logos, global masters or completed-report history.

A new Streamlit session with the same valid browser cookie can recover its
last successfully committed working text, Prepared by name, source references,
caption, approved picture state and current monthly draft. Only current
report widgets that sent their values to the server can be recovered;
uncommitted keystrokes at the exact instant of a 502 cannot be guaranteed.
If the cookie is missing or disabled, the editor says automatic recovery
is unavailable and retains the optional explicit Save progress control.

Identical reruns reuse the existing journal revision without writing another
file. Different browser tabs use an optimistic revision guard so an older tab
cannot silently overwrite a newer browser copy. If a shared saved-report
snapshot advanced while the browser was away, neither version is silently
selected: the user chooses whether to inspect the unfinished browser copy or
use the current saved report. The original shared snapshot history is never
rewritten. The existing report-revision/export conflict gate remains effective.

After a completed or explicit report-version save, the browser's own active
journal is cleared when its revision matches; only that temporary working
copy and pictures are affected. Existing saved history and standing data
remain intact. A collapsed Start over option has a confirmation checkbox
and discards only this browser's working copy for the selected sites/month.
**No inactivity expiry or automatic data purge was invented.**

The routine Save progress button moves under optional saved-version controls.
An ordinary editor no longer has to click it just to survive refresh. Save
success is displayed only after the atomic journal write is verified;
storage failures show a local error and keep current session fields visible.
The browser token is attribution/convenience identity, **not authentication**;
shared computers require the operator to clear their working copy.

## Tests and limitations

New synthetic tests cover atomic roundtrip, browser/site/month isolation,
no-op writes, newer-tab conflict, picture-content integrity, and deliberate
discard without touching completed snapshots. Streamlit AppTest regressions
cover a new session recovering typed Prepared by and Activity, a storage
failure that never claims success, a newer shared saved-version conflict,
and an explicit no-cookie fallback. No private report files are committed.
The pure journal tests ran locally under restored pinned Python 3.12 and
Streamlit 1.61.1; exact current-head full CI must independently test the
integrated UI, fonts, production container and 512 MiB / 0.5 CPU workload.

This first slice protects committed input through ordinary refresh and
process restart via persistent storage. It does not guarantee recovery of
in-flight uncommitted browser keystrokes, a cookie-free visitor, or a full
two-device collaboration system. It does not diagnose which particular
Oct 9 outage was caused by memory pressure. The owner will perform the
real browser/refresh test after a green production deployment.

Rollback is code-only. Do not erase finished report snapshots, original
uploads, standing information, or design pins.
