# The ENFRA master is verified with Ubuntu 24.04's LibreOffice 24.2 renderer.
# A floating Debian/LibreOffice major changes Word shape and table pagination.
FROM ubuntu:24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2 \
    PATH="/opt/venv/bin:$PATH"

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
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        ca-certificates \
        fontconfig \
        libreoffice-calc \
        libreoffice-writer \
        curl \
        fonts-dejavu-core \
        fonts-dejavu-extra \
        fonts-liberation \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fonts-texgyre \
        fonts-opensymbol \
        fonts-urw-base35 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.lock ./
RUN python3.12 -m venv /opt/venv \
    && python -m pip install -r requirements.lock \
    && python -m pip check

COPY . .

ENV FONTCONFIG_FILE=/app/runtime/fonts.conf

RUN python runtime/check_renderer.py

RUN python scripts/patch_streamlit_metadata.py

RUN mkdir -p output

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "run_web.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
