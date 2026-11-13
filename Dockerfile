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

# .dockerignore excludes tests/, so keep the synthetic QA archive in runtime/.
# Fail the image build instead of deploying a fixture-picker that cannot load.
RUN test -f runtime/qa_fixtures/ENFRA_Synthetic_Imperfect_Vendor_Chemical_QA_Pack.zip

ENV FONTCONFIG_FILE=/app/runtime/fonts.conf

RUN python runtime/check_renderer.py

# Absolute address used in link previews. A host other than Render passes its
# public https origin, e.g. --build-arg PUBLIC_SITE_ORIGIN=https://example.org
ARG PUBLIC_SITE_ORIGIN=https://msapo-generator.onrender.com
RUN python scripts/patch_streamlit_metadata.py --origin "$PUBLIC_SITE_ORIGIN"
RUN python scripts/patch_streamlit_frontend.py
RUN python scripts/patch_streamlit_date_input.py

RUN mkdir -p output

# Render reports the served commit at runtime (RENDER_GIT_COMMIT). Other hosts
# stamp it here so About can still show it, e.g.
#   --build-arg APP_GIT_COMMIT=$(git rev-parse HEAD)
# Last, so a new commit rebuilds only this layer.
ARG APP_GIT_COMMIT=""
ENV APP_GIT_COMMIT=$APP_GIT_COMMIT
LABEL org.opencontainers.image.revision="${APP_GIT_COMMIT}" \
      org.opencontainers.image.source="https://github.com/evanroden/msapo-generator"

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
    CMD python scripts/container_portability.py ready || exit 1

CMD ["streamlit", "run", "run_web.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
