"""Display-only progress links for the Monthly report workflow."""
from __future__ import annotations

from html import escape

MONTHLY_STEPS = (
    ("report-contract-selector", "Report and month", "Choose the report sites and month."),
    ("monthly-step-sources", "Sources", "Add and review files, or finish without files."),
    ("monthly-step-sections", "Sections", "Edit the included report sections."),
    ("report-review", "Review and download", "Check warnings and create Word and PDF."),
)


def monthly_step_states(*, report_ready=False, sources_ready=False,
                        sections_ready=False, generated=False):
    """The next unfinished stage is current; a later stage cannot skip a gate."""
    completed = (
        bool(report_ready),
        bool(report_ready and sources_ready),
        bool(report_ready and sources_ready and sections_ready),
        bool(report_ready and sources_ready and sections_ready and generated),
    )
    current = next((index for index, done in enumerate(completed) if not done), None)
    return tuple("complete" if done else "current" if index == current else "pending"
                 for index, done in enumerate(completed))


def monthly_step_spine(states, *, section_count=14):
    """Focusable in-page links, reusing the Purchase and Expense step styles."""
    if len(states) != len(MONTHLY_STEPS) or any(
            state not in {"complete", "current", "pending"} for state in states):
        raise ValueError("Expected one valid status per Monthly step")
    if not isinstance(section_count, int) or section_count < 1:
        raise ValueError("Expected a positive section count")
    links = []
    for index, ((anchor, title, summary), status) in enumerate(zip(MONTHLY_STEPS, states), 1):
        current = ' aria-current="step"' if status == "current" else ""
        status_label = {"complete": "Complete", "current": "Current", "pending": "Not yet ready"}[status]
        summary = f"{section_count} report sections; use the section pager below." if index == 3 else summary
        links.append(
            f'<li><a class="po-step-link" href="#{anchor}" data-state="{status}"{current} '
            f'aria-label="Step {index}: {escape(title)}. {status_label}. {escape(summary)}">'
            f'<span class="step-num" aria-hidden="true">{index}</span>'
            f'<span class="po-step-copy"><span class="step-title">{escape(title)}</span>'
            f'<span class="po-step-summary">{escape(summary)}</span></span></a></li>'
        )
    return ('<nav class="po-step-spine" aria-label="Monthly report steps">'
            '<ol>' + ''.join(links) + '</ol></nav>')
