"""Pure review-state rules for the streamlined quote-to-Smartsheet flow.

The Streamlit page uses these helpers to decide which values need to be shown
as questions and which already-filled values can stay in the correction panel.
Keeping the decision independent from widget rendering makes the behavior easy
to regression-test across reruns and viewport-specific layouts.

What depends on this module
---------------------------
``app.web_ui`` only, and it uses the result in TWO ways that must stay in
step: each field is rendered with ``with questions if needs.X else
corrections``, and the whole ``questions`` container is then highlighted as
"still needs a value". So a field being in ``ReviewNeeds`` is what puts it in
front of the operator AND what marks it. Nothing here renders anything, and
nothing here reads Streamlit state -- the caller must pass live values, because
placement has to be decided BEFORE the widgets exist.

These are placement rules, NOT the submission gate. The blocking list lives in
``po_context.build_po_context``. A value can legitimately be judged "resolved"
here (so it renders in the collapsed panel) and still be rejected there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.po_rules import parse_amount


# Deliberately permissive: one @, at least one dot after it, no spaces. It is a
# TYPO catcher, not an RFC 5322 validator. A stricter pattern would start
# rejecting real vendor addresses (plus-tags, long TLDs, hyphens) and the
# operator would have no way to override it, which is a worse failure than
# letting an odd-looking but valid address through -- smartsheet.py checks it
# again before submission.
_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


@dataclass(frozen=True)
class ReviewNeeds:
    """Values that must be presented outside the collapsed correction panel.

    True means "the operator still has to answer this". Every field is listed
    by name in THREE places -- here, in :attr:`any`, and in
    :func:`retain_review_needs`. Adding a tenth field and forgetting one of the
    other two is a silent partial feature: the field renders in the visible
    panel but never trips the banner, or it drops out of the panel the instant
    it is filled. There is no test that enumerates the fields for you.
    """

    routing: bool
    original_po_number: bool
    job_number: bool
    asset: bool
    total: bool
    vendor: bool
    description: bool
    contact_name: bool
    contact_email: bool

    @property
    def any(self) -> bool:
        """Whether the "Needed from you" banner should be shown at all.

        The property shadows the builtin ``any`` only inside the CLASS body;
        the call below resolves through globals to the builtin, because a
        method's scope chain skips the enclosing class. It is not recursion.
        Do not "fix" it by renaming -- web_ui reads ``needs.any``.
        """
        return any(
            (
                self.routing,
                self.original_po_number,
                self.job_number,
                self.asset,
                self.total,
                self.vendor,
                self.description,
                self.contact_name,
                self.contact_email,
            )
        )


def retain_review_needs(
    previous: object,
    current: ReviewNeeds,
) -> ReviewNeeds:
    """Keep every question that has needed operator input for this quote.

    Streamlit reruns after an input is committed. Without retained placement,
    a just-completed field can immediately move into the collapsed correction
    panel, which looks like the answer disappeared. New dependency-driven gaps
    (for example, an ambiguous asset after a site is chosen) are added as they
    become knowable.

    The result is a pure OR, so a question is sticky FOR THE LIFETIME OF THE
    QUOTE. That is intended: the caller stores this under a quote-scoped key
    that ``workflow_state.clear_active_analysis`` removes, which is the only
    reset. There is no "it is answered now, put it away" path by design -- the
    field moving back mid-session is precisely the flicker this prevents.

    ``previous`` is typed ``object`` and isinstance-checked because it comes
    straight out of session state, which can hold a value written by an older
    deployment with a different field set. A stale shape is discarded in favour
    of ``current`` rather than raising in the middle of a render.
    """
    if not isinstance(previous, ReviewNeeds):
        return current
    return ReviewNeeds(
        routing=previous.routing or current.routing,
        original_po_number=(
            previous.original_po_number or current.original_po_number
        ),
        job_number=previous.job_number or current.job_number,
        asset=previous.asset or current.asset,
        total=previous.total or current.total,
        vendor=previous.vendor or current.vendor,
        description=previous.description or current.description,
        contact_name=previous.contact_name or current.contact_name,
        contact_email=previous.contact_email or current.contact_email,
    )


def required_email_is_valid(value: object) -> bool:
    """Return whether a required email is present and conservatively valid.

    ``fullmatch``, not ``match``: with ``match`` the pattern would accept
    "alex@vendor.com and also bob@vendor.com" by matching only the prefix, and
    the trailing text would ride into the Smartsheet email cell.

    Blank returns False -- this helper is only ever asked about REQUIRED
    addresses, so absent and malformed deserve the same prompt.
    """
    return _EMAIL_RE.fullmatch(str(value or "").strip()) is not None


def tax_alert_message(status: object) -> str:
    """Return the prominent, non-blocking tax alert for a quote analysis.

    Returns "" only for the one status that needs no alert. Everything else --
    "excluded", "unclear", None, an unrecognised string from the analyzer --
    falls through to the strongest message. Failing toward the warning is the
    point: the tool cannot verify tax, and the PO amount must be the final
    payable total, so silence is only safe when the quote explicitly said so.

    NON-BLOCKING by design. It never becomes a warning in po_context, because a
    quote genuinely may be tax-exempt and blocking would strand those requests.
    """
    normalized = str(status or "").strip().casefold()
    if normalized == "included":
        return ""
    if normalized == "excluded":
        return (
            "The quote says tax is not included. Make sure the PO/CO amount "
            "includes any applicable tax before generating the package."
        )
    return (
        "No tax was found in the quote. Verify whether tax applies and make sure "
        "the PO/CO amount is the final payable total."
    )


def review_needs(
    *,
    routing_ready: bool,
    request_type: object,
    original_po_number: object,
    job_number: object,
    asset_resolved: bool,
    total: object,
    vendor: object,
    description: object,
    contact_name: object,
    contact_email: object,
) -> ReviewNeeds:
    """Classify unresolved/invalid values for exception-only visible prompts.

    Keyword-only so a caller cannot transpose two of nine same-typed arguments.
    That mistake would be silent -- swapping ``vendor`` and ``description``
    still type-checks and still produces a plausible-looking panel.

    ``routing_ready`` and ``asset_resolved`` arrive already decided because
    they depend on catalog lookups this module deliberately does not perform.
    Note the polarity flip: they are READY flags, the returned fields are NEEDS
    flags.

    Two conditional rules, both business policy rather than emptiness:

    * ``original_po_number`` is required only for a CHANGE ORDER, compared
      against that exact spelling;
    * ``total`` uses the shared currency parser and treats unparseable and
      non-positive alike, so "0.00" and "call for pricing" both ask.

    A field with a safe default must NEVER be listed here. Anything returned
    True both holds the disclosure panel open and gets a highlight bar, so
    flagging a defaulted field trains operators to ignore the mark.
    """
    amount = parse_amount(total)
    return ReviewNeeds(
        routing=not routing_ready,
        original_po_number=(
            str(request_type or "").strip() == "CHANGE ORDER"
            and not str(original_po_number or "").strip()
        ),
        job_number=not str(job_number or "").strip(),
        asset=not asset_resolved,
        total=amount is None or amount <= 0,
        vendor=not str(vendor or "").strip(),
        description=not str(description or "").strip(),
        contact_name=not str(contact_name or "").strip(),
        contact_email=not required_email_is_valid(contact_email),
    )
