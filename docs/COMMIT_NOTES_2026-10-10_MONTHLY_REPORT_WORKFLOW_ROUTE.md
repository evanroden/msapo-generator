---
document_type: implementation_checkpoint
date: 2026-10-10
base_commit: c519689f77180b6900a9291d8c28ce7b7b22c8a6
workflow: all_application_workflows
change_type: navigation_reliability
status: candidate_pending_exact_ci
---

# Keep the selected workflow visible after a page reload

The owner's second novice test observed that, after returning from a 502
connection failure or reloading a report, the landing page returned to the
Purchase order workflow. This is a navigation-state issue distinct from
recovering unsaved monthly report inputs. A fresh Streamlit session cannot
reuse its prior in-memory segmented-control value automatically.

The chosen workflow is now represented by a small URL navigation hint:
`?workflow=monthly`, `?workflow=expense`, or `?workflow=purchase`.
When a browser refresh creates a new Streamlit session, a valid existing
hint initializes the existing required segmented control to the matching
workflow before that widget renders. When someone deliberately switches
workflows, the URL is updated while preserving unrelated query parameters.

The hint contains **only** the public workflow name. It cannot specify
a contract, site, person, report, report content or a permission. It
provides no authentication or access control and does not pretend to save
monthly work. A current in-memory widget choice wins over a stale URL hint.
Unknown or malformed hints fall back to the existing Purchase order default.
If URL state is unavailable in an embedded/runtime test context, the
existing segmented control remains usable without a page-wide failure.

Tests use the pinned Streamlit 1.61.1 AppTest query parameter API and the
real entrypoint to cover fresh monthly reload, subsequent selection changes,
preservation of unrelated query data, invalid hints and active widget
priority. The existing required=True protection against deselection stays.

This does **not** fix the separate site-checkbox click failures,
manual-output blank review, active-work auto-retention during a 502,
unapproved client data access or user-visible upload errors. The selected
workflow is merely a routing hint, not durable business data. No persistent
schema, runtime file, cookie content, hosting plan or stored draft changes.
Rollback is code-only. Verify the same URL refresh behavior in a real
browser after merging; AppTest is not live-browser evidence.
