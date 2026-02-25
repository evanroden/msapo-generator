"""
FastAPI webhook receiver for inbound email processing.

Designed for SendGrid Inbound Parse but adaptable to Postmark or others.
SendGrid posts multipart form data with fields like:
  - from, to, subject, text, html
  - attachment1, attachment-info, etc.

Flow:
  1. Receive the inbound email POST
  2. Extract quote text from body or attachments
  3. Analyze via Anthropic
  4. Generate MSAPO .docx and .pdf
  5. Email the files back to the original sender
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse

from app.ocr import extract_text
from app.quote_analyzer import analyze_quote
from app.document_generator import generate_docx
from app.pdf_converter import convert_to_pdf
from app.email_handler import send_msapo_email
from app.config import WEBHOOK_SECRET

logger = logging.getLogger("msapo.webhook")

app = FastAPI(title="MSAPO Generator – Inbound Email Webhook")


def _extract_sender_email(from_field: str) -> str:
    """Parse 'Name <email@example.com>' into just the email address."""
    match = re.search(r"<([^>]+)>", from_field)
    if match:
        return match.group(1)
    return from_field.strip()


@app.post("/webhook/inbound-email")
async def inbound_email(request: Request):
    """
    Endpoint for SendGrid Inbound Parse webhook.
    Content-Type: multipart/form-data
    """
    form = await request.form()

    # Optional: verify webhook secret via a custom header or query param
    if WEBHOOK_SECRET:
        token = request.query_params.get("token", "")
        if token != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    sender = _extract_sender_email(form.get("from", ""))
    subject = form.get("subject", "")
    body_text = form.get("text", "") or form.get("html", "")

    logger.info("Inbound email from %s | subject: %s", sender, subject)

    # ── Gather quote text ────────────────────────────────────────────
    quote_text = ""

    # Check for attachments first (SendGrid names them attachment1, attachment2, …)
    attachment_info_raw = form.get("attachment-info", "{}")
    try:
        attachment_info = json.loads(attachment_info_raw)
    except json.JSONDecodeError:
        attachment_info = {}

    for key in attachment_info:
        upload: UploadFile | None = form.get(key)
        if upload is not None:
            file_bytes = await upload.read()
            filename = upload.filename or "attachment"
            try:
                extracted = extract_text(file_bytes, filename)
                if extracted.strip():
                    quote_text += f"\n\n--- Attachment: {filename} ---\n{extracted}"
            except Exception as exc:
                logger.warning("Failed to extract text from %s: %s", filename, exc)

    # Fall back to email body if no attachment text
    if not quote_text.strip():
        quote_text = body_text

    if not quote_text.strip():
        return JSONResponse(
            {"error": "No quote text found in email body or attachments."},
            status_code=400,
        )

    # ── Process ──────────────────────────────────────────────────────
    try:
        analysis = analyze_quote(quote_text)
        docx_path = generate_docx(analysis)
        pdf_path = convert_to_pdf(docx_path)
    except Exception as exc:
        logger.exception("Processing failed")
        return JSONResponse(
            {"error": f"Processing failed: {exc}"},
            status_code=500,
        )

    # ── Reply ────────────────────────────────────────────────────────
    try:
        result = send_msapo_email(
            to_email=sender,
            vendor_name=analysis.vendor_name,
            docx_path=docx_path,
            pdf_path=pdf_path,
            tax_warning=analysis.tax_warning,
            ai_assumptions=analysis.ai_assumptions,
        )
        logger.info("Reply sent to %s – status %s", sender, result["status_code"])
    except Exception as exc:
        logger.exception("Email send failed")
        return JSONResponse(
            {"error": f"Email send failed: {exc}"},
            status_code=500,
        )

    return {"status": "ok", "vendor": analysis.vendor_name, "sent_to": sender}


@app.get("/health")
async def health():
    return {"status": "healthy"}
