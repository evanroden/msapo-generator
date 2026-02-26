"""
Build RFC 2822 .eml files with attachments using Python stdlib.

The user downloads the .eml, double-clicks to open in Outlook,
reviews the pre-filled email, and hits Send.
"""

from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from pathlib import Path


DEBBIE_EMAIL = "dpagnottelli@enfrasolutions.com"


def build_eml(
    *,
    to: str = DEBBIE_EMAIL,
    subject: str,
    site_short_name: str,
    cost_code: str,
    vendor_name: str,
    contact_name: str,
    contact_email: str,
    description: str,
    amount: str,
    attachments: list[tuple[str, bytes]],  # [(filename, data), ...]
) -> bytes:
    """Return raw .eml bytes for an email to Debbie with all attachments.

    Parameters
    ----------
    attachments : list of (filename, file_bytes) tuples
        Typically: original quote, .docx, .pdf — three separate files.
    """
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["From"] = ""  # Left blank — Outlook fills in the sender

    body = (
        f"Good afternoon, Debbie. Please see below.\n"
        f"* Site Location:\n"
        f"   * RRH {site_short_name}\n"
        f"* Job cost code:\n"
        f"   * {cost_code}\n"
        f"* Subcontractor name:\n"
        f"   * {vendor_name}\n"
        f"* Contact Name:\n"
        f"   * {contact_name}\n"
        f"* Contact Email:\n"
        f"   * {contact_email}\n"
        f"* Description:\n"
        f"   * {description}\n"
        f"* Amount:\n"
        f"   * {amount}\n"
        f"Best,\n"
        f"Evan"
    )
    msg.set_content(body)

    for filename, data in attachments:
        maintype, subtype = _guess_mime(filename)
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    return msg.as_bytes()


def _guess_mime(filename: str) -> tuple[str, str]:
    """Return (maintype, subtype) for a filename."""
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        main, sub = mime.split("/", 1)
        return main, sub
    return "application", "octet-stream"
