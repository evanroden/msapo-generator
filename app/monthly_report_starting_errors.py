"""Operator-safe reasons for failed ordinary Starting Report DOCX inspection.

Only recognized import-limit and package-structure failures are displayed.
Arbitrary XML/parser/OS exception strings (including paths and source text)
never become UI copy. This helper is presentation-only: it does not alter
the importer, its limits, the staged file or the saved report.
"""
from __future__ import annotations

from app import monthly_report_import as importer
from app import monthly_report_import_ui as stage
from app.monthly_report_upload_limits import byte_limit_label, docx_size_error


_GENERIC = (
    "This report could not be analyzed. Choose a valid DOCX or retry; "
    "your existing work was preserved."
)
_PRESERVED = "Your original file and existing report were not changed."


def starting_docx_failure_notice(exc: Exception) -> str:
    """Name only the first *known* rejection with its effective runtime cap.

    The staging route checks the raw stream cap independently of the ZIP
    inspector. The latter's public exceptions are recognized by exact text,
    never by arbitrary substrings or unknown third-party parser messages.
    The alternate mapping importer has its own controls and is not modified.
    """
    reason = str(exc)

    # The ordinary upload's stream limit is enforced by staging even when a
    # native picker or declared size is inaccurate. Preserve its own limit,
    # not the (larger) shared-template shelf limit.
    if reason == docx_size_error(stage.MAX_DOCX_BYTES):
        return (
            f"This DOCX exceeds the {byte_limit_label(stage.MAX_DOCX_BYTES)} "
            f"Starting Report upload limit. Choose a smaller import copy. {_PRESERVED}"
        )

    if not isinstance(exc, importer.ImportError):
        return _GENERIC

    if reason == "DOCX exceeds the 128 MB import limit. Split the source document and retry.":
        return (
            f"This DOCX exceeds the {byte_limit_label(importer.MAX_DOCX_BYTES)} "
            f"DOCX import limit. Split it into smaller Word copies. {_PRESERVED}"
        )
    if reason == "Expanded DOCX exceeds 256 MB. Split it before importing.":
        return (
            f"This DOCX expands beyond the {byte_limit_label(importer.MAX_EXPANDED_BYTES)} "
            f"parsing limit. Split the Word document before retrying. {_PRESERVED}"
        )
    if reason == "The DOCX contains an oversized or encrypted part.":
        return (
            f"This DOCX contains a part larger than {byte_limit_label(importer.MAX_MEMBER_BYTES)} "
            f"or an encrypted part. Remove the oversized attachment or encryption "
            f"from an import copy. {_PRESERVED}"
        )
    if reason == "DOCX XML exceeds the safe parsing budget.":
        return (
            f"This DOCX exceeds its XML parsing limits "
            f"({byte_limit_label(importer.MAX_XML_BYTES)} per XML part; "
            f"{byte_limit_label(importer.MAX_XML_TOTAL)} total). "
            f"Split or simplify the Word import copy. {_PRESERVED}"
        )
    if reason == "DOCX XML complexity exceeds the parsing budget.":
        return (
            f"This DOCX has too many nested XML elements for safe parsing. "
            f"Simplify complex Word artwork in a separate import copy. {_PRESERVED}"
        )
    if reason == "Document exceeds the item/text/table review budget. Split it and retry; nothing was saved.":
        return (
            f"This DOCX has more items, text or table cells than can be reviewed "
            f"safely in one import. Split it into smaller Word copies. {_PRESERVED}"
        )
    if reason == "The DOCX contains too many or duplicate package parts.":
        return (
            f"This DOCX has too many or duplicate package parts. "
            f"Create a fresh Word import copy and retry. {_PRESERVED}"
        )
    if reason == "The DOCX contains an unsafe package path.":
        return (
            f"This DOCX has an unsafe internal package path. "
            f"Export a fresh DOCX from Word instead of renaming or editing its ZIP contents. "
            f"{_PRESERVED}"
        )
    if reason == "Choose a valid Word DOCX document.":
        return f"The uploaded file is not a valid Word DOCX. Export a new DOCX and retry. {_PRESERVED}"
    if reason == "Table is too wide to review safely.":
        return f"A DOCX table is too wide to review safely. Split the table in an import copy. {_PRESERVED}"
    if reason == "This DOCX could not be safely read. No library content was changed.":
        return f"The DOCX could not be safely read. Export a fresh Word copy and retry. {_PRESERVED}"

    # This includes arbitrary messages wrapped by importer.ImportError and
    # parser messages with unknown text. Never interpolate that input.
    return _GENERIC
