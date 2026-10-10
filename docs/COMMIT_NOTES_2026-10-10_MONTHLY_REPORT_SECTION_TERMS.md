---
document_type: implementation_checkpoint
date: 2026-10-10
workflow: monthly_report
base_commit: 21bae9bdc4e6216e0dd0b2e1323281701921b9b6
change_type: copy_and_help_clarity
status: candidate_rebased_for_exact_ci
---

# Define MBCx, ENFRA Connect and RFI at the point of use

The owner's second novice walkthrough identified unexplained section terms
MBCx, ENFRA Connect and RFI Matrix. Both onboarding panels are collapsed,
and a user who does not read them can still reach the report editor. This
change expands the terms in the **existing always-visible section guidance**,
not another mandatory checklist or a new wizard.

MBCx is described as monitoring-based commissioning based on reviewed
equipment performance data. ENFRA Connect is identified as the platform
named by the existing design, with an explicit reminder to describe only
verified findings and not invent results before monitoring begins.

RFI is expanded to Request for Information; open requests and site-specific
status remain visible until the requested response is confirmed.

Training guidance now clearly states the client/hospital staff scope,
not ENFRA's internal training, with hours and completed events only when
supported by records.

These are help-text changes only. They do not alter source classification,
vendor/ENFRA service-call routing, report inclusion, memory/storage,
semantic output, PDF layouts, AI prompts, or company/client affiliation
enforcement. Those remain distinct implementation and validation tasks.

Tests assert the expanded terminology and completion/uncertainty boundaries
for all standard sections. Full pinned tests, container/renderer and capped
resource checks must pass on the exact published commit. The owner should
review the text in the public app after deployment; AppTest and unit tests
alone cannot prove first-time readers understand every label.

No customer source files, private names, images, fonts or asset records are
included. Rollback is code-only.

October 10 integration: Maintenance guidance now honors merged #117 (vendor technical reports in Activity and ENFRA technician onsite calls only), without inventing staffing facts.
