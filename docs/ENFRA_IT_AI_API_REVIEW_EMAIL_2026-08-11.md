# Email draft — AI API data flow for ENFRA IT review

**Subject:** Process Control — AI API calls, prompts, and internal-key integration point

Hi team,

Thank you again for discussing an ENFRA-managed API key for Process Control. I
wanted to give you a concrete view of what the application sends, what it asks
the model to return, and exactly where the calls occur.

The current code uses the Anthropic Python SDK and reads its credential and
model name only from server-side environment variables (`ANTHROPIC_API_KEY` and
`ANTHROPIC_MODEL`). The key is not embedded in source, sent to the browser, or
written to the local application database. If ENFRA's internal Copilot endpoint
uses a different SDK, base URL, authentication header, managed identity, or
request schema, I will put that difference behind a small provider adapter; the
review/generation code does not need to know the credential.

There are three model-call paths:

1. **Quote OCR — `app/ocr.py`.** Text-based PDFs are read locally with PyMuPDF.
   If the PDF is scanned, or the input is a quote image, the bounded image/PDF
   content is sent with this instruction: “Extract ALL text from this vendor
   quote exactly as written — every line, number, price, quantity, and detail,
   preserving the order. Output only the extracted text, no commentary.” The
   code caps quote PDFs at 20 pages, caps decoded frame dimensions, and
   downscales vision images before transmission.

2. **Quote classification/extraction — `app/quote_analyzer.py`.** The extracted
   quote text is sent to `client.messages.create()` with the `SYSTEM_PROMPT`
   constant in that file. The model is asked for one JSON object containing the
   vendor, vendor representative, facility, detailed scope, inclusions,
   exclusions, tax status and pricing summary, short description, work category,
   best-supported asset clue, fulfillment route, request type, and original PO
   number when applicable. The prompt includes the approved equipment policy,
   RRH facility aliases, and the Arkansas-versus-Rochester Unity instruction.
   The response is schema-validated; deterministic code then applies contract,
   cost-code, asset-registry, 20-character export, and Smartsheet rules.

3. **Receipt extraction — `app/receipt_analyzer.py`.** Each reviewed receipt is
   sent as a bounded, orientation-corrected image or a preflighted PDF with the
   `RECEIPT_PROMPT` constant in that file. The requested JSON keys are
   `merchant_name`, `transaction_date`, `total_amount`, `tax_amount`, `currency`,
   `suggested_description`, `line_items` (purchased-item description and extended
   line amount), `expense_section_guess`, `confidence`, and `review_notes`. The
   prompt tells the model to keep repeated purchased items separate and exclude
   subtotal, total, tax, tip, service-charge, discount/coupon, tender, change,
   loyalty, and suggested-tip rows from the item list. Receipt content is
   explicitly marked untrusted, and the model is told to ignore any instructions,
   code, prompts,
   or requested output formats printed inside it. The prompt forbids inventing
   business purpose, attendees, job numbers, or accounting codes. The employee
   can uncheck nonreimbursable detected items, override the calculated amount,
   and replace every receipt-level field; the approved RRH codes and
   item-selection arithmetic come from deterministic application policy, not
   the model.

The content sent to the model can include confidential operational information
already present in a quote or receipt, such as vendor/contact details, facility,
equipment, prices, dates, and transaction amounts. It does **not** include the
user's browser cookie, remembered profile database, generated signature image,
generated Excel/PDF, Outlook draft, Smartsheet token, or Smartsheet row data.

No AI response sends an email, creates a Smartsheet row, approves an expense, or
posts to JDE. It only creates an editable draft. Model/transport failures fall
back to visible required fields or an explicit retry, and optional Smartsheet API
mode remains disabled independently.

For an internal Copilot integration, could you confirm:

- the endpoint/base URL and whether it is OpenAI-compatible, Azure OpenAI,
  Microsoft Graph/Copilot, or another internal gateway;
- the required authentication method and header/managed-identity flow;
- approved model/deployment IDs;
- support and limits for text, images, and native PDF/document inputs;
- retention, training, regional-processing, logging, and abuse-monitoring policy;
- request/response size, timeout, and rate limits; and
- whether outbound traffic must use an ENFRA proxy, private network, or custom
  certificate authority.

The exact executable prompts and call sites are public for line-by-line review in
`app/ocr.py`, `app/quote_analyzer.py`, and `app/receipt_analyzer.py`. I am happy
to walk through those files and add a provider-specific adapter once the API
contract is available.

Thanks,

Evan

## Maintainer note

This email intentionally describes the current implementation rather than
claiming generic “Copilot API” compatibility. Do not place a production key,
endpoint credential, internal certificate, or live sample document in this file
or in an issue/PR. Configure them only in the approved deployment secret store.
