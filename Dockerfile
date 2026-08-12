FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Calc renders the official reimbursement workbook plus receipt worksheet as a
# single PDF. Writer retains the existing MSAPO conversion path. Fonts keep the
# supplied templates and generated signature layout stable in the container.
#
# Both signature fonts in app.expense_report._SIGNATURE_FONT_CANDIDATES must be
# installable here or the fallback is a fiction. fonts-urw-base35 supplies
# Z003-MediumItalic.otf (the preferred cursive face). DejaVuSerif-Italic.ttf is
# in fonts-dejavu-EXTRA, not -core: with only -core installed the second
# candidate could never resolve, so signature rendering silently depended on a
# single package and would have failed closed with "The cursive signature font
# is unavailable in this deployment" had it ever been dropped.
# tests/test_expense_deployment.py enforces that this list stays in sync.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-calc \
        libreoffice-writer \
        curl \
        fonts-dejavu-core \
        fonts-dejavu-extra \
        fonts-liberation \
        fonts-urw-base35 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

RUN mkdir -p output

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "run_web.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
