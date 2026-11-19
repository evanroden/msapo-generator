"""Display-only purchase-order step navigation.

Progress is derived from the already-validated UI state. This module does not
change the purchase-order gate, source selection, or document rendering.
"""
from __future__ import annotations

from html import escape

PO_STEPS = (
    ("quote", "Quote", "Upload or paste a quote for analysis."),
    ("scope", "Scope", "Check the drafted work and suggested items."),
    ("details", "Needed from you", "Confirm missing details and your name."),
    ("generate", "Generate and submit", "Create both files and open Smartsheet."),
)


def po_step_states(
    *,
    quote_ready: bool = False,
    scope_ready: bool = False,
    details_ready: bool = False,
    generated: bool = False,
) -> tuple[str, str, str, str]:
    """Mark complete only after each prerequisite is available.

    The first incomplete step is current. A completed package has four
    completed steps and no current step; nothing is submitted automatically.
    """
    completed = (
        bool(quote_ready),
        bool(quote_ready and scope_ready),
        bool(quote_ready and scope_ready and details_ready),
        bool(quote_ready and scope_ready and details_ready and generated),
    )
    current = next((i for i, done in enumerate(completed) if not done), None)
    return tuple(
        "complete" if done else "current" if i == current else "pending"
        for i, done in enumerate(completed)
    )


def po_step_spine(states: tuple[str, str, str, str]) -> str:
    """Native, focusable hash links scroll to the actual PO sections.

    Reuses the expense flow's .step-num and .step-title rules. A pending
    section may not exist until the quote is analyzed; its link remains
    visible rather than adding a new path around the required-fields gate.
    """
    if len(states) != len(PO_STEPS) or any(
        state not in {"complete", "current", "pending"} for state in states
    ):
        raise ValueError("Expected one valid status per PO step")
    links = []
    for index, ((anchor, title, summary), status) in enumerate(zip(PO_STEPS, states), 1):
        current = ' aria-current="step"' if status == "current" else ""
        status_label = {
            "complete": "Complete",
            "current": "Current",
            "pending": "Not yet ready",
        }[status]
        links.append(
            f'<li><a class="po-step-link" href="#po-step-{anchor}" '
            f'data-state="{status}"{current} '
            f'aria-label="Step {index}: {escape(title)}. {status_label}. '
            f'{escape(summary)}">'
            f'<span class="step-num" aria-hidden="true">{index}</span>'
            f'<span class="po-step-copy">'
            f'<span class="step-title">{escape(title)}</span>'
            f'<span class="po-step-summary">{escape(summary)}</span>'
            f'</span></a></li>'
        )
    return (
        '<nav class="po-step-spine" aria-label="Purchase order steps">'
        '<ol>' + "".join(links) + '</ol></nav>'
    )
