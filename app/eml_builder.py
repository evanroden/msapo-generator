"""
Build RFC 2822 .eml files with attachments using Python stdlib.

Uses an HTML body so Outlook places the signature AFTER the email content
(plain-text .eml bodies cause Outlook to insert the signature first).

The email body is driven by a simple list of (label, value) bullet pairs so
the caller decides exactly which fields appear — MSAPO vs. Equipment-Only PO,
with or without a subtotal/tax breakdown.

The user downloads the .eml, opens it in Outlook, reviews the pre-filled
draft, and hits Send. On iPhone/iPad the same bullets feed the plain-text
body passed to the attachment-bearing share sheet. A separate mailto: link
is retained only as an explicitly attachment-free fallback.

WHO DEPENDS ON THIS: app/expense_ui.py only. The "MSAPO vs. Equipment-Only
PO" framing above is historical -- the purchase-order workflow no longer
imports or calls anything here, and
tests/test_smartsheet_handoff_entrypoint.py asserts that app/web_ui.py's
source contains no reference to this module's builder. Wiring a PO route
back through here therefore fails that test, by design: the PO handoff is a
Smartsheet submission, not an email.

Also deliberately absent: an Outlook-web "compose URL" helper. One existed
and was deleted on 2026-08-11 because such a URL can prefill text but
CANNOT carry local attachment bytes, so the employee sent an approval email
with no report in it and nothing anywhere reported a failure. Restoring it
as a primary route silently reintroduces that defect -- see
docs/COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md, invariant
5.
"""

from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from urllib.parse import quote

# The app now supports many contracts. A neutral default is safe for every
# administrator and avoids addressing a recipient by the wrong name.
#
# This string is PINNED verbatim by tests/test_eml_builder.py, which also
# asserts that the first name of the original single-contract administrator
# never reappears in it or in any body built from it. That test is the record
# of the incident: the greeting used to name one person, and every contract
# added after that shipped drafts addressed to the wrong administrator.
# Callers that know the real recipient pass their own `greeting=`.
GREETING = "Good afternoon. Please see below."

# A bullet is a (label, value) pair, e.g. ("Job cost code", "01GCHEM").
Bullet = tuple[str, str]


def build_plain_body(bullets: list[Bullet], greeting: str = GREETING) -> str:
    """Plain-text body for mailto: links and the iOS share sheet.

    Guarantees a trailing newline and one "- label: value" line per bullet, in
    the order given. Values are interpolated raw: this output is destined for
    percent-encoding in a mailto: URL or for a share sheet's plain-text field,
    never for HTML, so escaping here would put literal "&amp;" in front of the
    employee.

    Callers deliberately pass a SHORTER bullet list here than to build_eml --
    share sheets and mailto: URLs both truncate long bodies, while the .eml
    carries the full list. Do not "unify" the two call sites into one bullet
    list without re-checking that asymmetry (app/expense_ui.py documents it).
    """
    lines = [greeting, ""]
    for label, value in bullets:
        lines.append(f"- {label}: {value}")
    return "\n".join(lines) + "\n"


def _html_body(bullets: list[Bullet], greeting: str = GREETING) -> str:
    """Render the bullets as the inline-styled HTML Outlook will display.

    Every style is an inline `style=` attribute on purpose. Outlook for Windows
    renders mail through Word's HTML engine, which discards <style> blocks and
    external stylesheets outright -- a rule moved into a stylesheet does not
    error, it simply stops applying, and the draft arrives as unstyled
    Times New Roman.

    Each bullet is a nested single-item <ul> rather than "label: value" on one
    line so a long value wraps under its label instead of ragged-right beside
    it. That is why the markup looks redundant; collapsing it changes the
    rendered layout in Outlook, not just the source.
    """
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
    to: str,
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

    Contract
    --------
    Builds a DRAFT. Nothing here transmits anything: the bytes are handed to a
    browser download and the employee reviews and sends from their own mail
    client. Do not add an SMTP/Graph send path behind this signature.

    Assumes the caller has already decided WHICH artifact to attach. It
    attaches exactly what it is given, so passing the editable workbook here
    would put it in the approval email; app/expense_ui.py passes
    email_attachments_for_package(), which returns the submission PDF only.

    Raises ValueError (from the stdlib header policy) if `to` or `subject`
    contains CR or LF. That is the header-injection guard and the only failure
    mode: everything else about the message is constructed, not parsed.

    Raises ValueError on an EMPTY `attachments` list. The body this function
    writes tells the approver to review "the attached expense report", so a
    draft with nothing attached is a message that lies about itself.

    That used to be a documented CALLER obligation rather than an enforced one.
    The single caller, expense_ui._build_expense_eml, does honour it -- it
    raises ExpenseReportError when package.pdf_bytes is empty -- so this is
    defence in depth, not a live fix. It is enforced here because the obligation
    was invisible at the call site: a second caller would have to read this
    docstring to learn about it, and the failure it prevents is silent.
    """
    if not attachments:
        raise ValueError(
            "Refusing to build an approval draft with no attachment: the body "
            "describes an attached report."
        )

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


def build_mailto_url(*, to: str, subject: str, body: str) -> str:
    """mailto: URL that opens a pre-filled draft in the default mail app.

    Attachments cannot be passed through mailto:. The primary iOS action uses
    Web Share instead and passes the completed PDF directly.

    This helper survives only as the explicitly ATTACHMENT-FREE fallback in the
    collapsed options area, and the UI label must keep saying so (2026-08-11
    handoff, invariant 6). A control wired to this while claiming the report is
    attached fails in the worst possible way: the employee sends an approval
    request with no report and neither browser nor mail client reports
    anything wrong.

    `safe='@'` on the recipient replaces quote()'s default safe set, so "/" is
    encoded too; the subject and body are fully encoded, which is what turns
    build_plain_body's newlines into %0A rather than terminating the URL.
    """
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body)}"


def _esc(text: str) -> str:
    """Escape HTML special characters for TEXT-NODE use only.

    The apostrophe is intentionally NOT escaped, which is safe only because
    every value passing through here lands between tags. _html_body's `style`
    attributes are hardcoded literals for exactly this reason. If you ever
    interpolate an escaped value into a single-quoted attribute, this function
    is no longer sufficient -- use html.escape(..., quote=True) there instead.

    str() first because callers pass whatever came off a receipt or a form
    field, and a None or a Decimal must render, not raise.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _guess_mime(filename: str) -> tuple[str, str]:
    """Return (maintype, subtype) for a filename, never raising.

    Falls back to application/octet-stream rather than failing, because a
    wrong content type still lets Outlook attach and send the file whereas an
    exception here would destroy an otherwise complete draft. Outlook keys off
    the filename extension anyway.

    Two known imprecisions, both harmless for the only artifact this app
    attaches (a .pdf): mimetypes consults the host's mime database, so an
    exotic extension can resolve differently on the container than on a
    developer laptop; and the encoding half of guess_type is discarded, so
    "report.pdf.gz" is announced as application/pdf.
    """
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        main, sub = mime.split("/", 1)
        return main, sub
    return "application", "octet-stream"
