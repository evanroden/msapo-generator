"""Pure helpers for quote-source and Streamlit analysis-state integrity.

The page can accept an uploaded file, pasted text, or the hidden synthetic QA
sample.  Keeping source selection outside the UI code prevents a stale value
from one input from silently overriding the source the operator is looking at.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


UPLOAD_MODE = "Upload a file"
PASTE_MODE = "Paste text"
QUOTE_INPUT_MODES = (UPLOAD_MODE, PASTE_MODE)
MAX_QUOTE_CHARACTERS = 500_000

_ANALYSIS_KEYS = (
    "analysis",
    "analysis_token",
    "quote_text",
    "quote_source",
    "last_sig",
    "scope_pdf_bytes",
    "scope_pdf_signature",
    "analysis_error_signature",
    "analysis_error_message",
)


def choose_quote_text(
    mode: str,
    *,
    uploaded_text: str = "",
    pasted_text: str = "",
    synthetic_active: bool = False,
    synthetic_text: str = "",
) -> tuple[str, str]:
    """Return exactly one active quote and its source label.

    The selected mode wins even when the inactive widget still has stale
    session data.  The synthetic sample survives its one reload only until a
    real upload or paste interaction deactivates it.
    """
    if synthetic_active:
        text = str(synthetic_text or "").strip()
        return (text, "synthetic") if text else ("", "")
    if mode == UPLOAD_MODE:
        text = str(uploaded_text or "").strip()
        return (text, "upload") if text else ("", "")
    if mode == PASTE_MODE:
        text = str(pasted_text or "").strip()
        return (text, "paste") if text else ("", "")
    return "", ""


def clear_active_analysis(state: MutableMapping[str, Any]) -> None:
    """Remove every artifact that can make an old quote appear current."""
    for key in _ANALYSIS_KEYS:
        state.pop(key, None)
    for key in tuple(state):
        if str(key).startswith("generated_context_"):
            state.pop(key, None)


def quote_length_problem(text: str) -> str:
    """Return a blocking message for an impractically large analysis input."""
    count = len(str(text or ""))
    if count <= MAX_QUOTE_CHARACTERS:
        return ""
    return (
        f"The extracted quote contains {count:,} characters, above the "
        f"{MAX_QUOTE_CHARACTERS:,}-character analysis limit. Upload a shorter "
        "quote or paste only the vendor quote pages."
    )
