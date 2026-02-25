FROM python:3.12-slim

# Install LibreOffice for PDF conversion
RUN apt-get update && \
    apt-get install -y --no-install-recommends libreoffice-writer curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure output directory exists
RUN mkdir -p output

EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "run_web.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
