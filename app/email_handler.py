"""
Email handler: sends the generated MSAPO .docx and .pdf back to the sender.

Uses SendGrid Web API v3.  Swap in any SMTP library if preferred.
"""

from __future__ import annotations

import base64
from pathlib import Path

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    ContentId,
    Disposition,
    FileContent,
    FileName,
    FileType,
    Mail,
)

from app.config import SENDGRID_API_KEY, EMAIL_FROM


def _build_attachment(file_path: Path, mime: str) -> Attachment:
    data = file_path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    attachment = Attachment()
    attachment.file_content = FileContent(encoded)
    attachment.file_name = FileName(file_path.name)
    attachment.file_type = FileType(mime)
    attachment.disposition = Disposition("attachment")
    return attachment


def send_msapo_email(
    to_email: str,
    vendor_name: str,
    docx_path: Path,
    pdf_path: Path,
    tax_warning: str | None = None,
    ai_assumptions: list[str] | None = None,
) -> dict:
    """
    Send an email with both the .docx and .pdf MSAPO files attached.
    Returns the SendGrid API response status.
    """
    subject = f"MSAPO Generated – {vendor_name}"

    body_lines = [
        f"Your MSAPO Scope of Work for <b>{vendor_name}</b> is attached.",
        "",
    ]

    if tax_warning:
        body_lines.append(
            f'<p style="color:red;font-weight:bold;">⚠ {tax_warning}</p>'
        )

    if ai_assumptions:
        body_lines.append("<p><b>AI-Generated Assumptions (review required):</b></p><ul>")
        for a in ai_assumptions:
            body_lines.append(f"<li style='color:#CC6600'>[AI ESTIMATE: {a}]</li>")
        body_lines.append("</ul>")

    body_lines.append("<p>Please review before finalizing.</p>")
    html_body = "\n".join(body_lines)

    message = Mail(
        from_email=EMAIL_FROM,
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )

    message.add_attachment(
        _build_attachment(
            docx_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    )
    message.add_attachment(
        _build_attachment(pdf_path, "application/pdf")
    )

    sg = SendGridAPIClient(api_key=SENDGRID_API_KEY)
    response = sg.send(message)

    return {
        "status_code": response.status_code,
        "body": response.body,
    }
