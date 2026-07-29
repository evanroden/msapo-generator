FROM python:3.12-slim

ARG EPC_REQUIREMENTS_FILE=requirements.txt
ARG INSTALL_LIBREOFFICE=true

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    if [ "$INSTALL_LIBREOFFICE" = "true" ]; then \
      apt-get install -y --no-install-recommends libreoffice-writer; \
    fi && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements*.txt ./
RUN python -m pip install --no-cache-dir -r "$EPC_REQUIREMENTS_FILE"

COPY . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/_stcore/health' % os.getenv('PORT', os.getenv('EPC_PORT','8501')), timeout=5)" || exit 1

CMD ["python", "-m", "app.entrypoint"]
