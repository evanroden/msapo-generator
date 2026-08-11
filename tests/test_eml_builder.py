from email import policy
from email.parser import BytesParser

from urllib.parse import parse_qs, urlparse

from app.eml_builder import (
    GREETING,
    build_eml,
    build_outlook_web_url,
    build_plain_body,
)


def test_default_greeting_is_contract_neutral():
    assert "David" not in GREETING
    assert GREETING == "Good afternoon. Please see below."


def test_plain_body_uses_neutral_greeting():
    body = build_plain_body([("Site Location", "Tulane Medical Center")])

    assert body.startswith("Good afternoon. Please see below.\n\n")
    assert "David" not in body
    assert "- Site Location: Tulane Medical Center" in body


def test_eml_keeps_outlook_draft_and_base64_html_body():
    raw = build_eml(
        to="administrator@example.com",
        subject="Vendor repair at Site MSA PO",
        bullets=[("Amount", "$4,546.50")],
        attachments=[("quote.pdf", b"quote")],
    )
    message = BytesParser(policy=policy.default).parsebytes(raw)

    assert message["To"] == "administrator@example.com"
    assert message["X-Unsent"] == "1"
    assert message.get_content_type() == "multipart/mixed"

    html_part = next(part for part in message.walk() if part.get_content_type() == "text/html")
    assert html_part["Content-Transfer-Encoding"] == "base64"
    assert "Good afternoon. Please see below." in html_part.get_content()
    assert "David" not in html_part.get_content()


def test_outlook_web_compose_url_preserves_recipient_subject_and_body():
    url = build_outlook_web_url(
        to="approver+rrh@example.com",
        subject="Expense report & receipts",
        body="Good afternoon.\n\n- Total: $31.25\n",
    )
    parsed = urlparse(url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "outlook.office.com"
    assert parsed.path == "/mail/deeplink/compose"
    assert parse_qs(parsed.query) == {
        "to": ["approver+rrh@example.com"],
        "subject": ["Expense report & receipts"],
        "body": ["Good afternoon.\n\n- Total: $31.25\n"],
    }
