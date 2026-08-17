"""Build a verified Smartsheet-ready snapshot from the PO workflow.

The handoff never assumes that old Streamlit session values are current. It
checks the analyzed quote fingerprint, identifies the active quote source,
reconstructs the reviewed inclusions/exclusions, validates the generated scope
PDF signature, applies the canonical PO rules, and emits a context ID used to
isolate all Smartsheet page widgets.

What depends on this module
---------------------------
``app.web_ui`` calls :func:`build_po_context` once per rerun and hands the
result to ``app.smartsheet_inline.render_inline_smartsheet_handoff``, which
reads ``fields``, ``warnings``, ``attachments``, ``attachment_base`` and
``context_id``. ``app.memory`` is keyed by the two memory-context helpers
below. ``tests/test_po_context.py`` is the behavioural contract.

The coupling that has no compiler
---------------------------------
This module reconstructs the operator's answers by reading
``st.session_state`` keys BY EXACT STRING -- ``contract_<tok>``,
``gsite_<tok>_<contract>``, ``asset_<tok>_<contract>_<site>``,
``inc_<tok>_<index>`` and roughly twenty more. Nothing links those strings to
the widgets in ``app.web_ui`` that produce them. Rename a key on either side
and NOTHING raises: the lookup simply misses, the documented default applies,
and the field reaches Smartsheet blank or carrying the previous quote's value.
That failure is invisible until somebody reads the submitted form.

Three literals are duplicated here on purpose rather than imported, because
importing ``app.web_ui`` from this module would be an import cycle:
``_CONTRACT_PLACEHOLDER``, ``_SITE_PLACEHOLDER``, and the "None Applicable"
spelling in :func:`_asset_value`. Each has a twin in ``app.web_ui``; a fourth,
the asset placeholder prefix, lives in ``po_rules.normalize_asset_id``.
Changing one copy alone is silent in exactly the same way.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from app import contracts
from app.config import (
    FACILITIES,
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,
    lookup_cost_code,
)
from app.job_numbers import JOB_NUMBER_OPTIONS, RRH_JOB_NUMBERS
from app.po_rules import (
    PURCHASE_ROUTE_LABELS,
    classify_po,
    normalize_asset_id,
    parse_amount,
)

# Byte-for-byte copies of ``web_ui.CONTRACT_PLACEHOLDER`` and
# ``web_ui.SITE_PLACEHOLDER``. They are the selectbox's "not chosen yet"
# sentinels, and the ONLY thing separating them from a real answer is this
# string comparison. If web_ui's wording is edited without editing these, the
# comparison stops matching, the prompt text itself is treated as the operator's
# choice, and "— Select a site —" is exported into the Smartsheet SITE field.
# No exception, no warning -- the only symptom is the submitted form.
_CONTRACT_PLACEHOLDER = "— Select a contract —"
_SITE_PLACEHOLDER = "— Select a site —"
# Display label -> internal key, inverting the config dictionaries. Inverting is
# only lossless while every display value is unique; both source dicts satisfy
# that today. Adding a second facility abbreviated "UMMC", or a second category
# displayed "Repairs", would silently drop one of them from this map, and the
# affected site would then export a blank cost code with no error.
_SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
_CATEGORY_LABEL_TO_KEY = {label: key for key, label in WORK_CATEGORY_DISPLAY.items()}
# Declared as the fields the handoff page is expected to present read-only, so
# the reviewed package cannot be edited after the fact. Carried on POContext and
# currently read by NOTHING -- smartsheet_inline builds its own display. Left in
# place because removal is a separate verified phase; do not read its presence
# as evidence that anything enforces it.
_LOCKED_FIELDS = (
    "request_type",
    "order_type",
    "purchase_route",
    "contract",
    "site",
    "site_location",
    "work_category",
    "cost_code",
    "object_account",
    "agreement_type",
    "asset_id",
    "vendor",
    "contact_name",
    "contact_email",
    "description",
    "description_of_work",
    "scope_of_work",
    "subtotal",
    "tax",
    "total",
    "tax_status",
    "leave_request_completed",
    "po_number",
    "work_order_number",
    "original_po_number",
    "dispatch_service_center",
)

# RRH_JOB_NUMBERS is FILTERED from JOB_NUMBER_OPTIONS, so this default is
# guaranteed to survive the ``in JOB_NUMBER_OPTIONS`` membership test at the
# bottom of build_po_context. Hard-coding the literal string here instead would
# break that guarantee the next time the catalog is re-exported: the default
# would fail the membership test, job_number would export blank, and the only
# sign would be a "Confirm the job number" warning the operator cannot clear by
# choosing anything.
RRH_DEFAULT_JOB_NUMBER = RRH_JOB_NUMBERS[0]
# Session-state slot for a prepared context, described in
# docs/SMARTSHEET_PO_IMPLEMENTATION_HANDOFF_2026-08-04.md. The current page
# passes the POContext straight to smartsheet_inline instead, so nothing reads
# or writes this key today.
PREPARED_PO_CONTEXT_STATE_KEY = "_prepared_smartsheet_po_context"


@dataclass(frozen=True)
class POContext:
    """One immutable snapshot of a reviewed purchase order.

    Guarantees, relied on by ``app.smartsheet_inline``:

    * ``fields`` always carries EVERY Smartsheet key, using "" for absent
      values rather than omitting them, so a caller can index without
      ``.get``. Blank-by-policy fields (po_number, work_order_number,
      leave_request_completed) are blank on purpose, not unfilled.
    * ``attachments`` is positional: index 0 is the vendor's quote, index 1 is
      the generated MSAPO form PDF. ``smartsheet_inline`` and
      ``smartsheet.download_names`` both depend on that order.
    * ``warnings`` is de-duplicated and empty exactly when ``ready`` is True.
      An empty tuple is the ONLY thing that authorises submission.

    ``frozen=True`` is shallow: ``fields`` is a plain dict and a caller can
    still mutate it in place. The frozen marker prevents rebinding the
    attribute, not editing the mapping -- do not treat it as a security
    boundary, and copy before mutating (smartsheet_inline does).

    ``locked_fields`` defaults to a TUPLE, not a list. That is what makes a
    shared class-level default safe here; a list would be the classic mutable
    default shared across every instance.
    """

    fields: dict[str, str]
    attachments: tuple[tuple[str, bytes], ...]
    attachment_base: str
    warnings: tuple[str, ...]
    context_id: str
    locked_fields: tuple[str, ...] = _LOCKED_FIELDS

    @property
    def ready(self) -> bool:
        return not self.warnings


def _state_text(state: Mapping[str, Any], key: str, default: str = "") -> str:
    """Read one session value as stripped text, or ``default``.

    ``default`` applies when the key is ABSENT or holds ``None``. It does NOT
    apply when the key holds "" -- and Streamlit stores "" for a text input the
    operator has cleared. That asymmetry is deliberate and load-bearing: an
    operator who deletes the analyzer's vendor guess must get a blank vendor and
    the matching blocking warning, not the guess silently restored on the next
    rerun. Rewriting this as ``state.get(key) or default`` would reinstate
    exactly that bug, and it would look like a simplification.
    """
    value = state.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def _existing_path(value: Any) -> Path | None:
    """Return ``value`` as an existing regular file, else ``None``.

    NOT CALLED ANYWHERE. It survives from the era when the generated document
    travelled as a path on disk; the MSAPO reversal made the builder return
    bytes (see docs/COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md §2.1) and
    nothing has needed a path since. Kept because deletion is a separate
    verified phase, not because a caller exists.
    """
    if not value:
        return None
    try:
        path = Path(value)
    except TypeError:
        return None
    return path if path.exists() and path.is_file() else None


def _safe_basename(contract: str, site: str, description: str, rrh: bool) -> str:
    """Build the download stem for the two-file package.

    The result is consumed by ``smartsheet.download_names``, whose stem regex
    strips a trailing "MSAPO" or "Scope" word -- so the literal "MSAPO" tail
    below is not decoration, it is the token that regex expects to find and
    remove. A stem built without it renames both downloads incorrectly.

    Two different sanitisers run, and they are not redundant:

    * ``[^\\w\\s-]`` cleans only the free-text DESCRIPTION, which comes from the
      analyzer and can contain anything the vendor wrote.
    * ``[<>:"/\\|?*\\x00-\\x1f]`` then cleans the WHOLE name, because the
      contract and site segments never passed through the first pass and come
      from catalogs that legitimately contain "/" and ":" (for example
      "LCMC - Children's"). Those are the characters Windows refuses in a
      filename, and the operator downloads these files onto Windows.

    The 50-character truncation trims back to the last whole word only when it
    actually cut mid-string, so a short description is never shortened further.
    ``or "PO MSAPO"`` cannot fire while "MSAPO" is an unconditional part; it is
    a guard against a future edit that makes every part optional.
    """
    prefix = "RRH" if rrh else contract.strip()
    clean_description = re.sub(r"[^\w\s-]", "", description or "SOW")[:50]
    if len(clean_description) == 50 and " " in clean_description:
        clean_description = clean_description.rsplit(" ", 1)[0]
    parts = [prefix, site.strip(), clean_description.strip(), "MSAPO"]
    name = " ".join(part for part in parts if part)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return re.sub(r"\s+", " ", name).strip() or "PO MSAPO"


def _selected_contract(state: Mapping[str, Any], token: str) -> str:
    """The chosen contract, or "" when the placeholder is still selected."""
    contract = _state_text(state, f"contract_{token}")
    return "" if contract == _CONTRACT_PLACEHOLDER else contract


def _selected_site(state: Mapping[str, Any], token: str, contract: str) -> str:
    """The chosen site, or "" when nothing is selected.

    RRH and everyone else store the site under DIFFERENT keys because they use
    different controls: RRH picks a short facility label from a fixed list
    (``site_<tok>``), while a generic contract either picks from its own site
    list (``gsite_<tok>_<contract>``) or, for contracts with no configured
    sites, types one (``gsitetxt_<tok>_<contract>``). The contract name is part
    of the generic keys so switching contracts cannot carry a site across.

    The dropdown is consulted before the free-text box on purpose: web_ui
    renders only one of the two per contract, so at most one is ever populated.
    """
    if contracts.is_rrh(contract):
        site = _state_text(state, f"site_{token}")
    else:
        site = (
            _state_text(state, f"gsite_{token}_{contract}")
            or _state_text(state, f"gsitetxt_{token}_{contract}")
        )
    return "" if site == _SITE_PLACEHOLDER else site


def _routing_fields(
    state: Mapping[str, Any], token: str, contract: str, site: str, analysis: Any
) -> tuple[str, str, str]:
    """Return ``(work category label, cost code, facility address)``.

    Must mirror ``web_ui._routing_snapshot`` and ``_render_routing_controls``.
    Where those three disagree, the operator sees one value and Smartsheet
    receives another, with nothing to signal the divergence.

    Two precedence rules are load-bearing:

    * RRH cost code -- the CONFIGURED code for a mapped site+category wins, and
      the manually typed code is consulted only when no mapping exists. web_ui
      renders no text box at all when a mapping exists, so reversing this would
      let a stale typed value override a configured code that the operator
      cannot even see to correct.
    * Non-RRH address -- exported ONLY when the chosen site still equals the
      site the analyzer read off the quote. Once the operator overrides the
      site, the analyzer's address belongs to a different building, and
      shipping it would send a crew to the wrong address.

    ``_CATEGORY_LABEL_TO_KEY.get(label, label)`` falls back to the label
    unchanged so a value already stored as an internal key (an older session,
    or a category with no display entry) still reaches lookup_cost_code.
    """
    rrh = contracts.is_rrh(contract)
    if rrh:
        site_key = _SITE_LABEL_TO_KEY.get(site)
        category_label = _state_text(state, f"cat_{token}_{site_key}") if site_key else ""
        category_key = _CATEGORY_LABEL_TO_KEY.get(category_label, category_label)
        cost_code = (
            lookup_cost_code(site_key, category_key) if site_key and category_key else None
        ) or (
            _state_text(state, f"manualcost_{token}_{site_key}") if site_key else ""
        )
        address = str(FACILITIES.get(site_key, {}).get("address", "")) if site_key else ""
        return category_label, cost_code, address

    category = _state_text(state, f"gcat_{token}_{contract}")
    cost_code = _state_text(state, f"gcost_{token}_{contract}")
    extracted_site = str(getattr(analysis, "facility_name", "") or "").strip()
    address = (
        str(getattr(analysis, "facility_address", "") or "").strip()
        if site and site == extracted_site
        else ""
    )
    return category, cost_code, address


def _asset_value(state: Mapping[str, Any], token: str, contract: str, site: str) -> str:
    """The selected asset UID, or the "no asset" sentinel.

    Never returns "": the sentinel string is what ``po_rules.normalize_asset_id``
    recognises and maps to a blank Asset ID. Returning "" here instead would
    reach the same result today but would break the moment any caller starts
    distinguishing "not chosen" from "deliberately none".
    """
    no_asset_key = f"noasset_{token}_{contract}_{site}"
    # Retain the old checkbox key only as a compatibility read. The active UI
    # uses one asset dropdown with a No asset option and exports the full UID.
    if bool(state.get(no_asset_key, False)):
        return "None Applicable"
    return _state_text(state, f"asset_{token}_{contract}_{site}") or "None Applicable"


def _strip_ai_wrapper(text: str) -> str:
    """Unwrap an "[AI ESTIMATE: ...]" marker on an inclusion or exclusion.

    ``web_ui._strip_ai_wrapper`` is a byte-identical copy. The duplication is
    deliberate -- web_ui imports this module, so the dependency can only run one
    way -- and it is load-bearing: see :func:`_unified_review_items`.
    """
    match = re.search(r"\[AI ESTIMATE:\s*(.+?)\]", text)
    return match.group(1).strip() if match else text.strip()


def _unified_review_items(analysis: Any, section: str) -> list[str]:
    """Rebuild one review list in the SAME ORDER web_ui rendered it.

    This is the twin of ``web_ui._build_unified_lists``: quoted items first in
    analyzer order, then any ai_assumptions for this section that are not
    already present, de-duplicated on the stripped text.

    The order is a CONTRACT, not a preference. web_ui keys each checkbox
    positionally as ``inc_<token>_<index>`` / ``exc_<token>_<index>``, and
    :func:`_reviewed_lists` maps those indexes back onto this list. Sorting the
    items, changing the de-duplication rule, or stripping differently in one of
    the two copies shifts the list by an entry, and the operator's ticks are
    then attributed to the WRONG inclusions -- in the Smartsheet scope text and
    in the PDF the administrator signs. Nothing raises. Change both or neither.

    ``getattr`` rather than attribute access because the analysis object is a
    QuoteAnalysis in production and a SimpleNamespace in the tests.
    """
    raw_items = list(getattr(analysis, "inclusions" if section == "inclusion" else "exclusions", []) or [])
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        clean = _strip_ai_wrapper(str(item))
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    for assumption in list(getattr(analysis, "ai_assumptions", []) or []):
        assumption_section = str(getattr(assumption, "section", "") or "")
        text = str(getattr(assumption, "text", "") or "").strip()
        if assumption_section == section and text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _reviewed_lists(
    state: Mapping[str, Any], token: str, analysis: Any
) -> tuple[list[str], list[str]]:
    """The items the operator left ticked, in render order.

    A MISSING checkbox key defaults to True, matching web_ui's ``value=True``.
    That default is why an item is included on the very first rerun, before any
    checkbox has written state. It also means an item whose widget did not
    render this pass silently returns to "included" -- Streamlit drops keys for
    widgets absent from a rerun, so do not "tidy" the default to False on the
    theory that absent means unchecked; that would quietly delete reviewed scope
    from the PDF and from Smartsheet.
    """
    inclusions = _unified_review_items(analysis, "inclusion")
    exclusions = _unified_review_items(analysis, "exclusion")
    selected_inclusions = [
        text for index, text in enumerate(inclusions)
        if bool(state.get(f"inc_{token}_{index}", True))
    ]
    selected_exclusions = [
        text for index, text in enumerate(exclusions)
        if bool(state.get(f"exc_{token}_{index}", True))
    ]
    return selected_inclusions, selected_exclusions


def _document_signature(
    token: str,
    contract: str,
    site: str,
    inclusions: list[str],
    exclusions: list[str],
    *,
    vendor: str = "",
    scope: str = "",
) -> str:
    """Fingerprint of everything the generated MSAPO PDF is built from.

    web_ui computes this at generation time and stores it beside the PDF bytes;
    build_po_context recomputes it from live state and refuses to attach the PDF
    when the two differ. That is the ONLY defence against attaching a document
    that no longer describes the reviewed package -- the PDF bytes carry no
    self-describing metadata, so a stale file is indistinguishable from a fresh
    one by inspection.

    The payload must contain every input that changes the rendered document.
    Adding a new field to the PDF without adding it here creates a stale PDF
    that passes validation: it is attached, submitted, and silently wrong.
    Adding a field that does NOT affect the document is merely annoying -- it
    forces a needless regeneration.

    Note that ``vendor`` here is the operator's CORRECTED vendor, while the
    template currently prints ``analysis.vendor_name``. Correcting the vendor
    therefore invalidates the PDF and forces a regeneration that does not
    actually change the vendor line. Reported; do not "fix" it by dropping
    vendor from this payload, which would only hide the divergence.

    web_ui imports this private name directly. It is private by convention only.
    """
    payload = {
        "analysis": token,
        "contract": contract,
        "site": site,
        "vendor": vendor,
        "scope": scope,
        "inclusions": inclusions,
        "exclusions": exclusions,
    }
    # sort_keys makes the digest independent of dict insertion order, and
    # ensure_ascii=False keeps a vendor name with an accent hashing to the same
    # value on both sides. Change either and every previously generated PDF
    # instantly reads as stale.
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reviewed_scope(
    scope: str, inclusions: list[str], exclusions: list[str]
) -> str:
    """Flatten the reviewed scope into the single Smartsheet scope cell.

    Smartsheet has one free-text scope field, so the inclusion and exclusion
    lists are appended as labelled bullet blocks rather than lost. The 20-char
    Description of Work field is NOT a substitute for this; see the note beside
    ``description_of_work`` in build_po_context.
    """
    sections = [scope.strip()]
    if inclusions:
        sections.append("Inclusions:\n" + "\n".join(f"- {item}" for item in inclusions))
    if exclusions:
        sections.append("Exclusions:\n" + "\n".join(f"- {item}" for item in exclusions))
    return "\n\n".join(section for section in sections if section)


def _active_quote_attachment(
    state: Mapping[str, Any], quote_text: str
) -> tuple[tuple[str, bytes] | None, list[str]]:
    """Return the first attachment: the operator's ORIGINAL file if provable.

    Returns ``((filename, bytes), warnings)``, or ``(None, warnings)`` when
    there is no quote at all.

    Five independent facts must all hold before the uploaded bytes are used, and
    they exist because attachment 1 is what contract administration reads as
    "the vendor's quote". Attaching the wrong file is worse than attaching a
    plain-text stand-in.

    READ THIS BEFORE SIMPLIFYING THE GATE. When any check fails, the function
    does not error -- it falls through and synthesises "Vendor Quote.txt" from
    the analyzed text. The package still generates, still validates, and still
    submits; the operator gets a text file where they expected their PDF, and
    only one of the failure paths (upload selected, bytes present, extraction
    empty) raises a warning. Every other path is SILENT by design, because the
    common cause is benign: the same text legitimately moved from an upload to
    the paste box, which ``quote_source`` alone distinguishes.

    ``quote_source`` gates the whole thing. "paste" excludes a stale upload even
    when its extracted text is byte-identical to the pasted text -- pinned by
    test_explicit_paste_source_never_reuses_a_stale_upload_with_identical_text.
    "" is accepted because a legacy session predates the field being written.
    """
    warnings: list[str] = []
    quote_source = _state_text(state, "quote_source")
    uploaded_bytes = state.get("uploaded_file_bytes")
    uploaded_name = _state_text(state, "uploaded_file_name")
    extracted_text = _state_text(state, "extracted_text")
    extract_hash = _state_text(state, "extract_hash")

    upload_allowed = quote_source in {"", "upload", "synthetic"}
    # The last two conditions are the ones that matter, and they are separate
    # checks of two separate things:
    #   * extracted_text == quote_text proves the ANALYSIS describes this file;
    #   * sha256(uploaded_bytes) == extract_hash proves the BYTES still in state
    #     are the ones that text was extracted from.
    # Either alone is satisfiable by a half-updated session -- new file uploaded
    # but extraction failed, or extraction succeeded for a file the operator has
    # since replaced -- and either alone would attach the wrong document.
    upload_valid = (
        upload_allowed
        and
        isinstance(uploaded_bytes, bytes)
        and bool(uploaded_bytes)
        and bool(uploaded_name)
        and bool(extracted_text)
        and extracted_text.strip() == quote_text.strip()
        and hashlib.sha256(uploaded_bytes).hexdigest() == extract_hash
    )
    if upload_valid:
        return (uploaded_name, uploaded_bytes), warnings

    if (
        quote_source == "upload"
        and isinstance(uploaded_bytes, bytes)
        and uploaded_bytes
        and not extracted_text
    ):
        warnings.append(
            "The current uploaded file was not successfully extracted; the prior analysis may not describe it."
        )
    if quote_text:
        return ("Vendor Quote.txt", quote_text.encode("utf-8")), warnings
    return None, warnings


def _attachments(
    state: Mapping[str, Any], *, base: str, quote_text: str, scope_pdf_valid: bool
) -> tuple[tuple[tuple[str, bytes], ...], list[str]]:
    """Assemble the two-file package, quote first, MSAPO form PDF second.

    Order is the contract with ``smartsheet.download_names``, which labels by
    POSITION rather than by inspecting the bytes: index 0 becomes "Quote" and
    index 1 becomes "MSAPO". Appending in a different order silently mislabels
    both downloads.

    A missing or stale PDF yields a ONE-file tuple rather than a placeholder.
    That is what lets build_po_context detect the incomplete package by length
    and block submission; substituting an empty entry to keep the length at two
    would defeat that check.
    """
    warnings: list[str] = []
    result: list[tuple[str, bytes]] = []
    quote_attachment, source_warnings = _active_quote_attachment(state, quote_text)
    warnings.extend(source_warnings)
    if quote_attachment:
        result.append(quote_attachment)

    scope_pdf = state.get("scope_pdf_bytes")
    if scope_pdf_valid and isinstance(scope_pdf, bytes) and scope_pdf:
        result.append((f"{base}.pdf", scope_pdf))
    return tuple(result), warnings


def _money(value: str) -> Decimal | None:
    """Alias for the ONE currency parser in po_rules.

    Do not give this module its own parsing. ``po_rules.parse_amount``
    deliberately REFUSES ambiguous input instead of repairing it -- an earlier
    version stripped every non-digit and turned "1e3" into 13 -- and the
    subtotal+tax reconciliation below, classify_po, and smartsheet's amount
    validation must all agree about what a string means.
    """
    return parse_amount(value)


def _context_id(fields: Mapping[str, str], attachments: tuple[tuple[str, bytes], ...]) -> str:
    """Identity of one exact reviewed package, as 20 hex characters.

    Used as a widget-key prefix on the handoff page, so a new quote cannot
    reopen the previous quote's panel or inherit its half-typed values. It hashes
    attachment CONTENT, not filenames, so renaming a file does not fabricate a
    new package and swapping two files of the same name does not reuse an old
    one.

    20 characters is a display/key-length convenience. Do not shorten it further
    -- a collision would silently merge two different packages' widget state.
    """
    payload = {
        "fields": dict(sorted(fields.items())),
        "attachments": [
            {
                "name": name,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in attachments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def account_manager_memory_context_id(context: POContext) -> str:
    """Return a package identity that is stable while correcting requester name.

    The UI context includes requester name so changing it refreshes the generated
    handoff. Requester-memory deduplication intentionally excludes only that one
    field, allowing a correction on the same otherwise-identical package to move
    the event instead of creating a second remembered use.
    """
    fields = {
        field: value
        for field, value in context.fields.items()
        if field != "requester_name"
    }
    return _context_id(fields, context.attachments)


def vendor_contact_memory_context_id(context: POContext) -> str:
    """Return a stable package identity while correcting vendor/contact data.

    Vendor-contact memory records one event for the underlying request. The
    excluded fields can therefore be corrected without teaching both the old
    and new representative, vendor spelling, or requester assignment.
    """
    excluded = {"requester_name", "vendor", "contact_name", "contact_email"}
    fields = {
        field: value
        for field, value in context.fields.items()
        if field not in excluded
    }
    return _context_id(fields, context.attachments)


def build_po_context(
    state: Mapping[str, Any], env: Mapping[str, str] | None = None
) -> POContext | None:
    """Rebuild the whole Smartsheet package from session state.

    Returns ``None`` -- not an empty context -- when no analysis exists, which
    is the "nothing to submit yet" signal every caller checks first.

    Otherwise it ALWAYS returns a POContext, even for a hopelessly incomplete
    form. Problems are accumulated into ``warnings`` rather than raised, because
    the page needs to render the partially-filled snapshot while telling the
    operator what is still missing. ``context.ready`` (no warnings) is the only
    submission gate; a caller that checks ``context is not None`` and stops
    there will happily submit a blank package.

    Assumes nothing about the freshness of any value it reads. Streamlit keeps
    widget state for keys whose widgets did not render, so every read here is
    treated as potentially stale and re-validated: the quote fingerprint against
    the stored text, the PDF signature against the reviewed content, the job
    number against the catalog, the request type against the allowed pair.

    ``env`` is accepted and IGNORED -- see the comment below.
    """
    analysis = state.get("analysis")
    if analysis is None:
        return None

    # ``env`` remains in the public signature for backwards compatibility with
    # older callers, but requester identity must never come from a deployment
    # default. The requester is the person currently filling out the form and
    # is collected before generation, with device+account-scoped memory after
    # the first verified package.
    _ = env
    # "x" is the same placeholder token web_ui uses before an analysis exists,
    # so both sides build identical (and equally meaningless) keys in that
    # window rather than one side reading keys the other never wrote.
    token = _state_text(state, "analysis_token", "x") or "x"
    purchase_route = _state_text(state, f"purchase_route_{token}")
    contract = _selected_contract(state, token)
    site = _selected_site(state, token, contract) if contract else ""
    rrh = contracts.is_rrh(contract)
    category, cost_code, address = _routing_fields(
        state, token, contract, site, analysis
    )
    inclusions, exclusions = _reviewed_lists(state, token, analysis)
    scope = _state_text(
        state,
        f"scope_{token}",
        str(getattr(analysis, "scope_of_work", "") or ""),
    ).strip()

    # Truncated TWICE on purpose: once on the analyzer's fallback and again on
    # whatever came back from state. The second slice is the final boundary --
    # the live Smartsheet form caps this box at 20 characters, and a longer
    # value is silently truncated (or rejected) by Smartsheet itself, where the
    # operator never sees what was lost. The full text survives in scope_of_work
    # and in the attached PDF.
    description = _state_text(
        state,
        f"desc_{token}",
        str(getattr(analysis, "short_description", "") or "")[:20],
    )[:20]
    vendor = _state_text(
        state,
        f"vendor_{token}",
        str(getattr(analysis, "vendor_name", "") or ""),
    )
    quote_text = _state_text(state, "quote_text")
    # Must match web_ui's computation EXACTLY -- same 12-character slice, same
    # "ignore" error handler. The handler is not tidiness: OCR of a scanned
    # quote regularly yields lone surrogates, and utf-8 without "ignore" raises
    # on them. If the two sides ever disagree, every package reports a
    # fingerprint-mismatch warning that no operator action can clear.
    expected_token = hashlib.sha256(quote_text.encode("utf-8", "ignore")).hexdigest()[:12] if quote_text else ""
    base = _safe_basename(contract, site, getattr(analysis, "project_description", ""), rrh)

    expected_document_signature = _document_signature(
        token,
        contract,
        site,
        inclusions,
        exclusions,
        vendor=vendor,
        scope=scope,
    )
    stored_document_signature = _state_text(state, "scope_pdf_signature")
    scope_pdf_bytes = state.get("scope_pdf_bytes")
    # The magic-byte check is the second, independent guard. LibreOffice can
    # exit successfully having written an HTML error page or a zero-length file;
    # without this the package would carry a "PDF" that Smartsheet accepts as an
    # opaque blob and that opens as garbage on the administrator's desk.
    # ``state`` keys still say scope_pdf_* for the MSAPO form -- deliberately
    # unchanged by the 2026-08-12 reversal so only the bytes' origin moved.
    document_valid = (
        stored_document_signature == expected_document_signature
        and isinstance(scope_pdf_bytes, bytes)
        and scope_pdf_bytes.startswith(b"%PDF-")
    )
    attachments, source_warnings = _attachments(
        state,
        base=base,
        quote_text=quote_text,
        scope_pdf_valid=document_valid,
    )

    raw_asset_id = _asset_value(state, token, contract, site)
    asset_id = normalize_asset_id(raw_asset_id)
    reviewed_scope = _reviewed_scope(scope, inclusions, exclusions)
    total_value = _state_text(
        state, f"total_{token}", str(getattr(analysis, "total_amount", "") or "")
    )
    # classify_po RAISES on an unchosen route or an unusable amount, and the
    # exception text is the operator-facing message. Catching it into a warning
    # rather than letting it propagate is what keeps Object Account and
    # Agreement Type BLANK instead of defaulting -- a default here was the
    # reported "5511-Subcontractor / 03 - MSAPO every single time" defect.
    # Blank plus a warning is safe; a plausible default is not.
    try:
        classification = classify_po(purchase_route, total_value)
        classification_error = ""
    except ValueError as exc:
        classification = None
        classification_error = str(exc)
    request_type = _state_text(
        state,
        f"request_type_{token}",
        str(getattr(analysis, "request_type_guess", "") or "PO"),
    )
    # Re-validated against the exact Smartsheet option spellings because the
    # value can arrive from the analyzer's free-text guess. Anything else falls
    # back to "PO", the overwhelmingly common case.
    if request_type not in {"PO", "CHANGE ORDER"}:
        request_type = "PO"
    # Forced blank for a plain PO even when stale state holds a number: the
    # operator may have started a change order and switched back, and an
    # original PO number on a new PO is a data-entry error contract
    # administration has to chase. Pinned by
    # test_new_po_forces_original_po_blank_even_if_stale_state_has_a_value.
    original_po_number = (
        _state_text(
            state,
            f"original_po_{token}",
            str(getattr(analysis, "original_po_number", "") or ""),
        )
        if request_type == "CHANGE ORDER"
        else ""
    )
    # Both keys embed the CONTRACT, so switching contracts intentionally drops
    # the previous requester and job number rather than carrying a Tulane job
    # number onto an RRH request. The cost is that a contract typo loses a typed
    # requester name; that is the accepted trade.
    requester_name = _state_text(state, f"requester_{token}_{contract}")
    raw_job_number = _state_text(
        state,
        f"job_number_{token}_{contract}",
        RRH_DEFAULT_JOB_NUMBER if rrh else "",
    )
    # Membership in the verified 87-value catalog, not a format check. A job
    # number that merely looks right is rejected: Smartsheet's JOB NUMBER is a
    # picklist, and an unlisted value is dropped on submission with no error --
    # the request then lands unbillable. Exporting "" instead produces the
    # blocking warning below, which the operator can actually act on.
    job_number = raw_job_number if raw_job_number in JOB_NUMBER_OPTIONS else ""
    # EVERY Smartsheet key is present, blanks included. smartsheet.py's
    # validate_submission_fields checks only keys it is given and leaves absence
    # to missing_required_fields, so a key omitted here is a required field that
    # is never reported missing -- silence, then a rejected or half-empty
    # submission. Three are blank BY POLICY and must stay blank:
    # leave_request_completed, po_number and work_order_number are filled in by
    # contract administration after the request is accepted, and smartsheet.py
    # actively rejects the payload if the tool supplies them.
    fields = {
        "requester_name": requester_name,
        "request_type": request_type,
        "order_type": PURCHASE_ROUTE_LABELS.get(purchase_route, ""),
        "purchase_route": purchase_route,
        "contract": contract,
        "site": site,
        "job_number": job_number,
        "site_location": site,
        "facility_address": address,
        "related_to_om": "",
        "billing_method": "",
        "customer_po": "",
        "work_category": category,
        "cost_code": cost_code,
        "object_account": classification.object_account if classification else "",
        "agreement_type": classification.agreement_type if classification else "",
        "leave_request_completed": "",
        "po_number": "",
        "work_order_number": "",
        "original_po_number": original_po_number,
        "asset_id": asset_id,
        "vendor": vendor,
        "contact_name": _state_text(
            state, f"contact_{token}", str(getattr(analysis, "contact_name", "") or "")
        ),
        "contact_email": _state_text(
            state, f"cemail_{token}", str(getattr(analysis, "contact_email", "") or "")
        ),
        "description": description,
        # Smartsheet's Description of Work field is capped at 20 characters.
        # The complete reviewed scope remains in the generated PDF only.
        "description_of_work": description,
        "scope_of_work": reviewed_scope,
        "estimated_start_date": "",
        "estimated_completion_date": "",
        "customer_representative": "",
        "service_branch_tech_needed": "",
        "subtotal": _state_text(
            state, f"sub_{token}", str(getattr(analysis, "subtotal_amount", "") or "")
        ),
        "tax": _state_text(
            state, f"tax_{token}", str(getattr(analysis, "tax_amount", "") or "")
        ),
        "total": total_value,
        "tax_status": str(getattr(analysis, "tax_status", "") or "").strip(),
        "instructions": _state_text(state, f"instructions_{token}"),
        "dispatch_service_center": "NA",
    }

    # Everything below is ADDITIVE. Each check appends and none returns early,
    # because the operator has to see the complete list of what is still wrong;
    # fixing one item and discovering the next only on the following rerun is
    # how the "needed from you" panel became a treadmill. Order here is the
    # order the operator reads.
    warnings: list[str] = list(source_warnings)
    if quote_text and token != expected_token:
        warnings.append(
            "The analysis fingerprint does not match the stored quote text; re-analyze the quote."
        )
    if not contract:
        warnings.append("Select the contract in Purchase Order Process Control.")
    if not site:
        warnings.append("Select or enter the site in Purchase Order Process Control.")
    if not cost_code:
        warnings.append("Confirm the job cost code before submission.")
    if classification_error:
        warnings.append(classification_error)
    if not fields["requester_name"]:
        warnings.append("Enter the person filling out this request.")
    if not fields["job_number"]:
        warnings.append("Confirm the job number before submission.")
    if request_type == "CHANGE ORDER" and not original_po_number:
        warnings.append("Enter the original PO number for this change order.")
    if not fields["vendor"]:
        warnings.append("Confirm the vendor name before submission.")
    if not fields["contact_name"]:
        warnings.append("Confirm the vendor representative name before submission.")
    if not fields["contact_email"]:
        warnings.append("Confirm the vendor representative email before submission.")
    if not description:
        warnings.append("Confirm a Description of Work of 20 characters or fewer.")
    if not scope:
        warnings.append("Confirm the scope of work before submission.")
    if not fields["total"]:
        warnings.append("Confirm the total amount before submission.")
    if not attachments:
        warnings.append("No verified quote and scope PDF package is available to attach.")
    if not document_valid:
        warnings.append(
            "The MSAPO form PDF is missing or no longer matches the reviewed contract, site, inclusions, and exclusions. Regenerate it."
        )
    # Exactly two files, one of them a PDF. This is deliberately a COUNT check
    # and not a "has a PDF" check: the failure it catches is the quote silently
    # dropping out of the package (see _active_quote_attachment), which would
    # otherwise leave a lone, perfectly valid MSAPO PDF and no evidence of what
    # the vendor actually quoted.
    if len(attachments) != 2 or not any(
        name.lower().endswith(".pdf") for name, _ in attachments
    ):
        warnings.append(
            "The attachment package must contain the original quote and one MSAPO form PDF."
        )
    # 160 is Smartsheet's practical single-line cell limit for this column. The
    # same number is repeated in po_rules.asset_id_is_numeric; they are not
    # linked, so a change needs both.
    if len(asset_id) > 160:
        warnings.append("The selected full Asset ID is unexpectedly long.")

    # Decimal, never float: 0.1 + 0.2 != 0.3 in binary floating point, and this
    # comparison decides whether a real quote is flagged as internally
    # inconsistent. One cent of tolerance absorbs the vendor's own rounding.
    #
    # Deliberately silent when ANY of the three fails to parse. A quote with no
    # stated subtotal is normal, and warning "subtotal plus tax does not equal
    # total" for a missing subtotal would train operators to ignore the message.
    subtotal = _money(fields["subtotal"])
    tax = _money(fields["tax"])
    total = _money(fields["total"])
    if subtotal is not None and tax is not None and total is not None:
        if abs((subtotal + tax) - total) > Decimal("0.01"):
            warnings.append("Subtotal plus sales tax does not equal the total amount.")

    context_id = _context_id(fields, attachments)
    return POContext(
        fields=fields,
        attachments=attachments,
        attachment_base=base,
        # dict.fromkeys de-duplicates while PRESERVING first-seen order;
        # set(warnings) would lose the reading order above and shuffle the
        # panel between reruns. Duplicates are real -- a missing route produces
        # both a classification error and a routing warning.
        warnings=tuple(dict.fromkeys(warnings)),
        context_id=context_id,
    )
