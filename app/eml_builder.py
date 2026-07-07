"""
Build RFC 2822 .eml files with attachments using Python stdlib.

Uses HTML body so Outlook places the signature AFTER the email content
(plain-text .eml bodies cause Outlook to insert the signature first).

The user downloads the .eml, double-clicks to open in Outlook,
reviews the pre-filled email, and hits Send.
"""

from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote


DAVID_EMAIL = "david.siegal@enfrasolutions.com"


def build_eml(
    *,
    to: str = DAVID_EMAIL,
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
    """Return raw .eml bytes for an email to David with all attachments.

    Parameters
    ----------
    attachments : list of (filename, file_bytes) tuples
        Typically: original quote, .docx, .pdf — three separate files.
    """
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["From"] = ""  # Left blank — Outlook fills in the sender
    msg["X-Unsent"] = "1"  # Opens in Outlook compose mode with Send button

    # HTML body — Outlook places its auto-signature after this content.
    # Headings are bold; no "Best, Evan" since the Outlook signature covers it.
    html_body = f"""\
<html>
<body style="font-family: Calibri, Arial, sans-serif; font-size: 11pt; color: #000000;">
<p>Good afternoon, David. Please see below.</p>
<ul style="list-style-type: disc; padding-left: 20px;">
  <li><b>Site Location:</b>
    <ul style="list-style-type: disc;"><li>RRH {_esc(site_short_name)}</li></ul>
  </li>
  <li><b>Job cost code:</b>
    <ul style="list-style-type: disc;"><li>{_esc(cost_code)}</li></ul>
  </li>
  <li><b>Subcontractor name:</b>
    <ul style="list-style-type: disc;"><li>{_esc(vendor_name)}</li></ul>
  </li>
  <li><b>Contact Name:</b>
    <ul style="list-style-type: disc;"><li>{_esc(contact_name)}</li></ul>
  </li>
  <li><b>Contact Email:</b>
    <ul style="list-style-type: disc;"><li>{_esc(contact_email)}</li></ul>
  </li>
  <li><b>Description:</b>
    <ul style="list-style-type: disc;"><li>{_esc(description)}</li></ul>
  </li>
  <li><b>Amount:</b>
    <ul style="list-style-type: disc;"><li>{_esc(amount)}</li></ul>
  </li>
</ul>
</body>
</html>"""

    # Set as HTML content so Outlook handles signature placement correctly
    msg.set_content(html_body, subtype="html")

    for filename, data in attachments:
        maintype, subtype = _guess_mime(filename)
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    return msg.as_bytes()


def build_plain_body(
    *,
    site_short_name: str,
    cost_code: str,
    vendor_name: str,
    contact_name: str,
    contact_email: str,
    description: str,
    amount: str,
) -> str:
    """Plain-text version of the email body, for mailto: links and the
    iOS share sheet (Apple Mail can't take HTML from either)."""
    return (
        "Good afternoon, David. Please see below.\n\n"
        f"- Site Location: RRH {site_short_name}\n"
        f"- Job cost code: {cost_code}\n"
        f"- Subcontractor name: {vendor_name}\n"
        f"- Contact Name: {contact_name}\n"
        f"- Contact Email: {contact_email}\n"
        f"- Description: {description}\n"
        f"- Amount: {amount}\n"
    )


def build_mailto_url(*, to: str = DAVID_EMAIL, subject: str, body: str) -> str:
    """mailto: URL that opens a pre-filled draft in the default mail app.

    Attachments cannot be passed through mailto: — on iOS they are shared
    to Mail separately via the share sheet.
    """
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body)}"


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _guess_mime(filename: str) -> tuple[str, str]:
    """Return (maintype, subtype) for a filename."""
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        main, sub = mime.split("/", 1)
        return main, sub
    return "application", "octet-stream"
