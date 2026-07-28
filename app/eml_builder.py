"""
Build RFC 2822 .eml files with attachments using Python stdlib.

Uses an HTML body so Outlook places the signature AFTER the email content
(plain-text .eml bodies cause Outlook to insert the signature first).

The email body is driven by a simple list of (label, value) bullet pairs so
the caller decides exactly which fields appear — MSAPO vs. Equipment-Only PO,
with or without a subtotal/tax breakdown.

The user downloads the .eml, opens it in Outlook, reviews the pre-filled
draft, and hits Send.  On iPhone/iPad the same bullets feed a plain-text
body used by the share sheet and mailto: links.
"""

from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from urllib.parse import quote

DAVID_EMAIL = "david.siegal@enfrasolutions.com"
# The app now supports many contracts. A neutral default is safe for every
# administrator and avoids addressing non-RRH recipients as David.
GREETING = "Good afternoon. Please see below."

# A bullet is a (label, value) pair, e.g. ("Job cost code", "01GCHEM").
Bullet = tuple[str, str]


def build_plain_body(bullets: list[Bullet], greeting: str = GREETING) -> str:
    """Plain-text body for mailto: links and the iOS share sheet (neither
    can take HTML)."""
    lines = [greeting, ""]
    for label, value in bullets:
        lines.append(f"- {label}: {value}")
    return "\n".join(lines) + "\n"


def _html_body(bullets: list[Bullet], greeting: str = GREETING) -> str:
    items = "\n".join(
        f'  <li><b>{_esc(label)}:</b>'
        f'<ul style="list-style-type: disc;"><li>{_esc(value)}</li></ul></li>'
        for label, value in bullets
    )
    return (
        '<html>\n<body style="font-family: Calibri, Arial, sans-serif; '
        'font-size: 11pt; color: #000000;">\n'
        f"<p>{_esc(greeting)}</p>\n"
        '<ul style="list-style-type: disc; padding-left: 20px;">\n'
        f"{items}\n"
        "</ul>\n</body>\n</html>"
    )


def build_eml(
    *,
    to: str = DAVID_EMAIL,
    subject: str,
    bullets: list[Bullet],
    attachments: list[tuple[str, bytes]],  # [(filename, data), ...]
    greeting: str = GREETING,
) -> bytes:
    """Return raw .eml bytes with a ready-to-send body and attachments.

    Parameters
    ----------
    bullets : list of (label, value) tuples rendered as the email body.
    attachments : list of (filename, file_bytes) tuples.
    """
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["From"] = ""  # Left blank — Outlook fills in the sender
    msg["X-Unsent"] = "1"  # Opens in Outlook compose mode with Send button

    # HTML body — Outlook places its auto-signature after this content.
    # base64 (not the default quoted-printable): QP wraps long lines with "="
    # soft breaks, which Outlook Web fails to re-join when composing from an
    # imported .eml, corrupting the text ("Walla=e", "$8,4=0.00", "<=ul>").
    msg.set_content(_html_body(bullets, greeting), subtype="html", cte="base64")

    for filename, data in attachments:
        maintype, subtype = _guess_mime(filename)
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    return msg.as_bytes()


def build_mailto_url(*, to: str = DAVID_EMAIL, subject: str, body: str) -> str:
    """mailto: URL that opens a pre-filled draft in the default mail app.

    Attachments cannot be passed through mailto: — on iOS they are shared to
    Mail separately via the share sheet.
    """
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body)}"


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
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
