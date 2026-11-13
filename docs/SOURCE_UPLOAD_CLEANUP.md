# Rejected monthly-report uploads: cleanup rule

Owner decision for #284, 13 November 2026.

- **Rejected uploads are deleted right away.** When a source file is not read
  (damaged, unsupported content, over a report budget, or an unexpected fault
  while reading it), the original bytes and extraction cache that this attempt
  wrote are removed before the batch continues or the fault is raised.
- **Old and accepted files are never touched.** A blob that already existed
  before the attempt, a blob whose bytes no longer match the rejected upload,
  a pre-existing extraction cache, symlinks, and every accepted original stay
  exactly as they are. There is no sweep of older or unreferenced files.

Code: `_discard_rejected` in `app/monthly_report_sources.py`, used by
`ingest_batch` for both expected file failures and unexpected faults (which are
still raised, never hidden as a file failure).

Tests: `tests/test_monthly_report_rejected_upload_cleanup.py`, plus the existing
`tests/test_monthly_report_source_batch_failures.py` and
`tests/test_monthly_report_parser_failure_integrity.py`.
