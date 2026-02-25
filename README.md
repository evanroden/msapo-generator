# MSAPO Scope of Work Generator

Processes vendor quotes and generates standard Scope of Work (MSAPO) documents in `.docx` and `.pdf` formats using the Anthropic Claude API.

## Features

- **Web Interface** (Streamlit) — Upload a quote PDF/image/text and download generated files
- **Email Interface** (FastAPI webhook) — Forward a quote via email, receive MSAPO files back
- **AI-powered extraction** — Vendor, scope, inclusions/exclusions via Claude
- **AI assumption flagging** — Missing items are inferred and marked `[AI ESTIMATE: ...]`
- **Tax verification** — Warns when tax status is unclear
- **Price stripping** — All dollar amounts are removed from generated documents
- **Facility auto-fill** — Cross-references RRH St. Mary's and United Memorial Medical Center
- **Template-driven** — Uses your `Master_MSAPO_Template.docx` with `{{TAG}}` placeholders

## Project Structure

```
msapo-generator/
├── app/
│   ├── config.py              # Environment settings & facility data
│   ├── quote_analyzer.py      # Anthropic API integration
│   ├── document_generator.py  # python-docx template filling
│   ├── pdf_converter.py       # DOCX → PDF (LibreOffice/Gotenberg/docx2pdf)
│   ├── email_handler.py       # SendGrid email with attachments
│   ├── ocr.py                 # PDF/image text extraction
│   ├── webhook.py             # FastAPI inbound email endpoint
│   └── web_ui.py              # Streamlit web portal
├── templates/
│   └── Master_MSAPO_Template.docx
├── output/                    # Generated files land here
├── create_template.py         # One-time scaffold template generator
├── run_web.py                 # Streamlit entry point
├── run_api.py                 # FastAPI entry point
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Quick Start (Local)

### 1. Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- LibreOffice (for PDF conversion on Linux/Mac) **or** MS Word (for `docx2pdf` on Windows)

### 2. Install

```bash
cd msapo-generator
python -m venv .venv
# Linux/Mac:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and fill in your ANTHROPIC_API_KEY (required)
# Fill in SENDGRID_API_KEY and EMAIL_FROM if using the email interface
```

### 4. Set Up the Template

**Option A — Use the scaffold generator:**

```bash
python create_template.py
```

This creates a starter `templates/Master_MSAPO_Template.docx` with placeholder tags and checkbox tables.

**Option B — Use your own template:**

Place your real `Master_MSAPO_Template.docx` in the `templates/` folder. Ensure it contains these placeholder tags where you want data inserted:

| Tag | Replaced With |
|---|---|
| `{{DATE}}` | Today's date |
| `{{VENDOR}}` | Vendor / contractor name |
| `{{FACILITY_NAME}}` | Matched facility name |
| `{{FACILITY_ADDRESS}}` | Facility street address |
| `{{PROJECT_DESCRIPTION}}` | Short project description |

The Scope of Work details (inclusions, exclusions, warnings) are **appended after** your existing template content, so your checkbox tables and approval sections at the top are preserved.

### 5. Run the Web UI

```bash
streamlit run run_web.py
```

Open `http://localhost:8501` in your browser.

### 6. Run the Email Webhook API

```bash
python run_api.py
# or:
uvicorn app.webhook:app --host 0.0.0.0 --port 8000
```

The webhook endpoint is: `POST http://your-server:8000/webhook/inbound-email`

## Docker Deployment

```bash
docker compose up --build
```

This starts both the Streamlit UI (port 8501) and the FastAPI webhook (port 8000).

Mount your real template into the container via the `templates/` volume.

## PDF Conversion Backends

Set `PDF_BACKEND` in `.env`:

| Backend | Requirements | Best For |
|---|---|---|
| `libreoffice` | LibreOffice installed (`apt install libreoffice-writer`) | Linux servers, Docker |
| `gotenberg` | [Gotenberg](https://gotenberg.dev/) Docker container running | Containerized deploys |
| `docx2pdf` | MS Word installed + `pip install docx2pdf` | Windows/macOS dev machines |

The Dockerfile already includes LibreOffice, so `libreoffice` works out of the box with Docker.

### Using Gotenberg

Uncomment the `gotenberg` service in `docker-compose.yml` and set:

```
PDF_BACKEND=gotenberg
GOTENBERG_URL=http://gotenberg:3000
```

## Email Webhook Setup (SendGrid Inbound Parse)

1. In SendGrid, go to **Settings → Inbound Parse**
2. Add a host/domain (e.g., `parse.yourdomain.com`)
3. Point the webhook URL to: `https://your-server/webhook/inbound-email`
4. Set the MX record for your domain as instructed by SendGrid
5. Forward vendor quotes to your parse address (e.g., `quote@parse.yourdomain.com`)
6. The app processes the quote and emails back the `.docx` and `.pdf`

Optional: add `?token=YOUR_SECRET` to the webhook URL and set `WEBHOOK_SECRET` in `.env` for authentication.

## Hardcoded Facilities

The tool auto-matches these facilities from quote text:

- **RRH St. Mary's Medical Center** — 89 Genesee St, Rochester, NY 14611
- **United Memorial Medical Center** — 127 North Street, Batavia, NY 14020

To add more facilities, edit the `FACILITIES` dict in `app/config.py`.

## Business Rules

- **No prices in SOW**: All dollar amounts, hourly rates, and cost figures are stripped from generated documents. The Anthropic prompt enforces this, and a regex post-processor catches any residuals.
- **AI assumptions flagged**: Any inferred inclusions/exclusions are wrapped in `[AI ESTIMATE: ...]` and highlighted in orange in the document.
- **Tax warnings**: If tax status is missing or ambiguous, a red warning appears in both the document and the email/web UI.

## Troubleshooting

| Problem | Solution |
|---|---|
| `Template not found` | Place `Master_MSAPO_Template.docx` in `templates/` or run `python create_template.py` |
| `LibreOffice not on PATH` | Install with `apt install libreoffice-writer` or switch to `gotenberg`/`docx2pdf` |
| PDF conversion hangs | LibreOffice may have a lock file — kill stale `soffice` processes |
| Anthropic API error | Check your `ANTHROPIC_API_KEY` in `.env` |
| Email not sending | Verify `SENDGRID_API_KEY` and `EMAIL_FROM` are set; check SendGrid dashboard for errors |
