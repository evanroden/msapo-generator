"""Pure helpers for quote-source and Streamlit analysis-state integrity.

The page can accept an uploaded file, pasted text, or the hidden synthetic QA
sample.  Keeping source selection outside the UI code prevents a stale value
from one input from silently overriding the source the operator is looking at.

What depends on this module
---------------------------
``app.web_ui`` only. The hazard it exists to contain is specific to Streamlit:
a widget that is not rendered this run KEEPS its session value, so the paste
box still holds last week's quote while the operator is looking at an uploader.
Choosing the active text by hand at the call site is how a stale source wins.

``quote_source`` is not cosmetic. ``po_context._active_quote_attachment`` uses
it to decide whether the uploaded FILE may be attached as the vendor's quote,
so the label this module returns determines which document reaches contract
administration.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


# These two strings are BOTH the radio labels the operator reads and the values
# compared in choose_quote_text. Changing the wording changes the comparison:
# an edit here alone makes both branches fall through and choose_quote_text
# returns ("", ""), which web_ui reads as "no quote yet" and answers by clearing
# the analysis. No error -- the page just refuses to see the uploaded file.
UPLOAD_MODE = "Upload a file"
PASTE_MODE = "Paste text"
QUOTE_INPUT_MODES = (UPLOAD_MODE, PASTE_MODE)
# A ceiling on the ANALYZER call, not on the file. Roughly an order of
# magnitude above the largest real quote seen (a 45,866-character Trane PDF
# including 42,000 characters of terms), so it stops a pathological input --
# an OCR loop, a whole manual pasted in -- before it becomes a slow, expensive
# and useless model call. Blocking here is deliberate: silently truncating
# would analyze a fraction of the quote and report nothing.
MAX_QUOTE_CHARACTERS = 500_000

# Everything that can make an OLD analysis look like it describes the CURRENT
# quote. The list is exhaustive on purpose and each entry earns its place:
# analysis/analysis_token/quote_text are the analysis itself; last_sig is the
# cache key that would otherwise suppress the next analyzer call;
# scope_pdf_bytes/scope_pdf_signature are the generated package; the two
# analysis_error_* keys are a sticky failure that would re-display against an
# unrelated quote. A key omitted here does not raise -- it survives and
# contradicts the others.
#
# NOT cleared, deliberately: uploaded_file_name, uploaded_file_bytes,
# extracted_text and extract_hash. Those describe the FILE the operator still
# has selected in the uploader, not the analysis, and dropping them would
# re-run OCR on a scan that takes tens of seconds. Pinned by
# test_clearing_source_removes_old_analysis_and_generated_package_state.
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

    Returns ``(text, source)`` where source is one of "upload", "paste",
    "synthetic", or "" -- and the pair is ALWAYS consistent: empty text never
    carries a source label, because ``po_context`` keys attachment decisions off
    that label and a source without text would authorise attaching a file the
    analysis does not describe.

    An unrecognised mode returns ``("", "")`` rather than guessing. web_ui
    treats that as "no quote yet" and clears the analysis, which is the safe
    reading; the alternative would be rendering a previous quote's fields under
    a source nobody selected.
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
    """Remove every artifact that can make an old quote appear current.

    Idempotent and safe on a fresh session -- every removal is a ``pop`` with a
    default, because this runs on paths where the analysis may never have
    existed (a failed first analyzer call, an oversized paste).

    It does NOT clear the per-field correction widgets (vendor_, contact_,
    scope_, desc_, ...). Those are keyed by the analysis token, so a new quote
    gets new keys and the old ones are simply never read again. Adding them to
    the sweep would be the plausible-looking wrong change: on the paths where
    this runs while the operator is mid-correction, it would erase typing they
    have not finished.
    """
    for key in _ANALYSIS_KEYS:
        state.pop(key, None)
    # Prefix sweep for the two families whose names embed a token this function
    # does not know. Iterating over ``tuple(state)`` is REQUIRED, not stylistic:
    # popping from a live mapping while iterating it raises RuntimeError
    # mid-render, and this runs inside the Streamlit script.
    for key in tuple(state):
        if str(key).startswith(("generated_context_", "routing_")):
            state.pop(key, None)


def quote_length_problem(text: str) -> str:
    """Return a blocking message for an impractically large analysis input.

    Returns "" when the input is acceptable, so the caller's guard reads
    ``if quote_length_problem(...)``. Measured in CHARACTERS, not tokens or
    bytes: it is a cheap sanity bound in front of a paid call, not an accurate
    model-context calculation, and the message quotes the same unit it counted
    so the operator can act on it.
    """
    count = len(str(text or ""))
    if count <= MAX_QUOTE_CHARACTERS:
        return ""
    return (
        f"The extracted quote contains {count:,} characters, above the "
        f"{MAX_QUOTE_CHARACTERS:,}-character analysis limit. Upload a shorter "
        "quote or paste only the vendor quote pages."
    )
